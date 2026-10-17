"use client";

import Link from "next/link";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Badge } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../../components/ui/card";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { NativeSelect } from "../../../components/ui/native-select";
import {
  formatBytes,
  formatDuration,
  listPresets,
  makeTestFile,
  renderPreset,
  upload3mf
} from "../../../lib/plate-merger-api";

// ---------------------------------------------------------------------------
// 常量：取值一律来自 backend（app/plate_merger/presets.py + models.py）
// ---------------------------------------------------------------------------

/** ApproachMode 枚举（models.py）= force | open */
const APPROACH_MODE_LABELS = {
  force: "力控推盘（G380）",
  open: "开环推盘（G1）"
};

const APPROACH_MODE_HINTS = {
  force: "遇阻提前停止，最稳，节拍略慢",
  open: "固定坐标直推，最快，依赖机械一致性"
};

/** 三档之间仅停留时间不同（presets.py 里用 dataclasses.replace 覆盖） */
const DWELL_BY_PRESET = {
  "builtin:a1-conservative": { afterZ: "2000 ms", beforePull: "1000 ms", shake: "500 ms" },
  "builtin:a1-balanced": { afterZ: "1000 ms", beforePull: "500 ms", shake: "300 ms" },
  "builtin:a1-fast": { afterZ: "0（不停留）", beforePull: "0（不停留）", shake: "300 ms" }
};

/** 代码块最多渲染这么多行，避免超长字符串拖慢首帧（复制仍复制全文） */
const PREVIEW_LINE_LIMIT = 500;
/** 后端 TestFileIn.cycles 的约束：ge=1, le=50 */
const CYCLES_MIN = 1;
const CYCLES_MAX = 50;

function approachModeLabel(mode) {
  if (!mode) return "未知";
  return APPROACH_MODE_LABELS[mode] || String(mode);
}

/**
 * 只做一次 split 生成预览文本，不做逐行再加工。
 * 全文仍保留在 state 中，供「复制」使用。
 */
function makeGcodePreview(text) {
  if (!text) return { preview: "", totalLines: 0, truncated: false };
  const lines = text.split("\n");
  const totalLines = text.endsWith("\n") ? lines.length - 1 : lines.length;
  if (totalLines <= PREVIEW_LINE_LIMIT) return { preview: text, totalLines, truncated: false };
  return { preview: lines.slice(0, PREVIEW_LINE_LIMIT).join("\n"), totalLines, truncated: true };
}

/** 局域网 http 下 clipboard API 不可用，退回到临时 textarea */
function fallbackCopy(text) {
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.top = "-1000px";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  } catch {
    return false;
  }
}

function errMessage(err) {
  const issues = err?.detail?.issues;
  if (Array.isArray(issues) && issues.length > 0) return issues.join("；");
  if (typeof issues === "string" && issues) return issues;
  return String(err?.message || err);
}

function ParamTable({ groups }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-black/[0.06] dark:border-white/10">
      <table className="w-full min-w-[680px] border-collapse text-sm">
        <thead>
          <tr className="bg-[#f5f5f7] text-left text-xs font-medium text-muted-foreground dark:bg-[#2c2c2e]">
            <th scope="col" className="px-3 py-2">
              参数
            </th>
            <th scope="col" className="px-3 py-2">
              值
            </th>
            <th scope="col" className="px-3 py-2">
              说明
            </th>
          </tr>
        </thead>
        <tbody>
          {groups.map((group) => (
            <Fragment key={group.title}>
              <tr className="border-t border-black/10 dark:border-white/10">
                <th
                  scope="colgroup"
                  colSpan={3}
                  className="bg-[#f5f5f7]/60 px-3 py-1.5 text-left text-xs font-semibold text-foreground dark:bg-[#2c2c2e]/60"
                >
                  {group.title}
                </th>
              </tr>
              {group.rows.map((row) => (
                <tr key={row.name} className="border-t border-black/[0.06] align-top dark:border-white/[0.08]">
                  <td className="px-3 py-2">
                    <div className="font-mono text-xs text-foreground">{row.name}</div>
                    <div className="mt-0.5 text-xs text-muted-foreground">{row.label}</div>
                  </td>
                  <td className="px-3 py-2 font-mono text-xs text-foreground">{row.value}</td>
                  <td className="px-3 py-2 text-xs leading-relaxed text-muted-foreground">{row.note}</td>
                </tr>
              ))}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Page() {
  const [presets, setPresets] = useState([]);
  const [presetsLoading, setPresetsLoading] = useState(true);
  const [presetsError, setPresetsError] = useState("");
  const [presetsNonce, setPresetsNonce] = useState(0);
  const [selectedId, setSelectedId] = useState("");

  const [renderData, setRenderData] = useState(null);
  const [renderLoading, setRenderLoading] = useState(false);
  const [renderError, setRenderError] = useState("");
  const [renderNonce, setRenderNonce] = useState(0);
  const [copied, setCopied] = useState(false);

  const [uploaded, setUploaded] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [cycles, setCycles] = useState("3");
  const [generating, setGenerating] = useState(false);
  const [testResult, setTestResult] = useState(null);

  const fileInputRef = useRef(null);

  // ------------------------------------------------------------ 预设列表
  useEffect(() => {
    let cancelled = false;
    setPresetsLoading(true);
    setPresetsError("");
    (async () => {
      try {
        const data = await listPresets();
        if (cancelled) return;
        const list = Array.isArray(data) ? data : [];
        setPresets(list);
        setSelectedId((prev) =>
          prev && list.some((item) => item.id === prev) ? prev : list[0]?.id || ""
        );
      } catch (e) {
        if (cancelled) return;
        setPresetsError(errMessage(e));
      } finally {
        if (!cancelled) setPresetsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [presetsNonce]);

  const selectedPreset = useMemo(
    () => presets.find((item) => item.id === selectedId) || null,
    [presets, selectedId]
  );

  // ------------------------------------------------------------ 渲染预览
  useEffect(() => {
    if (!selectedId) {
      setRenderData(null);
      setRenderError("");
      return undefined;
    }
    let cancelled = false;
    setRenderLoading(true);
    setRenderError("");
    setRenderData(null);
    setCopied(false);
    (async () => {
      try {
        const data = await renderPreset(selectedId);
        if (!cancelled) setRenderData(data);
      } catch (e) {
        if (cancelled) return;
        const msg = errMessage(e);
        setRenderError(msg);
        toast.error(`渲染失败：${msg}`);
      } finally {
        if (!cancelled) setRenderLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedId, renderNonce]);

  const gcode = typeof renderData?.gcode === "string" ? renderData.gcode : "";
  const preview = useMemo(() => makeGcodePreview(gcode), [gcode]);
  const durationText = renderData ? formatDuration(renderData.duration_s) : null;

  async function copyGcode() {
    if (!gcode) return;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(gcode);
      } else if (!fallbackCopy(gcode)) {
        throw new Error("当前浏览器不允许写入剪贴板");
      }
      setCopied(true);
      toast.success(`已复制 G-code（共 ${preview.totalLines} 行）`);
      setTimeout(() => setCopied(false), 2000);
    } catch (e) {
      toast.error(`复制失败：${String(e?.message || e)}`);
    }
  }

  // ------------------------------------------------------------ 参数说明表
  const paramGroups = useMemo(() => {
    const preset = selectedPreset;
    if (!preset) return [];
    const mode = preset.approach_mode;
    const isForce = mode !== "open";
    const yLimit = Number(preset.y_limit) || 0;
    const dwell = DWELL_BY_PRESET[preset.id] || null;
    const dwellText = (key) => (dwell ? dwell[key] : "见后端预设");

    return [
      {
        title: "推盘与行程",
        rows: [
          {
            name: "approach_mode",
            label: "换盘方式",
            value: approachModeLabel(mode),
            note: `推热床到后限位的方式。${APPROACH_MODE_HINTS[mode] || ""}`
          },
          {
            name: "y_limit",
            label: "Y 轴行程上限",
            value: yLimit ? `${yLimit} mm` : "—",
            note: "所有绝对 Y 坐标都不得超过它；A1 为 264，A1 mini 为 180。换机型需整体替换预设坐标。"
          },
          {
            name: "home_y_before",
            label: "推盘前是否归零",
            value: isForce ? "是（G28 Y 后慢速贴近）" : "否（跳过归零，直接进给）",
            note: "归零费时但保证起点确定；快速档跳过归零，靠机械一致性换节拍。"
          },
          {
            name: "approach_target",
            label: "推盘目标位置",
            value: isForce
              ? `${yLimit || "—"} mm（力控顶到后限位）`
              : "260 mm（开环，留 4 mm 余量）",
            note: "力控档可以顶到极限；开环档必须留余量，否则会与后挡件硬碰。"
          },
          {
            name: "approach_feedrate",
            label: "开环推盘进给",
            value: isForce ? "— （力控固定 F2000）" : "3000 mm/min",
            note: "仅开环模式使用；力控模式的进给由 _FEED_FORCE 固定。"
          }
        ]
      },
      {
        title: "Z 力控升降（把热床对齐到托盘高度）",
        rows: [
          {
            name: "z_probe_down",
            label: "首次下压量",
            value: "-25 mm",
            note: "负值表示热床上升，写反会反向撞机（后端校验强制为负）。"
          },
          {
            name: "z_probe_up",
            label: "每次抬升量",
            value: "+85 mm",
            note: "必须为正；与回落量共同构成「抬升 → 回落」循环。"
          },
          {
            name: "z_probe_cycles",
            label: "升降循环次数",
            value: "4 次",
            note: "次数越多越稳、越慢；必须 >= 1。"
          },
          {
            name: "z_probe_mid_down",
            label: "循环中的回落量",
            value: "-20 mm",
            note: "绝对值小于首次下压量，逐次确认托盘接触面。"
          },
          {
            name: "z_settle",
            label: "收尾微调量",
            value: "-5 mm",
            note: "力控结束后的最后一点贴合，必须为负。"
          },
          {
            name: "z_lift_before_eject",
            label: "卸盘前抬升量",
            value: "-55 mm",
            note: "卸盘前先把热床升到盘架高度（与原文件 G1 Z-55 一致）。"
          },
          {
            name: "force_level_probe / force_level_push",
            label: "力控档位",
            value: "S3 / S2",
            note: "G380 的力控档位会被原样写入 G-code，必须是「S + 数字」，防止指令注入。"
          }
        ]
      },
      {
        title: "抖动脱盘",
        rows: [
          {
            name: "shake_offsets",
            label: "抖动越位序列",
            value: "1.0 → 3.5 mm（6 档）",
            note: "低速小幅越位、由轻到重递增（后端强制递增），把盘推到临界后靠惯性脱开。"
          },
          {
            name: "shake_feedrate",
            label: "抖动越位进给",
            value: "100 mm/min",
            note: "极低进给，避免硬推撞坏盘夹。"
          },
          {
            name: "retract_feedrates",
            label: "回位进给序列",
            value: "20000 ×4 → 10000 → 5000",
            note: "越位越大回拉越慢，与越位序列一一对应，长度不一致后端直接报错。"
          },
          {
            name: "shake_dwell_ms",
            label: "每组抖动停留",
            value: dwellText("shake"),
            note: "最后一组不停留，紧接着进入下一段动作。"
          }
        ]
      },
      {
        title: "越位与停留",
        rows: [
          {
            name: "eject_offset",
            label: "卸盘越位量",
            value: "-1 mm",
            note: "硬约束：必须 <= -1，否则前端退盘机构不会被触发。"
          },
          {
            name: "pull_offset",
            label: "拉盘越位量",
            value: "-2 mm",
            note: "同样必须 <= -1；不够就勾不住拉盘钩。"
          },
          {
            name: "dwell_after_z_ms",
            label: "Z 后停留",
            value: dwellText("afterZ"),
            note: "Z 力控结束后的停留，给机构反应时间；均衡/快速档会压缩或去掉。"
          },
          {
            name: "dwell_before_pull_ms",
            label: "拉盘前停留",
            value: dwellText("beforePull"),
            note: "第二次推盘前等待，让拉盘钩到位。"
          }
        ]
      },
      {
        title: "进给速度常量（swapcode.py）",
        rows: [
          {
            name: "_FEED_SLOW",
            label: "慢速",
            value: "1200 mm/min",
            note: "初始贴近、所有 Z 动作、卸盘越位都走这个速度。"
          },
          {
            name: "_FEED_FORCE",
            label: "力控推盘",
            value: "2000 mm/min",
            note: "G380 力控移动的进给，实际位移取决于阻力。"
          },
          {
            name: "_FEED_FAST",
            label: "快速",
            value: "4000 mm/min",
            note: "卸盘前的中位停靠 y_park 等空行程。"
          },
          {
            name: "_HOME_SECONDS",
            label: "归零估算时长",
            value: "3 s / 次",
            note: "renderPreset 返回的时长按名义位移估算，用于档位横向比较与排产预估，不是精确墙钟时间。"
          }
        ]
      }
    ];
  }, [selectedPreset]);

  // ------------------------------------------------------------ 测试文件
  async function onPickFile(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (!/\.3mf$/i.test(file.name)) {
      toast.error("请选择 .3mf 切片文件作为模板");
      return;
    }
    setUploading(true);
    try {
      const res = await upload3mf(file);
      setUploaded(res);
      setTestResult(null);
      toast.success(`模板已上传：${res?.name || file.name}`);
    } catch (e) {
      toast.error(`上传失败：${errMessage(e)}`);
    } finally {
      setUploading(false);
    }
  }

  const cyclesNumber = Number(cycles);
  const cyclesValid =
    Number.isInteger(cyclesNumber) && cyclesNumber >= CYCLES_MIN && cyclesNumber <= CYCLES_MAX;

  const estimateHint = useMemo(() => {
    if (!renderData || !cyclesValid) return null;
    const perCycle = Number(renderData.duration_s) || 0;
    return {
      perCycle: formatDuration(perCycle),
      total: formatDuration(perCycle * cyclesNumber)
    };
  }, [renderData, cyclesValid, cyclesNumber]);

  async function generateTestFile() {
    if (!uploaded?.path) {
      toast.error("请先上传一个模板 3MF 文件");
      return;
    }
    if (!selectedPreset?.id) {
      toast.error("请先选择一个换盘预设");
      return;
    }
    if (!cyclesValid) {
      toast.error(`换盘次数需为 ${CYCLES_MIN}~${CYCLES_MAX} 的整数`);
      return;
    }
    setGenerating(true);
    try {
      const res = await makeTestFile(uploaded.path, cyclesNumber, selectedPreset.id);
      setTestResult(res);
      toast.success(`测试文件已生成：${res?.output || ""}`);
    } catch (e) {
      toast.error(`生成失败：${errMessage(e)}`);
    } finally {
      setGenerating(false);
    }
  }

  // ------------------------------------------------------------ 渲染
  return (
    <div className="space-y-6">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">换盘码管理</h1>
          <Badge variant="secondary">只读</Badge>
        </div>
        <p className="mt-1 text-sm text-muted-foreground">
          换盘码是合盘功能的核心配置：每次换盘时机械臂要完成的归零、力控对齐、推盘、卸旧盘、拉新盘全部由它驱动。
          这里可以查看三档预设、实时渲染 G-code 与时长估算，并生成空跑测试文件。
        </p>
      </div>

      {/* 安全提示：醒目但不惊悚 */}
      <Card className="border border-amber-500/30 bg-amber-50/70 dark:border-amber-400/25 dark:bg-amber-400/10">
        <CardHeader className="pb-2">
          <div className="flex items-start gap-3">
            <span
              aria-hidden="true"
              className="mt-0.5 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-amber-500/15 text-amber-600 dark:text-amber-400"
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="m10.29 3.86-8.18 14a2 2 0 0 0 1.71 3h16.36a2 2 0 0 0 1.71-3l-8.18-14a2 2 0 0 0-3.42 0Z" />
                <path d="M12 9v4" />
                <path d="M12 17h.01" />
              </svg>
            </span>
            <div className="min-w-0">
              <CardTitle className="text-base">首次使用某档预设，先空机跑一遍测试文件</CardTitle>
              <CardDescription className="mt-1">
                换盘码会驱动热床做越位与力控挤压动作，参数与你的机型不匹配时可能撞件。建议先在空机上（不装打印件、不挂料）
                用下方「换盘测试文件」验证动作顺序与坐标，确认没有异响、没有碰撞，再投入正式合盘。
              </CardDescription>
            </div>
          </div>
        </CardHeader>
      </Card>

      {/* 预设列表 */}
      <section className="space-y-3">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">换盘预设</h2>
          <p className="text-sm text-muted-foreground">
            三档预设共用同一套动作顺序，只是可靠性 vs. 节拍的取舍不同。点击卡片切换，下方预览会同步刷新。
          </p>
        </div>

        {presetsLoading ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <Card key={i} className="h-32 animate-pulse bg-[#f5f5f7] dark:bg-[#2c2c2e]" />
            ))}
          </div>
        ) : presetsError ? (
          <Card>
            <CardContent className="space-y-3 p-4 sm:p-6">
              <div className="text-sm text-destructive">预设加载失败：{presetsError}</div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setPresetsNonce((n) => n + 1)}
                disabled={presetsLoading}
              >
                {presetsLoading ? "加载中…" : "重试"}
              </Button>
            </CardContent>
          </Card>
        ) : presets.length === 0 ? (
          <div className="py-6 text-center text-sm text-muted-foreground">后端未返回任何换盘预设。</div>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {presets.map((preset) => {
              const isActive = preset.id === selectedId;
              return (
                <button
                  key={preset.id}
                  type="button"
                  onClick={() => setSelectedId(preset.id)}
                  aria-pressed={isActive}
                  className="rounded-2xl text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0071e3] focus-visible:ring-offset-2 focus-visible:ring-offset-background dark:focus-visible:ring-[#0a84ff]"
                >
                  <Card
                    className={
                      "h-full border-2 transition-colors " +
                      (isActive
                        ? "border-[#0071e3] ring-2 ring-[#0071e3]/20 dark:border-[#0a84ff] dark:ring-[#0a84ff]/25"
                        : "border-transparent hover:border-black/10 dark:hover:border-white/15")
                    }
                  >
                    <CardHeader className="pb-3">
                      <div className="flex items-start justify-between gap-2">
                        <CardTitle className="text-base leading-snug">{preset.name}</CardTitle>
                        {isActive ? <Badge variant="info">已选中</Badge> : null}
                      </div>
                      <CardDescription className="font-mono text-xs">{preset.id}</CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-2 text-sm">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-muted-foreground">机型</span>
                        <span className="font-medium text-foreground">{preset.machine || "—"}</span>
                      </div>
                      <div className="flex items-start justify-between gap-2">
                        <span className="shrink-0 text-muted-foreground">换盘方式</span>
                        <span className="text-right font-medium text-foreground">
                          {approachModeLabel(preset.approach_mode)}
                        </span>
                      </div>
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-muted-foreground">Y 轴限位</span>
                        <span className="font-medium text-foreground">
                          {preset.y_limit === null || preset.y_limit === undefined
                            ? "—"
                            : `${preset.y_limit} mm`}
                        </span>
                      </div>
                    </CardContent>
                  </Card>
                </button>
              );
            })}
          </div>
        )}
      </section>

      {/* 渲染预览 */}
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <CardTitle>G-code 预览</CardTitle>
              <CardDescription className="mt-1">
                {selectedPreset
                  ? `当前预设：${selectedPreset.name}（${selectedPreset.machine}）`
                  : "选择上方任一预设后会自动渲染"}
              </CardDescription>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {durationText ? <Badge variant="secondary">单次换盘约 {durationText}</Badge> : null}
              {preview.totalLines > 0 ? <Badge variant="outline">{preview.totalLines} 行</Badge> : null}
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => setRenderNonce((n) => n + 1)}
                disabled={!selectedId || renderLoading}
              >
                {renderLoading ? "渲染中…" : "重新渲染"}
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={copyGcode}
                disabled={!gcode || renderLoading}
              >
                {copied ? "已复制" : "复制 G-code"}
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-2">
          {renderLoading ? (
            <div className="flex h-40 items-center justify-center rounded-xl bg-[#f5f5f7] text-sm text-muted-foreground dark:bg-[#2c2c2e]">
              正在渲染换盘码…
            </div>
          ) : renderError ? (
            <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
              渲染失败：{renderError}
            </div>
          ) : gcode ? (
            <>
              <pre
                tabIndex={0}
                role="region"
                aria-label="换盘 G-code 预览"
                className="max-h-[420px] overflow-auto rounded-xl bg-[#1c1c1e] p-3 font-mono text-xs leading-relaxed text-[#e8e8ed] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0a84ff]"
              >
                {preview.preview}
              </pre>
              {preview.truncated ? (
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <Badge variant="warning">已截断</Badge>
                  <span>
                    仅显示前 {PREVIEW_LINE_LIMIT} 行（共 {preview.totalLines} 行）；「复制 G-code」仍复制全文。
                  </span>
                </div>
              ) : null}
            </>
          ) : (
            <div className="py-8 text-center text-sm text-muted-foreground">暂无内容</div>
          )}
        </CardContent>
      </Card>

      {/* 参数说明表 */}
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-2">
            <CardTitle>参数说明</CardTitle>
            <Badge variant="outline">后端只读</Badge>
          </div>
          <CardDescription className="mt-1">
            「换盘方式」「Y 轴限位」由接口返回；其余为预设基准值（其余两档只覆盖停留时间与推盘方式）。
            <span className="font-medium text-foreground">修改参数需在 backend 预设中调整</span>
            （backend/app/plate_merger/presets.py、models.py），前端只做展示；最终以「G-code 预览」中的实际指令为准。
          </CardDescription>
        </CardHeader>
        <CardContent>
          {paramGroups.length > 0 ? (
            <ParamTable groups={paramGroups} />
          ) : (
            <div className="py-6 text-center text-sm text-muted-foreground">选择预设后显示参数值。</div>
          )}
        </CardContent>
      </Card>

      {/* 换盘测试文件 */}
      <Card>
        <CardHeader>
          <CardTitle>换盘测试文件</CardTitle>
          <CardDescription className="mt-1">
            生成的文件<strong className="text-foreground">不加热、不耗料</strong>
            ，只保留换盘码与最小开销，用于验证换盘动作与坐标是否安全，可直接上机空跑。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            {/* 上传模板 */}
            <div className="space-y-2">
              <Label htmlFor="swap-template-file">模板 3MF</Label>
              <input
                id="swap-template-file"
                ref={fileInputRef}
                type="file"
                accept=".3mf"
                className="sr-only"
                onChange={onPickFile}
                aria-label="选择模板 3MF 文件"
              />
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={uploading}
                >
                  {uploading ? "上传中…" : uploaded ? "重新选择" : "选择文件"}
                </Button>
                {uploaded ? (
                  <>
                    <Badge variant="success">已上传</Badge>
                    <span className="min-w-0 break-all text-xs text-muted-foreground">
                      {uploaded.name || "模板.3mf"}
                      {uploaded.size ? ` · ${formatBytes(uploaded.size)}` : ""}
                    </span>
                  </>
                ) : uploading ? (
                  <span className="text-xs text-muted-foreground">正在上传到服务端…</span>
                ) : (
                  <span className="text-xs text-muted-foreground">尚未上传模板（任意切片 3MF 均可）</span>
                )}
              </div>
            </div>

            {/* 次数 + 预设 */}
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="swap-cycles">换盘次数</Label>
                <Input
                  id="swap-cycles"
                  type="number"
                  inputMode="numeric"
                  min={CYCLES_MIN}
                  max={CYCLES_MAX}
                  step="1"
                  value={cycles}
                  onChange={(e) => setCycles(e.target.value)}
                  aria-describedby="swap-cycles-hint"
                />
                <div id="swap-cycles-hint" className="text-xs text-muted-foreground">
                  {CYCLES_MIN}~{CYCLES_MAX}，默认 3 次
                </div>
              </div>
              <div className="space-y-2">
                <Label htmlFor="swap-preset">使用预设</Label>
                <NativeSelect
                  id="swap-preset"
                  value={selectedId}
                  onChange={(e) => setSelectedId(e.target.value)}
                  disabled={presets.length === 0}
                >
                  {presets.length === 0 ? <option value="">暂无预设</option> : null}
                  {presets.map((preset) => (
                    <option key={preset.id} value={preset.id}>
                      {preset.name}
                    </option>
                  ))}
                </NativeSelect>
                <div className="text-xs text-muted-foreground">与上方选中的预设共用</div>
              </div>
            </div>
          </div>

          <div className="rounded-xl bg-[#f5f5f7] p-3 text-sm dark:bg-[#2c2c2e]">
            <div className="text-muted-foreground">
              生成时以模板的开场段为骨架（加热目标置 0、删除等待升温），只按所选预设把换盘码重复{" "}
              {cyclesValid ? cyclesNumber : "—"} 次，不含任何走刀路径，产物写入服务端产物目录。
              {estimateHint ? (
                <>
                  {" "}
                  按当前预设估算：单次约 {estimateHint.perCycle}，合计约{" "}
                  <span className="font-medium text-foreground">{estimateHint.total}</span>
                  （名义位移估算，不含机械等待）。
                </>
              ) : null}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Button
              type="button"
              onClick={generateTestFile}
              disabled={generating || uploading || !uploaded?.path || !selectedPreset || !cyclesValid}
            >
              {generating ? "生成中…" : "生成测试文件"}
            </Button>
            {!uploaded?.path ? (
              <span className="text-xs text-muted-foreground">先上传模板 3MF 才能生成</span>
            ) : null}
          </div>

          {testResult ? (
            <div className="space-y-2 rounded-xl border border-black/[0.06] p-3 text-sm dark:border-white/10">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="success">已写入产物库</Badge>
                <span className="break-all font-mono text-xs text-foreground">{testResult.output}</span>
                {testResult.cycles ? (
                  <span className="text-xs text-muted-foreground">（{testResult.cycles} 次换盘）</span>
                ) : null}
              </div>
              <div className="text-xs text-muted-foreground">
                文件已保存到服务端产物目录，可在产物库中下载、删除或直接下发到打印机空跑验证。
              </div>
              <Button asChild variant="outline" size="sm">
                <Link href="/production/gcodes">前往产物库</Link>
              </Button>
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
