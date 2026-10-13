"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { z } from "zod";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";

import { apiBaseUrl, fetchJson } from "../../lib/api";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { DataCell, DataTable } from "../../components/ui/data-table";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { PrinterScanDialog } from "../../components/printer-scan-dialog";
import { TrayBindDialog } from "../../components/tray-bind-dialog";
import { FilamentSpool } from "../../components/filament-spool";

function formatGcodeState(st) {
  if (!st) return "-";
  const s = String(st).toUpperCase();
  if (s === "RUNNING") return "打印中";
  if (s === "PAUSE" || s === "PAUSED") return "暂停";
  if (s === "FINISH" || s === "IDLE") return "空闲";
  if (s === "PREPARE" || s === "PREPARING") return "准备中";
  if (s === "FAILED" || s === "ERROR") return "异常";
  return s;
}

function fmtTime(iso) {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return d.toLocaleString();
}

function linkLabel(link) {
  if (link === "lan") return "当前局域网";
  if (link === "cloud") return "当前云端";
  return "通路未连通";
}

function statusVariant(status) {
  const s = String(status || "").toLowerCase();
  if (s === "online") return "success";
  if (s === "unknown") return "outline";
  if (s === "offline") return "secondary";
  return "outline";
}

const printerSchema = z.object({
  ip: z.string().trim().min(1, "请输入 IP"),
  serial: z.string().trim().min(1, "请输入 Serial"),
  lan_access_code: z.string().trim().min(1, "请输入 LAN Code"),
  alias: z.string().trim().optional(),
  model: z.string().trim().optional()
});

export default function Page() {
  const [items, setItems] = useState([]);
  const [reportsById, setReportsById] = useState({});
  const [stocks, setStocks] = useState([]);
  const [colorMappings, setColorMappings] = useState({});
  const [colorDraftByHex, setColorDraftByHex] = useState({});
  const [savingColorHex, setSavingColorHex] = useState(null);
  const [loading, setLoading] = useState(false);
  const [scanOpen, setScanOpen] = useState(false);
  // 托盘手动绑定：key 为 `${printer_id}:${tray_id}`，值为后端 /tray-mappings 返回的绑定记录
  const [trayMappings, setTrayMappings] = useState({});
  // 当前正在编辑绑定的托盘（{ printerId, trayId }），为 null 表示无
  const [bindTarget, setBindTarget] = useState(null);
  const [bindOpen, setBindOpen] = useState(false);

  const printerIdsKey = items
    .map((p) => p && p.id)
    .filter(Boolean)
    .join("|");

  async function reload() {
    try {
      setLoading(true);
      const data = await fetchJson("/printers");
      setItems(data);
    } finally {
      setLoading(false);
    }
  }

  async function reloadStocks() {
    try {
      const s = await fetchJson("/stocks");
      setStocks(Array.isArray(s) ? s : []);
    } catch (e) {
      toast.error(String(e?.message || e));
    }
  }

  /** 加载当前生效的托盘绑定（只取 active），并按 `printer:tray` 建索引便于表格查表。 */
  async function reloadTrayMappings() {
    try {
      const rows = await fetchJson("/tray-mappings?active_only=true");
      const map = {};
      for (const r of Array.isArray(rows) ? rows : []) {
        if (r?.printer_id == null || r?.tray_id == null) continue;
        map[`${r.printer_id}:${r.tray_id}`] = r;
      }
      setTrayMappings(map);
    } catch (e) {
      // 绑定属于增强信息：加载失败仅降级为「未绑定（自动匹配）」，不打断页面主流程
      console.warn("load tray mappings failed", e);
    }
  }

  /** 打开指定托盘的绑定 Dialog。 */
  function openBindDialog(printerId, trayId) {
    setBindTarget({ printerId, trayId });
    setBindOpen(true);
  }

  function normalizeColorHex(v) {
    if (v == null) return null;
    const s0 = String(v).trim();
    if (!s0) return null;
    const raw = s0.startsWith("#") ? s0.slice(1).trim() : s0;
    const hx = raw.toUpperCase();
    if (!/^[0-9A-F]+$/.test(hx)) return null;
    if (hx.length === 8) {
      // Keep consistent with backend normalization (supports both RRGGBBAA and AARRGGBB).
      if (hx.endsWith("FF") || hx.endsWith("00")) return `#${hx.slice(0, 6)}`; // RRGGBBAA
      if (hx.startsWith("FF") || hx.startsWith("00")) return `#${hx.slice(-6)}`; // AARRGGBB
      return `#${hx.slice(-6)}`;
    }
    if (hx.length === 6) return `#${hx}`;
    return null;
  }

  async function reloadColorMappings() {
    try {
      const rows = await fetchJson("/color-mappings");
      const map = {};
      for (const r of Array.isArray(rows) ? rows : []) {
        if (r?.color_hex && r?.color_name) map[String(r.color_hex)] = String(r.color_name);
      }
      setColorMappings(map);
    } catch (e) {
      toast.error(String(e?.message || e));
    }
  }

  async function saveColorMapping(colorHex) {
    const name = String(colorDraftByHex[colorHex] || "").trim();
    if (!name) {
      toast.error("请输入要映射的颜色名（如：白色/灰色）");
      return;
    }
    try {
      setSavingColorHex(colorHex);
      await fetchJson("/color-mappings", {
        method: "POST",
        body: JSON.stringify({ color_hex: colorHex, color_name: name })
      });
      toast.success(`已保存映射：${colorHex} -> ${name}`);
      setColorDraftByHex((prev) => ({ ...prev, [colorHex]: "" }));
      await reloadColorMappings();
      await reloadStocks();
    } catch (e) {
      if (e && e.status === 409) {
        const d = e.detail;
        if (d && typeof d === "object" && d.color_hex && d.existing_color_name) {
          toast.error(`该颜色码已映射且不可修改：${d.color_hex} -> ${d.existing_color_name}`);
        } else {
          toast.error("该颜色码已映射且不可修改；如需修正请新增另一个颜色码映射。");
        }
      } else {
        toast.error(String(e?.message || e));
      }
    } finally {
      setSavingColorHex(null);
    }
  }

  useEffect(() => {
    reload();
    reloadStocks();
    reloadColorMappings();
    reloadTrayMappings();

    // Realtime updates via SSE
    const url = `${apiBaseUrl()}/realtime/printers`;
    const es = new EventSource(url);
    es.addEventListener("printers", (e) => {
      try {
        const payload = JSON.parse(e.data);
        if (payload && Array.isArray(payload.printers)) {
          setItems(payload.printers);
        }
      } catch (_err) {
        // ignore parse errors; user can still manually refresh
      }
    });
    es.onerror = () => {
      // Don't spam errors; keep manual refresh available
    };

    // Fallback polling (SSE may be blocked in some network/proxy setups)
    const pollId = setInterval(() => {
      reload();
    }, 5000);

    return () => {
      es.close();
      clearInterval(pollId);
    };
  }, []);

  // Per-printer live report (print status / progress / tray info)
  useEffect(() => {
    let cancelled = false;
    const sources = new Map();

    async function loadLatest(printerId) {
      try {
        const r = await fetchJson(`/printers/${printerId}/latest-report`);
        if (!cancelled) {
          setReportsById((prev) => ({ ...prev, [printerId]: r }));
        }
      } catch (_e) {
        // ignore; SSE may still fill
      }
    }

    for (const p of items) {
      if (!p?.id) continue;
      loadLatest(p.id);

      const sseUrl = `${apiBaseUrl()}/realtime/printers/${p.id}`;
      const es = new EventSource(sseUrl);
      es.addEventListener("printer", (e) => {
        try {
          const payload = JSON.parse(e.data);
          if (payload && payload.printer_id) {
            setReportsById((prev) => ({ ...prev, [payload.printer_id]: payload }));
          }
        } catch (_err) {
          // ignore parse errors
        }
      });
      es.onerror = () => {
        // ignore; polling still works
      };
      sources.set(p.id, es);
    }

    // low-frequency polling to cover SSE blocked cases
    const pollId = setInterval(() => {
      for (const p of items) {
        if (p?.id) loadLatest(p.id);
      }
    }, 4000);

    return () => {
      cancelled = true;
      clearInterval(pollId);
      for (const es of sources.values()) es.close();
    };
  }, [printerIdsKey]);

  const form = useForm({
    resolver: zodResolver(printerSchema),
    defaultValues: { ip: "", serial: "", lan_access_code: "", alias: "", model: "" }
  });

  async function onSubmit(values) {
    const payload = {
      ip: values.ip,
      serial: values.serial,
      lan_access_code: values.lan_access_code,
      alias: values.alias ? values.alias : null,
      model: values.model ? values.model : null
    };
    try {
      await fetchJson("/printers", { method: "POST", body: JSON.stringify(payload) });
      toast.success("打印机已添加");
    } catch (e) {
      const printerId = e?.detail?.printer_id;
      if (e?.status === 409 && printerId) {
        const patch = { ip: values.ip, lan_access_code: values.lan_access_code };
        if (values.alias) patch.alias = values.alias;
        if (values.model) patch.model = values.model;
        await fetchJson(`/printers/${printerId}`, { method: "PATCH", body: JSON.stringify(patch) });
        toast.success("这台打印机已在列表中，局域网地址已写到同一条记录");
      } else {
        throw e;
      }
    }
    form.reset({ ip: "", serial: "", lan_access_code: "", alias: "", model: "" });
    await reload();
  }

  function normalizeRemainPct(v) {
    if (v == null) return null;
    const n = Number(v);
    if (!Number.isFinite(n) || n < 0) return null;
    if (n <= 1) return n * 100; // fraction -> percent
    if (n <= 100) return n;
    return null; // unknown unit
  }

  function isOfficialTray(t) {
    if (!t || typeof t !== "object") return false;
    const tag = t.tag_uid;
    const uuid = t.tray_uuid;
    const name = t.tray_id_name;
    if (typeof tag === "number" && tag > 0) return true;
    if (typeof tag === "string" && tag.trim() && tag.trim() !== "0") return true;
    if (typeof uuid === "string" && uuid.trim()) return true;
    if (typeof name === "string" && name.trim()) return true;
    return false;
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight">打印机</h1>
          <p className="text-sm text-muted-foreground">
            一台打印机只保留一条记录。局域网能连上时走直连，否则走拓竹云上的同一台机器。
          </p>
        </div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:flex lg:flex-wrap lg:justify-end">
          <Button variant="outline" onClick={() => setScanOpen(true)}>
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
              className="mr-2"
            >
              <circle cx="12" cy="12" r="10" />
              <path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
            </svg>
            扫描局域网
          </Button>
          <Button variant="outline" onClick={reload} disabled={loading}>
            {loading ? "加载中…" : "刷新"}
          </Button>
          <Button variant="outline" onClick={reloadStocks}>
            刷新库存
          </Button>
          <Button variant="outline" onClick={reloadColorMappings}>
            刷新颜色映射
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>添加打印机</CardTitle>
          <CardDescription>LAN访问码将在后端加密存储。</CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="grid gap-4"
            onSubmit={form.handleSubmit(async (v) => {
              try {
                await onSubmit(v);
              } catch (e) {
                toast.error(String(e?.message || e));
              }
            })}
          >
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
              <div className="grid gap-2">
                <Label>IP *</Label>
                <Input placeholder="IP地址，例如：192.168.x.x" {...form.register("ip")} />
                {form.formState.errors.ip ? <div className="text-xs text-destructive">{form.formState.errors.ip.message}</div> : null}
              </div>
              <div className="grid gap-2">
                <Label>Serial *</Label>
                <Input placeholder="序列号，例如：A1Pxxxx..." {...form.register("serial")} />
                {form.formState.errors.serial ? <div className="text-xs text-destructive">{form.formState.errors.serial.message}</div> : null}
              </div>
              <div className="grid gap-2">
                <Label>LAN Code *</Label>
                <Input placeholder="LAN访问码" {...form.register("lan_access_code")} />
                {form.formState.errors.lan_access_code ? (
                  <div className="text-xs text-destructive">{form.formState.errors.lan_access_code.message}</div>
                ) : null}
              </div>
              <div className="grid gap-2">
                <Label>别名</Label>
                <Input placeholder="别名，可选" {...form.register("alias")} />
              </div>
              <div className="grid gap-2">
                <Label>型号</Label>
                <Input placeholder="型号，可选" {...form.register("model")} />
              </div>
            </div>
            <div>
              <Button type="submit" className="w-full sm:w-auto" disabled={form.formState.isSubmitting}>
                {form.formState.isSubmitting ? "提交中…" : "添加"}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      <div className="space-y-4">
        {items.map((p) => {
          const rep = reportsById[p.id];
          const ev = rep?.event || rep?.data || null;
          const gcodeState = ev?.gcode_state || ev?.gcodeState || null;
          const progress = ev?.progress ?? null;
          const taskId = ev?.task_id || ev?.subtask_id || null;
          const taskName = ev?.subtask_name || ev?.gcode_file || null;
          const trayNow = ev?.tray_now ?? null;
          const trays = Array.isArray(ev?.ams_trays) ? ev.ams_trays : [];
          // 固定 1 个 AMS（4 槽）：即便固件不回传空槽，也要稳定展示 0-3。
          const slotIds = [0, 1, 2, 3];
          const trayById = new Map();
          for (const t of trays) {
            const tid = t?.id;
            if (tid == null) continue;
            const n = Number(tid);
            if (!Number.isFinite(n)) continue;
            trayById.set(n, t);
          }
          const displayTrays = slotIds.map((id) => trayById.get(id) || { id, __missing: true });
          const occurredAt = rep?.occurred_at || null;
          const currentTray =
            trayNow == null || trayNow === 255 ? null : trays.find((t) => Number(t?.id) === Number(trayNow)) || null;
          const currentMaterial = currentTray?.type || "-";
          const currentColorHex = normalizeColorHex(currentTray?.color);
          const currentColorName = currentColorHex ? colorMappings[currentColorHex] || null : currentTray?.color || null;
          const currentColor = currentColorName ? `${currentColorName}${currentColorHex ? ` (${currentColorHex})` : ""}` : currentColorHex || currentTray?.color || "-";
          const currentOfficial = currentTray ? isOfficialTray(currentTray) : false;
          const currentColorKey = currentColorName || (!currentColorHex && typeof currentTray?.color === "string" ? currentTray.color : null);
          const currentCandidates = currentTray
            ? stocks.filter(
                (s) =>
                  s.material === currentMaterial &&
                  (currentColorKey ? s.color === currentColorKey : false) &&
                  (currentOfficial ? s.brand === "拓竹" : s.brand !== "拓竹")
              )
            : [];
          const currentStock = currentCandidates.length === 1 ? currentCandidates[0] : null;

          return (
            <Card key={p.id}>
              <CardHeader>
                <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
                  <div className="space-y-1">
                    <CardTitle className="flex items-center gap-2">
                      <span>{p.alias || p.serial}</span>
                      <Badge variant={statusVariant(p.status)}>{p.status}</Badge>
                      <Badge variant="outline">{linkLabel(p.link_used)}</Badge>
                    </CardTitle>
                    <CardDescription className="break-all">
                      {p.ip || "未填局域网地址"} · {p.serial} · 最后连接：{p.last_seen ? fmtTime(p.last_seen) : "-"}
                    </CardDescription>
                  </div>
                  <div className="min-w-0 break-words text-sm">
                    <div className="font-medium">{formatGcodeState(gcodeState)}</div>
                    <div className="text-muted-foreground">{progress == null ? "-" : `进度 ${progress}%`}</div>
                    <div className="text-muted-foreground">{taskId ? `${taskId}` : "-"} {taskName ? `· ${taskName}` : ""}</div>
                    <div className="text-muted-foreground">上报：{fmtTime(occurredAt)}</div>
                    <div className="text-muted-foreground">当前托盘：{trayNow == null || trayNow === 255 ? "-" : `托盘 ${trayNow}`}</div>
                    <div className="text-muted-foreground">
                      当前耗材：{currentTray ? `${currentMaterial} · ${currentColor}${currentOfficial ? "（拓竹）" : ""}` : "-"}
                    </div>
                    <div className="text-muted-foreground">
                      扣减库存：
                      {currentTray
                        ? currentColorHex && !currentColorName
                          ? "颜色未映射（先映射再匹配）"
                          : currentStock
                            ? `${currentStock.brand}（剩余 ${currentStock.remaining_grams}g）`
                            : currentCandidates.length > 1
                              ? "多品牌冲突（打印后归因）"
                              : "未匹配库存项"
                        : "-"}
                    </div>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="text-sm text-muted-foreground">AMS 托盘信息（材质/颜色/剩余）。系统会尝试匹配到唯一库存项；匹配不到会在作业里提示归因。</div>
                <DataTable className="lg:min-w-[720px]">
                  <thead className="bg-muted/50">
                    <tr className="text-left">
                      <th className="px-3 py-2">托盘</th>
                      <th className="px-3 py-2">材质</th>
                      <th className="px-3 py-2">颜色</th>
                      <th className="px-3 py-2">剩余(%)</th>
                      <th className="px-3 py-2">来源</th>
                      <th className="px-3 py-2">库存匹配</th>
                      <th className="px-3 py-2">库存绑定</th>
                    </tr>
                  </thead>
                  <tbody>
                    {displayTrays.map((t) => {
                      const trayId = t?.id;
                      if (trayId == null) return null;
                      const key = `${p.id}:${trayId}`;
                      // 手动绑定优先于自动颜色匹配；未绑定时回落到自动匹配结果
                      const binding = trayMappings[key] || null;
                      const isActiveTray = trayNow != null && trayNow !== 255 && Number(trayNow) === Number(trayId);
                      const isMissing = Boolean(t?.__missing);
                      const pct = normalizeRemainPct(t?.remain);
                      const material = isMissing ? "-" : t?.type || "-";
                      const colorHex = isMissing ? null : normalizeColorHex(t?.color);
                      const mappedName = colorHex ? colorMappings[colorHex] || null : null;
                      const colorKey = mappedName || (!colorHex && !isMissing && typeof t?.color === "string" ? t.color : null);
                      const colorDisplay = isMissing ? "-" : mappedName ? `${mappedName} (${colorHex})` : colorHex || t?.color || "-";
                      const official = !isMissing && isOfficialTray(t);
                      const candidates = stocks.filter(
                        (s) =>
                          s.material === material &&
                          (colorKey ? s.color === colorKey : false) &&
                          (official ? s.brand === "拓竹" : s.brand !== "拓竹")
                      );
                      const matched = candidates.length === 1 ? candidates[0] : null;
                      const matchText =
                        isMissing
                          ? "-"
                          : colorHex && !mappedName
                          ? "颜色未映射（先映射）"
                          : matched
                            ? `${matched.brand}（剩余 ${matched.remaining_grams}g）`
                            : candidates.length > 1
                              ? `多品牌冲突：${candidates.map((c) => c.brand).join(" / ")}（打印后归因）`
                              : "未匹配（去库存新增）";
                      const remainText = isMissing ? "-" : pct == null ? (t?.remain == null ? "-" : t.remain) : `${Math.round(pct)}%`;
                      const spoolRemain = pct != null && pct >= 0 && pct <= 100 ? pct : 0;
                      return (
                        <tr key={key} className={`border-t ${isActiveTray ? "bg-accent/30" : ""}`}>
                          <DataCell label="托盘" valueClassName="font-medium">
                            托盘 {trayId} {isActiveTray ? <span className="ml-2 text-xs font-normal text-muted-foreground">(正在使用)</span> : null}
                          </DataCell>
                          <DataCell label="材质">{material}</DataCell>
                          <DataCell label="颜色">
                            <div className="flex items-center gap-3">
                              <FilamentSpool
                                colors={colorHex}
                                percent={spoolRemain}
                                size={96}
                                title={`托盘 ${trayId} ${colorDisplay}`}
                              />
                              <div className="min-w-0 text-foreground">{colorDisplay}</div>
                            </div>
                            {colorHex && !mappedName && !isMissing ? (
                              <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:items-center">
                                <Input
                                  className="min-w-0 flex-1"
                                  placeholder="映射为：白色/灰色/…"
                                  value={colorDraftByHex[colorHex] || ""}
                                  onChange={(e) =>
                                    setColorDraftByHex((prev) => ({ ...prev, [colorHex]: e.target.value }))
                                  }
                                  aria-label={`为 ${colorHex} 填写颜色名`}
                                />
                                <Button
                                  size="sm"
                                  variant="outline"
                                  className="w-full sm:w-auto"
                                  disabled={savingColorHex === colorHex}
                                  onClick={() => saveColorMapping(colorHex)}
                                >
                                  {savingColorHex === colorHex ? "保存中…" : "保存映射"}
                                </Button>
                              </div>
                            ) : null}
                          </DataCell>
                          <DataCell label="剩余(%)">{remainText}</DataCell>
                          <DataCell label="来源">{isMissing ? "空槽/未上报" : official ? "拓竹" : "第三方/未知"}</DataCell>
                          <DataCell label="库存匹配">{matchText}</DataCell>
                          <DataCell label="库存绑定">
                            {isMissing ? (
                              <span className="text-xs text-muted-foreground">-</span>
                            ) : binding?.stock_id ? (
                              <div className="space-y-1">
                                <div className="text-xs font-medium">
                                  {binding.stock_material} · {binding.stock_color}
                                </div>
                                <div className="text-xs text-muted-foreground">
                                  {binding.stock_brand} · 剩余 {binding.stock_remaining_grams}g
                                </div>
                                <Button
                                  size="sm"
                                  variant="outline"
                                  className="w-full sm:w-auto"
                                  onClick={() => openBindDialog(p.id, trayId)}
                                >
                                  更改绑定
                                </Button>
                              </div>
                            ) : (
                              <Button
                                size="sm"
                                variant="outline"
                                className="w-full sm:w-auto"
                                onClick={() => openBindDialog(p.id, trayId)}
                              >
                                绑定库存
                              </Button>
                            )}
                          </DataCell>
                        </tr>
                      );
                    })}
                  </tbody>
                </DataTable>
              </CardContent>
            </Card>
          );
        })}
        {items.length === 0 ? (
          <Card>
            <CardContent className="py-10 text-center text-sm text-muted-foreground">暂无打印机，请先添加。</CardContent>
          </Card>
        ) : null}
      </div>

      {/* 局域网 mDNS 扫描添加打印机 */}
      <PrinterScanDialog
        open={scanOpen}
        onOpenChange={setScanOpen}
        existingSerials={items.map((p) => p.serial)}
        onSelect={(device) => {
          // 预填表单：扫描拿到的 ip/serial/model/alias 自动填入，用户只需补 LAN Code
          form.setValue("ip", device.ip, { shouldDirty: true, shouldValidate: true });
          form.setValue("serial", device.serial, { shouldDirty: true, shouldValidate: true });
          if (device.model) form.setValue("model", device.model, { shouldDirty: true });
          if (device.alias) form.setValue("alias", device.alias, { shouldDirty: true });
          // 清空 LAN Code 字段，引导用户去打印机屏幕查看
          form.setValue("lan_access_code", "", { shouldDirty: true });
          toast.success(`已选中 ${device.ip}（${device.model || "未知型号"}），请在打印机屏幕查看 LAN 访问码并填入`);
          // 滚动到表单顶部，方便用户继续填写
          setTimeout(() => {
            const el = document.querySelector('input[placeholder*="LAN"]');
            if (el) el.focus();
          }, 100);
        }}
      />

      {/* 托盘 ↔ 库存绑定（手动指定优先于颜色自动匹配） */}
      <TrayBindDialog
        open={bindOpen}
        onOpenChange={(v) => {
          setBindOpen(v);
          if (!v) setBindTarget(null);
        }}
        printerId={bindTarget?.printerId}
        trayId={bindTarget?.trayId}
        currentBinding={
          bindTarget ? trayMappings[`${bindTarget.printerId}:${bindTarget.trayId}`] || null : null
        }
        stocks={stocks}
        onBound={reloadTrayMappings}
      />
    </div>
  );
}


