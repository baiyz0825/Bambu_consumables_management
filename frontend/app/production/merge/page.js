"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { ApiError } from "../../../lib/api";
import {
  analyze,
  downloadOutput,
  formatBytes,
  formatDuration,
  listPresets,
  makeTestFile,
  merge,
  upload3mf
} from "../../../lib/plate-merger-api";
import { Badge } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../../components/ui/card";
import { ColorBlock } from "../../../components/ui/color-block";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "../../../components/ui/dialog";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { NativeSelect } from "../../../components/ui/native-select";
import { MergeAdvancedParams } from "../../../components/production/merge-advanced-params";
import { MergeSoundEditor } from "../../../components/production/merge-sound-editor";

// 后端 MergeIn 的默认预设（预设接口异常时兜底，避免发出空串）
const DEFAULT_PRESET = "builtin:a1-conservative";

// 单个 3MF 最多 9 盘（与后端 AnalyzeIn / MergeIn 的 plate 语义一致：1 起）
const PLATE_NUMBERS = Array.from({ length: 9 }, (_, i) => i + 1);

// 首尾处理策略：后端 StartEndPolicy = full / slim / turbo
const POLICY_OPTIONS = [
  {
    value: "slim",
    label: "精简（slim，默认）",
    hint: "剥离开头的降温、调平与归位，但保留退料。喷嘴不会带着融化的料移动，是可靠性与速度的平衡点。"
  },
  {
    value: "full",
    label: "全保留（full，最稳）",
    hint: "每盘都完整执行切片器原始的 start/end G-code：重新加热、调平、退料。最稳，但每盘多花几分钟。"
  },
  {
    value: "turbo",
    label: "极速（turbo，需实测）",
    hint: "连退料也剥离，换盘后直接开打。最快，但首层质量取决于热床与喷嘴残料状态，必须先在实机验证。"
  }
];

// 盘号显示：后端 PlateDisplay = off / m73 / m117 / both
const PLATE_DISPLAY_OPTIONS = [
  { value: "off", label: "关闭（off，默认）" },
  { value: "m73", label: "M73 剩余时间（m73）" },
  { value: "m117", label: "M117 屏幕文本（m117）" },
  { value: "both", label: "两者都开（both）" }
];

// 提示音：后端 AudioMode = off / short / jingle
const AUDIO_OPTIONS = [
  { value: "off", label: "关闭" },
  { value: "short", label: "短提示音" },
  { value: "jingle", label: "铃声" },
  { value: "custom", label: "自定义乐谱（高级）" }
];

//: 自定义音效的起始模板（Bambu M1006 乐谱：每条写三个音符）
const CUSTOM_SOUND_PLACEHOLDER =
  "M1006 A0 B20 L100 C44 D10 M60 E44 F10 N60\nM1006 A0 B10 L100 C48 D10 M60 E48 F10 N60\nM1006 A0 B10 L100 C51 D20 M60 E51 F10 N60";

/** 把多行乐谱文本拆成数组（去空行 + trim） */
function splitNotes(text) {
  return String(text || "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

let rowSeq = 0;

function nextRowId() {
  rowSeq += 1;
  return `merge-row-${rowSeq}`;
}

/** 统一把后端/网络错误转成一句可展示的中文。 */
function errorText(err) {
  if (err instanceof ApiError) {
    if (err.detail && typeof err.detail === "object" && typeof err.detail.message === "string") {
      return err.detail.message;
    }
    return err.message || "请求失败";
  }
  return String(err?.message || err || "未知错误");
}

/** 克数展示：大数取整、小数保留一位。 */
function fmtGrams(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "-";
  return n >= 100 ? String(Math.round(n)) : n.toFixed(1);
}

/** 「第 1 盘、第 3 盘」 */
function fmtPlateList(list) {
  const arr = Array.isArray(list) ? list : [];
  if (arr.length === 0) return "-";
  return arr.map((n) => `第 ${n} 盘`).join("、");
}

/**
 * 输出文件名清洗：去掉路径分隔符，缺后缀补 .3mf。
 * 后端只取纯文件名写入产物目录，留空则由后端生成默认名。
 */
function normalizeOutputName(raw) {
  const trimmed = String(raw || "").trim();
  if (!trimmed) return null;
  const safe = trimmed.replace(/[\\/]+/g, "_");
  return safe.toLowerCase().endsWith(".3mf") ? safe : `${safe}.3mf`;
}

function Metric({ label, value, hint }) {
  return (
    <div className="rounded-xl bg-[#f5f5f7] p-3 dark:bg-[#2c2c2e]">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-xl font-semibold tracking-tight text-foreground">{value}</div>
      {hint ? <div className="mt-1 text-xs text-muted-foreground">{hint}</div> : null}
    </div>
  );
}

function UploadBadge({ status }) {
  if (status === "uploading") return <Badge variant="info">上传中…</Badge>;
  if (status === "error") return <Badge variant="destructive">上传失败</Badge>;
  return <Badge variant="success">已就绪</Badge>;
}

export default function Page() {
  const inputRef = useRef(null);

  // 文件行：{ id, raw: File, name, size, plate, status, path, error }
  const [rows, setRows] = useState([]);
  const [dragging, setDragging] = useState(false);

  const [presets, setPresets] = useState([]);
  const [presetsLoading, setPresetsLoading] = useState(true);
  const [presetId, setPresetId] = useState("");

  const [policy, setPolicy] = useState("slim");
  const [plateDisplay, setPlateDisplay] = useState("off");
  const [preSound, setPreSound] = useState("off");
  const [postSound, setPostSound] = useState("jingle");
  const [preCustomNotes, setPreCustomNotes] = useState("");
  const [postCustomNotes, setPostCustomNotes] = useState("");
  // 音效编辑模式：visual=音符可视化，raw=直接编辑 M1006
  const [preSoundMode, setPreSoundMode] = useState("visual");
  const [postSoundMode, setPostSoundMode] = useState("visual");

  // 换盘测试文件（不加热、不耗料，验证换盘动作与提示音时序）
  const [testCycles, setTestCycles] = useState("8");
  const [testWait, setTestWait] = useState("5");
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);
  const [swapOverrides, setSwapOverrides] = useState({});
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [cooldown, setCooldown] = useState("");
  const [waitS, setWaitS] = useState("0");
  const [outputName, setOutputName] = useState("");

  const [configOpen, setConfigOpen] = useState(true);
  const [warningsDialog, setWarningsDialog] = useState(null);

  const [analysis, setAnalysis] = useState(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [merging, setMerging] = useState(false);
  const [result, setResult] = useState(null);

  // 换盘码预设：首屏拉取，默认第一项
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setPresetsLoading(true);
      try {
        const data = await listPresets();
        if (cancelled) return;
        const list = Array.isArray(data) ? data : [];
        setPresets(list);
        // 默认选中第一项；接口无数据时退回后端默认预设
        setPresetId(list[0]?.id || DEFAULT_PRESET);
      } catch (e) {
        if (!cancelled) {
          setPresetId(DEFAULT_PRESET);
          toast.error(`换盘码预设加载失败：${errorText(e)}`);
        }
      } finally {
        if (!cancelled) setPresetsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const activePreset = useMemo(
    () => presets.find((p) => p.id === presetId) || null,
    [presets, presetId]
  );

  // 已就绪文件 → analyze 入参（列表顺序即合盘顺序）
  const items = useMemo(
    () =>
      rows
        .filter((row) => row.status === "done" && row.path)
        .map((row) => ({ path: row.path, plate: Number(row.plate) || 1 })),
    [rows]
  );
  const itemsKey = useMemo(() => JSON.stringify(items), [items]);

  const uploadingCount = useMemo(
    () => rows.filter((row) => row.status === "uploading").length,
    [rows]
  );
  const failedCount = useMemo(() => rows.filter((row) => row.status === "error").length, [rows]);

  // 上传状态 / 盘号变化后自动重新统计（用 key 驱动，避免数组引用抖动）
  useEffect(() => {
    const parsedItems = itemsKey === "[]" ? [] : JSON.parse(itemsKey);
    // 输入变了，上一次的产物就不再对应当前配置，先清掉避免误下载
    setResult(null);
    if (parsedItems.length === 0) {
      setAnalysis(null);
      setAnalyzing(false);
      return undefined;
    }

    let cancelled = false;
    setAnalyzing(true);
    analyze(parsedItems)
      .then((data) => {
        if (!cancelled) setAnalysis(data || null);
      })
      .catch((e) => {
        if (!cancelled) {
          setAnalysis(null);
          toast.error(`统计失败：${errorText(e)}`);
        }
      })
      .finally(() => {
        if (!cancelled) setAnalyzing(false);
      });

    return () => {
      cancelled = true;
    };
  }, [itemsKey]);

  async function uploadRow(id, file) {
    try {
      const res = await upload3mf(file);
      if (!res?.path) {
        throw new ApiError("上传返回缺少文件路径，请重试", { status: 0 });
      }
      setRows((prev) =>
        prev.map((row) =>
          row.id === id
            ? {
                ...row,
                status: "done",
                path: res.path,
                name: res.name || row.name,
                size: Number.isFinite(Number(res.size)) ? Number(res.size) : row.size
              }
            : row
        )
      );
      return true;
    } catch (e) {
      const message = errorText(e);
      setRows((prev) =>
        prev.map((row) => (row.id === id ? { ...row, status: "error", path: null, error: message } : row))
      );
      toast.error(`${file?.name || "文件"} 上传失败：${message}`);
      return false;
    }
  }

  async function handlePickFiles(fileList) {
    const all = Array.from(fileList || []);
    if (all.length === 0) return;

    const accepted = [];
    let rejected = 0;
    for (const file of all) {
      if (String(file?.name || "").toLowerCase().endsWith(".3mf")) accepted.push(file);
      else rejected += 1;
    }
    if (rejected > 0) toast.error(`已忽略 ${rejected} 个非 .3mf 文件`);
    if (accepted.length === 0) return;

    const newRows = accepted.map((file) => ({
      id: nextRowId(),
      raw: file,
      name: file.name,
      size: file.size,
      plate: 1,
      status: "uploading",
      path: null,
      error: null
    }));

    setRows((prev) => [...prev, ...newRows]);

    // 并行上传，单条失败只影响自己那一行
    const results = await Promise.all(newRows.map((row) => uploadRow(row.id, row.raw)));
    const okCount = results.filter(Boolean).length;
    if (okCount > 0) toast.success(`${okCount} 个文件上传完成`);
  }

  function removeRow(id) {
    setRows((prev) => prev.filter((row) => row.id !== id));
  }

  function moveRow(id, delta) {
    setRows((prev) => {
      const index = prev.findIndex((row) => row.id === id);
      const target = index + delta;
      if (index < 0 || target < 0 || target >= prev.length) return prev;
      const next = [...prev];
      const tmp = next[index];
      next[index] = next[target];
      next[target] = tmp;
      return next;
    });
  }

  function changePlate(id, value) {
    const plate = Number(value);
    setRows((prev) =>
      prev.map((row) => (row.id === id ? { ...row, plate: Number.isFinite(plate) && plate >= 1 ? plate : 1 } : row))
    );
  }

  function retryRow(row) {
    if (!row?.raw) {
      toast.error("原始文件已丢失，请重新选择文件");
      return;
    }
    setRows((prev) =>
      prev.map((item) => (item.id === row.id ? { ...item, status: "uploading", error: null } : item))
    );
    uploadRow(row.id, row.raw);
  }

  async function handleMerge() {
    if (items.length === 0) {
      toast.error("请先上传至少一个 3MF 文件");
      return;
    }
    if (uploadingCount > 0) {
      toast.error("还有文件正在上传，请稍候");
      return;
    }
    if (failedCount > 0) {
      toast.error("存在上传失败的文件，请重试或删除后再合盘");
      return;
    }

    let cooldownValue = null;
    const cooldownText = String(cooldown ?? "").trim();
    if (cooldownText) {
      const n = Number(cooldownText);
      if (!Number.isFinite(n) || n < 0 || n > 120) {
        toast.error("热床冷却温度需为 0~120 之间的整数");
        return;
      }
      cooldownValue = Math.round(n);
    }

    const waitNumber = Number(waitS);
    if (!Number.isFinite(waitNumber) || waitNumber < 0) {
      toast.error("换盘后等待秒数需 >= 0");
      return;
    }

    if (preSound === "custom" && splitNotes(preCustomNotes).length === 0) {
      toast.error("自定义换盘前音效不能为空");
      return;
    }
    if (postSound === "custom" && splitNotes(postCustomNotes).length === 0) {
      toast.error("自定义换盘后音效不能为空");
      return;
    }

    setMerging(true);
    setResult(null);
    try {
      const res = await merge({
        items,
        preset: presetId || DEFAULT_PRESET,
        policy,
        plate_display: plateDisplay,
        pre_sound: preSound,
        post_sound: postSound,
        cooldown: cooldownValue,
        wait_s: Math.round(waitNumber),
        output_name: normalizeOutputName(outputName),
        swap_overrides: Object.keys(swapOverrides).length > 0 ? swapOverrides : null,
        pre_custom_notes: preSound === "custom" ? splitNotes(preCustomNotes) : null,
        post_custom_notes: postSound === "custom" ? splitNotes(postCustomNotes) : null
      });
      setResult(res || null);
      toast.success(`合盘完成：${res?.plate_count ?? items.length} 盘`);
    } catch (e) {
      toast.error(`合盘失败：${errorText(e)}`);
    } finally {
      setMerging(false);
    }
  }

  /** 生成纯换盘测试文件：不加热、不耗料，每次换盘后等待再播放滴滴滴。 */
  async function handleMakeTestFile() {
    const cycles = Number(String(testCycles).trim());
    if (!Number.isInteger(cycles) || cycles < 1 || cycles > 50) {
      toast.error("换盘次数需为 1~50 之间的整数");
      return;
    }
    const wait = Number(String(testWait).trim());
    if (!Number.isFinite(wait) || wait < 0 || wait > 300) {
      toast.error("等待秒数需为 0~300 之间的数字");
      return;
    }

    setTesting(true);
    try {
      const res = await makeTestFile(null, cycles, presetId || DEFAULT_PRESET, Math.round(wait));
      setTestResult(res || null);
      toast.success(`换盘测试文件已生成：${cycles} 次换盘`);
    } catch (e) {
      toast.error(`生成失败：${errorText(e)}`);
    } finally {
      setTesting(false);
    }
  }

  const totals = analysis?.totals || null;
  const filaments = Array.isArray(analysis?.filaments) ? analysis.filaments : [];
  const plates = Array.isArray(analysis?.plates) ? analysis.plates : [];
  const analyzeWarnings = Array.isArray(analysis?.warnings) ? analysis.warnings : [];
  const resultWarnings = Array.isArray(result?.warnings) ? result.warnings : [];
  const swapCount = Math.max(0, items.length - 1);

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight">合盘向导</h1>
          <p className="text-sm text-muted-foreground">
            把多个 3MF 的指定盘合成一个可连续打印的文件：自动注入换盘码、合并耗材元数据。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" asChild>
            <Link href="/production/gcodes">产物库</Link>
          </Button>
          <Button variant="outline" asChild>
            <Link href="/production">返回生产</Link>
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 lg:items-start">
        {/* 左列：文件选择 */}
        <Card>
          <CardHeader>
            <div className="flex items-start justify-between gap-2">
              <div>
                <CardTitle className="text-base">1. 选择切片文件</CardTitle>
                <CardDescription>
                  支持一次多选 .3mf。列表顺序即合盘顺序（第一个文件是第 1 盘），可上下调整。
                </CardDescription>
              </div>
              <Badge variant="outline">{rows.length} 个</Badge>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            <input
              ref={inputRef}
              type="file"
              accept=".3mf"
              multiple
              className="hidden"
              onChange={(e) => {
                // 先快照成数组：把 value 清空会让 FileList 同步变空（允许重复选择同一文件）
                const picked = Array.from(e.target.files || []);
                e.target.value = "";
                handlePickFiles(picked);
              }}
            />

            <div
              role="button"
              tabIndex={0}
              aria-label="选择或拖入 3MF 文件"
              onClick={() => inputRef.current?.click()}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  inputRef.current?.click();
                }
              }}
              onDragOver={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragging(false);
                handlePickFiles(e.dataTransfer?.files);
              }}
              className={`flex min-h-32 cursor-pointer flex-col items-center justify-center gap-1 rounded-xl border border-dashed p-4 text-center transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0071e3] dark:focus-visible:ring-[#0a84ff] ${
                dragging
                  ? "border-[#0071e3] bg-[#0071e3]/5 dark:border-[#0a84ff] dark:bg-[#0a84ff]/10"
                  : "border-black/15 hover:border-[#0071e3]/60 dark:border-white/20 dark:hover:border-[#0a84ff]/60"
              }`}
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="22"
                height="22"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="text-muted-foreground"
                aria-hidden="true"
              >
                <path d="M12 16V4" />
                <path d="m7 9 5-5 5 5" />
                <path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
              </svg>
              <div className="text-sm font-medium text-foreground">点击选择或拖入 3MF 文件</div>
              <div className="text-xs text-muted-foreground">支持多选，单个文件不超过 512MB</div>
            </div>

            {rows.length === 0 ? (
              <div className="rounded-xl border border-dashed p-6 text-center text-sm text-muted-foreground">
                还没有文件。拖入或选择多个 3MF 切片文件，上传完成后会自动统计盘数、时长与耗材。
              </div>
            ) : (
              <ul className="space-y-2">
                {rows.map((row, index) => (
                  <li
                    key={row.id}
                    className="rounded-xl border border-black/[0.06] p-3 dark:border-white/10"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-medium text-foreground" title={row.name}>
                          {index + 1}. {row.name}
                        </div>
                        <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                          <span>{formatBytes(row.size)}</span>
                          <UploadBadge status={row.status} />
                        </div>
                        {row.status === "error" && row.error ? (
                          <div className="mt-1 break-words text-xs text-destructive">{row.error}</div>
                        ) : null}
                      </div>

                      <div className="flex items-end gap-1">
                        <div className="w-[5.25rem] shrink-0">
                          <Label
                            htmlFor={`plate-${row.id}`}
                            className="mb-1 block text-xs font-normal text-muted-foreground"
                          >
                            盘号
                          </Label>
                          <NativeSelect
                            id={`plate-${row.id}`}
                            value={String(row.plate)}
                            onChange={(e) => changePlate(row.id, e.target.value)}
                            disabled={row.status === "uploading"}
                            aria-label={`${row.name} 使用第几盘`}
                          >
                            {PLATE_NUMBERS.map((n) => (
                              <option key={n} value={String(n)}>
                                第 {n} 盘
                              </option>
                            ))}
                          </NativeSelect>
                        </div>
                        <Button
                          type="button"
                          variant="outline"
                          size="icon"
                          onClick={() => moveRow(row.id, -1)}
                          disabled={index === 0}
                          aria-label={`上移 ${row.name}`}
                        >
                          <span aria-hidden="true">↑</span>
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          size="icon"
                          onClick={() => moveRow(row.id, 1)}
                          disabled={index === rows.length - 1}
                          aria-label={`下移 ${row.name}`}
                        >
                          <span aria-hidden="true">↓</span>
                        </Button>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          onClick={() => removeRow(row.id)}
                          aria-label={`移除 ${row.name}`}
                        >
                          <svg
                            xmlns="http://www.w3.org/2000/svg"
                            width="16"
                            height="16"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            aria-hidden="true"
                          >
                            <path d="M18 6 6 18" />
                            <path d="m6 6 12 12" />
                          </svg>
                        </Button>
                      </div>
                    </div>

                    {row.status === "error" ? (
                      <div className="mt-2">
                        <Button type="button" variant="outline" size="sm" onClick={() => retryRow(row)}>
                          重新上传
                        </Button>
                      </div>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}

            <div className="flex flex-col gap-2 sm:flex-row">
              <Button
                type="button"
                className="w-full sm:w-auto"
                onClick={() => inputRef.current?.click()}
              >
                选择文件
              </Button>
              <Button
                type="button"
                variant="outline"
                className="w-full sm:w-auto"
                onClick={() => setRows([])}
                disabled={rows.length === 0}
              >
                清空列表
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* 右列：统计 + 配置 + 操作 + 结果 */}
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <div className="flex items-start justify-between gap-2">
                <div>
                  <CardTitle className="text-base">2. 统计</CardTitle>
                  <CardDescription>按已就绪的文件自动统计，变更盘号后会重新计算。</CardDescription>
                </div>
                {analyzing ? <Badge variant="info">统计中…</Badge> : null}
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {!analysis && !analyzing ? (
                <div className="rounded-xl border border-dashed p-6 text-center text-sm text-muted-foreground">
                  {items.length === 0
                    ? "上传文件后自动显示总盘数、总时长与耗材用量。"
                    : "暂无统计结果。"}
                </div>
              ) : null}

              {totals ? (
                <div className="grid grid-cols-2 gap-3">
                  <Metric label="总盘数" value={totals.plates ?? items.length} hint="即将合入的盘数" />
                  <Metric
                    label="总时长"
                    value={formatDuration(totals.time_s)}
                    hint={`${Math.round(Number(totals.time_s) || 0)} 秒（切片预估）`}
                  />
                  <Metric
                    label="总耗材"
                    value={`${fmtGrams(totals.weight_g)} g`}
                    hint="全部盘合计克数"
                  />
                  <Metric label="预计换盘" value={`${swapCount} 次`} hint="盘数 - 1" />
                </div>
              ) : null}

              {filaments.length > 0 ? (
                <div>
                  <div className="mb-2 text-sm font-medium text-foreground">全局槽位</div>
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[26rem] text-sm">
                      <thead>
                        <tr className="border-b border-black/[0.06] text-left text-xs text-muted-foreground dark:border-white/10">
                          <th className="py-2 pr-2 font-medium">槽位</th>
                          <th className="py-2 pr-2 font-medium">颜色</th>
                          <th className="py-2 pr-2 font-medium">材质</th>
                          <th className="py-2 pr-2 text-right font-medium">总用量</th>
                          <th className="py-2 font-medium">来自</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filaments.map((f) => (
                          <tr
                            key={`${f.slot}-${f.type}-${f.color}`}
                            className="border-b border-black/[0.06] last:border-0 dark:border-white/10"
                          >
                            <td className="py-2 pr-2 font-mono text-xs text-muted-foreground">S{f.slot}</td>
                            <td className="py-2 pr-2">
                              <ColorBlock colorHex={f.color} colorName={f.type || "耗材"} size={18} />
                            </td>
                            <td className="py-2 pr-2 text-foreground">{f.type || "-"}</td>
                            <td className="py-2 pr-2 text-right text-foreground">{fmtGrams(f.total_used_g)} g</td>
                            <td className="py-2 text-xs text-muted-foreground">{fmtPlateList(f.plates)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : null}

              {plates.length > 0 ? (
                <div>
                  <div className="mb-2 text-sm font-medium text-foreground">各盘明细</div>
                  <ul className="space-y-2">
                    {plates.map((p) => (
                      <li
                        key={p.index}
                        className="rounded-xl border border-black/[0.06] p-3 dark:border-white/10"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className="text-sm font-medium text-foreground">第 {p.index} 盘</span>
                          <span className="text-xs text-muted-foreground">
                            {p.client_version ? `切片器 ${p.client_version}` : "切片器版本未知"}
                          </span>
                        </div>
                        <div className="mt-1 text-xs text-muted-foreground">
                          预估 {p.prediction_s == null ? "-" : formatDuration(p.prediction_s)} · 耗材{" "}
                          {fmtGrams(p.weight_g)} g ·{" "}
                          {Array.isArray(p.filaments) ? p.filaments.length : 0} 个槽位
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}

              {analyzeWarnings.length > 0 ? (
                <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-sm font-medium text-destructive">
                      注意（{analyzeWarnings.length} 条）
                    </div>
                    {analyzeWarnings.length > 3 ? (
                      <Button
                        type="button"
                        variant="link"
                        size="sm"
                        onClick={() => setWarningsDialog(analyzeWarnings)}
                      >
                        查看全部
                      </Button>
                    ) : null}
                  </div>
                  <ul className="mt-2 space-y-1 text-xs text-destructive">
                    {analyzeWarnings.slice(0, 3).map((w, i) => (
                      <li key={`${w.code || "warn"}-${i}`} className="break-words">
                        [{w.code || "warning"}] {w.message}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <div className="flex items-start justify-between gap-2">
                <div>
                  <CardTitle className="text-base">3. 合盘配置</CardTitle>
                  <CardDescription>默认值面向 A1 + 第二代换盘套件，改动前建议先在实机小件验证。</CardDescription>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => setConfigOpen((v) => !v)}
                  aria-expanded={configOpen}
                >
                  {configOpen ? "收起" : "展开"}
                </Button>
              </div>
            </CardHeader>
            {configOpen ? (
              <CardContent className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="grid gap-2 sm:col-span-2">
                  <Label htmlFor="preset">换盘码预设</Label>
                  <NativeSelect
                    id="preset"
                    value={presetId}
                    onChange={(e) => setPresetId(e.target.value)}
                    disabled={presetsLoading || presets.length === 0}
                  >
                    {presetsLoading ? <option value="">加载中…</option> : null}
                    {!presetsLoading && presets.length === 0 ? (
                      <option value={DEFAULT_PRESET}>默认预设（接口不可用）</option>
                    ) : null}
                    {presets.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </NativeSelect>
                  <div className="text-xs text-muted-foreground">
                    {activePreset
                      ? `机型 ${activePreset.machine || "-"} · 推盘方式 ${activePreset.approach_mode || "-"} · Y 行程 ${
                          activePreset.y_limit ?? "-"
                        } mm`
                      : "预设详情不可用，将使用后端默认参数。"}
                  </div>
                  <p className="text-xs leading-relaxed text-[#0071e3] dark:text-[#0a84ff]">
                    这里调的是<strong>换料机械动作</strong>（推盘力度、Y 行程、停留时间），与打印速度无关。
                    <br />
                    打印速度分两层：<strong>切片参数</strong>决定基准速度（每条 G1 的 F 值），打印机上的
                    <strong>1–4 档</strong>是运行时倍率（M220），随时可改、不写回 G-code。
                  </p>
                  <div className="flex flex-wrap items-center gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => setShowAdvanced((v) => !v)}
                    >
                      {showAdvanced ? "收起参数" : "单独调整参数"}
                    </Button>
                    {Object.keys(swapOverrides).length > 0 ? (
                      <span className="text-xs text-muted-foreground">
                        已修改 {Object.keys(swapOverrides).length} 项
                      </span>
                    ) : null}
                  </div>
                  {showAdvanced ? (
                    <MergeAdvancedParams
                      presetId={presetId || DEFAULT_PRESET}
                      overrides={swapOverrides}
                      onChange={setSwapOverrides}
                    />
                  ) : null}
                </div>

                <div className="grid gap-2">
                  <Label htmlFor="policy">首尾处理策略</Label>
                  <NativeSelect id="policy" value={policy} onChange={(e) => setPolicy(e.target.value)}>
                    {POLICY_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </NativeSelect>
                  <div className="rounded-lg bg-[#f5f5f7] px-2.5 py-2 text-xs leading-relaxed text-muted-foreground dark:bg-white/5">
                    {POLICY_OPTIONS.find((o) => o.value === policy)?.hint ||
                      "中间盘的 start/end G-code 保留强度。"}
                  </div>
                </div>

                <div className="grid gap-2">
                  <Label htmlFor="plate-display">盘号显示</Label>
                  <NativeSelect
                    id="plate-display"
                    value={plateDisplay}
                    onChange={(e) => setPlateDisplay(e.target.value)}
                  >
                    {PLATE_DISPLAY_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </NativeSelect>
                  <div className="text-xs text-muted-foreground">在打印机屏幕上提示当前是第几盘。</div>
                </div>

                <div className={`grid gap-2 ${preSound === "custom" ? "sm:col-span-2" : ""}`}>
                  <Label htmlFor="pre-sound">换盘前音效</Label>
                  <NativeSelect id="pre-sound" value={preSound} onChange={(e) => setPreSound(e.target.value)}>
                    {AUDIO_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </NativeSelect>
                  {preSound === "custom" ? (
                    <div className="space-y-2">
                      <div className="flex items-center gap-2">
                        <Button
                          type="button"
                          size="sm"
                          variant={preSoundMode === "visual" ? "default" : "outline"}
                          onClick={() => setPreSoundMode("visual")}
                        >
                          音符编辑
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          variant={preSoundMode === "raw" ? "default" : "outline"}
                          onClick={() => setPreSoundMode("raw")}
                        >
                          原始乐谱
                        </Button>
                      </div>
                      {preSoundMode === "visual" ? (
                        <MergeSoundEditor value={preCustomNotes} onChange={setPreCustomNotes} />
                      ) : (
                        <>
                          <textarea
                            className="min-h-[84px] w-full resize-y rounded-lg border border-black/[0.1] bg-white px-3 py-2 font-mono text-xs leading-relaxed text-foreground outline-none focus-visible:border-[#0071e3] dark:border-white/15 dark:bg-white/5"
                            value={preCustomNotes}
                            onChange={(e) => setPreCustomNotes(e.target.value)}
                            placeholder={CUSTOM_SOUND_PLACEHOLDER}
                            spellCheck={false}
                          />
                          <p className="text-xs text-muted-foreground">
                            每行一条 <code>M1006</code>（三音一组），只允许 M1006 指令；留空会报错。
                          </p>
                        </>
                      )}
                    </div>
                  ) : null}
                </div>

                <div className={`grid gap-2 ${postSound === "custom" ? "sm:col-span-2" : ""}`}>
                  <Label htmlFor="post-sound">换盘后音效</Label>
                  <NativeSelect id="post-sound" value={postSound} onChange={(e) => setPostSound(e.target.value)}>
                    {AUDIO_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </NativeSelect>
                  {postSound === "custom" ? (
                    <div className="space-y-2">
                      <div className="flex items-center gap-2">
                        <Button
                          type="button"
                          size="sm"
                          variant={postSoundMode === "visual" ? "default" : "outline"}
                          onClick={() => setPostSoundMode("visual")}
                        >
                          音符编辑
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          variant={postSoundMode === "raw" ? "default" : "outline"}
                          onClick={() => setPostSoundMode("raw")}
                        >
                          原始乐谱
                        </Button>
                      </div>
                      {postSoundMode === "visual" ? (
                        <MergeSoundEditor value={postCustomNotes} onChange={setPostCustomNotes} />
                      ) : (
                        <>
                          <textarea
                            className="min-h-[84px] w-full resize-y rounded-lg border border-black/[0.1] bg-white px-3 py-2 font-mono text-xs leading-relaxed text-foreground outline-none focus-visible:border-[#0071e3] dark:border-white/15 dark:bg-white/5"
                            value={postCustomNotes}
                            onChange={(e) => setPostCustomNotes(e.target.value)}
                            placeholder={CUSTOM_SOUND_PLACEHOLDER}
                            spellCheck={false}
                          />
                          <p className="text-xs text-muted-foreground">
                            每行一条 <code>M1006</code>（三音一组），只允许 M1006 指令；留空会报错。
                          </p>
                        </>
                      )}
                    </div>
                  ) : null}
                </div>

                <div className="grid gap-2">
                  <Label htmlFor="cooldown">热床冷却温度（℃，可选）</Label>
                  <Input
                    id="cooldown"
                    type="number"
                    min="0"
                    max="120"
                    step="1"
                    inputMode="numeric"
                    value={cooldown}
                    onChange={(e) => setCooldown(e.target.value)}
                    placeholder="留空不降温"
                  />
                  <div className="text-xs text-muted-foreground">插入换盘码前把热床降到该温度，避免烫手。</div>
                </div>

                <div className="grid gap-2">
                  <Label htmlFor="wait-s">换盘后等待秒数</Label>
                  <Input
                    id="wait-s"
                    type="number"
                    min="0"
                    step="1"
                    inputMode="numeric"
                    value={waitS}
                    onChange={(e) => setWaitS(e.target.value)}
                  />
                  <div className="text-xs text-muted-foreground">0 表示不等待。</div>
                </div>

                <div className="grid gap-2 sm:col-span-2">
                  <Label htmlFor="output-name">输出文件名（可选）</Label>
                  <Input
                    id="output-name"
                    value={outputName}
                    onChange={(e) => setOutputName(e.target.value)}
                    placeholder="例如 merged.gcode.3mf，留空由后端自动命名"
                  />
                  <div className="text-xs text-muted-foreground">
                    未填后缀会自动补 .3mf；产物保存在服务端，生成后可下载或到产物库查看。
                  </div>
                </div>
              </CardContent>
            ) : null}
          </Card>

          <Card>
            <CardContent className="space-y-3 p-4 sm:p-6">
              <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
                <span>
                  将合入 <span className="font-medium text-foreground">{items.length}</span> 盘，预计换盘{" "}
                  <span className="font-medium text-foreground">{swapCount}</span> 次
                </span>
                {uploadingCount > 0 ? <Badge variant="warning">{uploadingCount} 个上传中</Badge> : null}
                {failedCount > 0 ? <Badge variant="destructive">{failedCount} 个失败</Badge> : null}
              </div>
              <Button
                type="button"
                className="w-full"
                onClick={handleMerge}
                disabled={merging || items.length === 0 || uploadingCount > 0}
              >
                {merging ? "生成中…" : "生成合盘文件"}
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">换盘测试文件（不加热 · 不耗料）</CardTitle>
              <CardDescription>
                生成一个纯换盘动作的测试文件：只执行换盘机械动作，不升温、不出料、无打印轨迹。
                每次换盘后静默等待，再播放滴滴滴提示音；屏幕显示盘号与进度。
                首次使用某档预设前，建议先空机跑一遍确认动作安全。
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="test-cycles">换盘次数（1~50）</Label>
                  <Input
                    id="test-cycles"
                    type="number"
                    min={1}
                    max={50}
                    value={testCycles}
                    onChange={(e) => setTestCycles(e.target.value)}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="test-wait">换盘后等待秒数</Label>
                  <Input
                    id="test-wait"
                    type="number"
                    min={0}
                    max={300}
                    value={testWait}
                    onChange={(e) => setTestWait(e.target.value)}
                  />
                </div>
              </div>
              <div className="text-xs text-muted-foreground">
                使用上方「合盘配置」里选中的换盘码预设（当前：
                {presets.find((p) => p.id === presetId)?.name || "默认保守档"}）。
              </div>
              <Button
                type="button"
                variant="secondary"
                className="w-full"
                onClick={handleMakeTestFile}
                disabled={testing}
              >
                {testing ? "生成中…" : "生成换盘测试文件"}
              </Button>

              {testResult ? (
                <div className="rounded-xl border border-[#0071e3]/30 bg-[#0071e3]/5 p-3 dark:border-[#0a84ff]/30 dark:bg-[#0a84ff]/5">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="min-w-0">
                      <div className="break-all font-mono text-xs text-foreground">{testResult.output}</div>
                      <div className="text-xs text-muted-foreground">
                        {testResult.cycles} 次换盘{testResult.size ? ` · ${formatBytes(testResult.size)}` : ""}
                      </div>
                    </div>
                    <div className="flex shrink-0 gap-2">
                      <Button type="button" size="sm" onClick={() => downloadOutput(testResult.output)}>
                        下载
                      </Button>
                      <Link href="/production/gcodes">
                        <Button type="button" size="sm" variant="ghost">
                          去产物库
                        </Button>
                      </Link>
                    </div>
                  </div>
                </div>
              ) : null}
            </CardContent>
          </Card>

          {result ? (
            <Card className="border-[#0071e3]/30 dark:border-[#0a84ff]/30">
              <CardHeader>
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <CardTitle className="text-base">合盘完成</CardTitle>
                    <CardDescription className="break-all font-mono text-xs">{result.output}</CardDescription>
                  </div>
                  <Badge variant="success">{result.plate_count} 盘</Badge>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <Metric label="文件大小" value={formatBytes(result.gcode_bytes)} />
                  <Metric
                    label="总时长"
                    value={result.total_time_s == null ? "-" : formatDuration(result.total_time_s)}
                  />
                  <Metric
                    label="总耗材"
                    value={result.total_weight_g == null ? "-" : `${fmtGrams(result.total_weight_g)} g`}
                  />
                  <Metric label="盘数" value={result.plate_count ?? "-"} />
                </div>

                <div className="rounded-xl bg-[#f5f5f7] p-3 dark:bg-[#2c2c2e]">
                  <div className="text-xs text-muted-foreground">MD5</div>
                  <div className="mt-1 break-all font-mono text-xs text-foreground">{result.md5 || "-"}</div>
                </div>

                {resultWarnings.length > 0 ? (
                  <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-3">
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-sm font-medium text-destructive">
                        注意（{resultWarnings.length} 条）
                      </div>
                      {resultWarnings.length > 3 ? (
                        <Button
                          type="button"
                          variant="link"
                          size="sm"
                          onClick={() => setWarningsDialog(resultWarnings)}
                        >
                          查看全部
                        </Button>
                      ) : null}
                    </div>
                    <ul className="mt-2 space-y-1 text-xs text-destructive">
                      {resultWarnings.slice(0, 3).map((w, i) => (
                        <li key={`${w.code || "warn"}-${i}`} className="break-words">
                          [{w.code || "warning"}] {w.message}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                <div className="grid gap-2 sm:grid-cols-2">
                  <Button type="button" onClick={() => downloadOutput(result.output)}>
                    下载
                  </Button>
                  <Button type="button" variant="outline" asChild>
                    <Link href="/production/gcodes">去产物库</Link>
                  </Button>
                </div>
              </CardContent>
            </Card>
          ) : null}
        </div>
      </div>

      <Dialog
        open={Boolean(warningsDialog)}
        onOpenChange={(v) => {
          if (!v) setWarningsDialog(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>全部提示</DialogTitle>
            <DialogDescription>这些提示不阻断合盘，但建议打印前逐条确认。</DialogDescription>
          </DialogHeader>
          <ul className="max-h-[50dvh] space-y-2 overflow-y-auto text-sm">
            {(warningsDialog || []).map((w, i) => (
              <li key={`${w.code || "warn"}-${i}`} className="rounded-xl border border-black/[0.06] p-3 dark:border-white/10">
                <div className="font-mono text-xs text-muted-foreground">{w.code || "warning"}</div>
                <div className="mt-1 break-words text-foreground">{w.message}</div>
              </li>
            ))}
          </ul>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setWarningsDialog(null)}>
              关闭
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
