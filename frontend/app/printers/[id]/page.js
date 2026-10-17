"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
  formatDateTime,
  formatGcodeState,
  gcodeStateVariant,
  getLatestReport,
  getPrinter,
  printerRealtimeUrl
} from "../../../lib/printer-control-api";
import { Badge } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../../components/ui/card";
import { DetailControlPanel } from "../../../components/printer/detail-control-panel";
import { DetailHmsAlert } from "../../../components/printer/detail-hms-alert";
import { DetailRealtimePanel } from "../../../components/printer/detail-realtime-panel";

/**
 * 打印机设备详情页。
 *
 * 数据来源两条腿（缺一不可）：
 *
 * 1. `GET /printers/{id}/latest-report` —— 首屏兜底。SSE 只在**出现新事件**时推送，
 *    空闲设备可能几分钟没有新事件，只靠 SSE 会长时间空白；
 * 2. `GET /realtime/printers/{id}`（EventSource）—— 实时增量。
 *
 * 两者写入同一个 `liveState`，并用 `occurred_at` 做「只接受不更旧的数据」的仲裁，
 * 避免轮询响应晚到把更新的 SSE 数据覆盖回去。
 *
 * 连接状态（顶部指示）：
 * - `connected`：收到 `onopen` 或任意一条 `printer` 事件；
 * - `retrying`：`onerror` 且 readyState 仍为 CONNECTING —— EventSource 正在自动重连；
 * - `closed`：`onerror` 且 readyState 为 CLOSED —— 浏览器放弃重连，需要手动刷新重建。
 */

const CONNECTION_META = {
  connecting: {
    label: "建立连接中…",
    hint: "正在订阅实时数据",
    dot: "bg-[#ff9500]",
    text: "text-[#8a5a00] dark:text-[#ffb340]"
  },
  connected: {
    label: "实时连接正常",
    hint: "SSE 已订阅，数据自动刷新",
    dot: "bg-[#34c759]",
    text: "text-[#248a3d] dark:text-[#30d158]"
  },
  retrying: {
    label: "重连中…",
    hint: "连接中断，浏览器正在自动重连（同时走轮询兜底）",
    dot: "bg-[#ff9500] animate-pulse",
    text: "text-[#8a5a00] dark:text-[#ffb340]"
  },
  closed: {
    label: "连接已断开",
    hint: "实时通道已关闭；数据改为轮询兜底，可点「重新连接」",
    dot: "bg-destructive",
    text: "text-destructive"
  }
};

function statusVariant(status) {
  const s = String(status || "").toLowerCase();
  if (s === "online") return "success";
  if (s === "unknown") return "outline";
  if (s === "offline") return "secondary";
  return "outline";
}

function linkLabel(link) {
  if (link === "lan") return "局域网直连";
  if (link === "cloud") return "云端通路";
  return "通路未连通";
}

function describeLoadError(err) {
  const status = Number(err?.status ?? 0);
  if (status === 404) return "设备不存在，可能已被删除";
  if (status === 422) return "设备 ID 格式不正确（需为 UUID）";
  if (status === 0) return "请求超时，请检查 API 服务是否正常";
  return err?.message ? String(err.message) : "加载设备信息失败";
}

export default function Page() {
  const params = useParams();
  // Next 15 的 useParams 可能返回 string | string[]，统一收敛成字符串
  const rawId = params?.id;
  const printerId = Array.isArray(rawId) ? rawId[0] : typeof rawId === "string" ? rawId : "";

  const [printer, setPrinter] = useState(null);
  const [printerLoading, setPrinterLoading] = useState(true);
  const [printerError, setPrinterError] = useState(null);

  const [liveState, setLiveState] = useState(null);
  const [eventMeta, setEventMeta] = useState(null);

  const [connection, setConnection] = useState("connecting");
  // 递增即可重建 EventSource（用于「重新连接」按钮）
  const [sseToken, setSseToken] = useState(0);

  const [tab, setTab] = useState("realtime");

  // 组件是否已卸载：防止 close() 触发的 onerror 在卸载后再 setState
  const closedRef = useRef(false);
  // 已应用数据的 occurred_at（毫秒）：只接受不更旧的数据
  const lastOccurredAtRef = useRef(0);

  /** 统一写入实时状态（SSE 与轮询共用，带时序仲裁）。 */
  const applySnapshot = useCallback((data, meta) => {
    const occurredAt = meta?.occurredAt || null;
    const ts = occurredAt ? new Date(occurredAt).getTime() : 0;
    const usable = Number.isFinite(ts) && ts > 0;
    if (usable && ts < lastOccurredAtRef.current) return;
    if (usable) lastOccurredAtRef.current = ts;

    if (data && typeof data === "object") setLiveState(data);
    if (meta) setEventMeta(meta);
  }, []);

  // —— 设备基础信息（别名 / 序列号 / 型号 / IP / 在线状态）——
  useEffect(() => {
    if (!printerId) {
      setPrinterLoading(false);
      return undefined;
    }
    let cancelled = false;

    async function load({ silent = false } = {}) {
      try {
        if (!silent) setPrinterLoading(true);
        const data = await getPrinter(printerId);
        if (cancelled) return;
        setPrinter(data);
        setPrinterError(null);
      } catch (err) {
        if (cancelled) return;
        setPrinterError(describeLoadError(err));
      } finally {
        if (!cancelled && !silent) setPrinterLoading(false);
      }
    }

    load();
    // 在线状态由设备心跳决定，低频刷新即可（不用额外开一条全局 SSE）
    const timer = setInterval(() => load({ silent: true }), 20000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [printerId]);

  // —— SSE 实时订阅 ——
  useEffect(() => {
    if (!printerId) return undefined;

    closedRef.current = false;
    setConnection("connecting");

    const es = new EventSource(printerRealtimeUrl(printerId));

    const onPrinter = (e) => {
      if (closedRef.current) return;
      try {
        const payload = JSON.parse(e.data);
        if (!payload || typeof payload !== "object") return;
        // 防御：订阅的是单机频道，万一串台也不写入别人的数据
        if (payload.printer_id && String(payload.printer_id) !== String(printerId)) return;

        applySnapshot(payload.data, {
          type: payload.type ?? null,
          eventId: payload.event_id ?? null,
          occurredAt: payload.occurred_at ?? null
        });
        setConnection("connected");
      } catch (_err) {
        // 单条 payload 解析失败不影响后续事件
      }
    };

    es.addEventListener("printer", onPrinter);
    es.onopen = () => {
      if (!closedRef.current) setConnection("connected");
    };
    es.onerror = () => {
      if (closedRef.current) return;
      // EventSource 自带重连：CONNECTING=正在重试，CLOSED=已放弃
      setConnection(es.readyState === EventSource.CLOSED ? "closed" : "retrying");
    };

    return () => {
      closedRef.current = true;
      es.removeEventListener("printer", onPrinter);
      // 必须 close：否则卸载后浏览器仍会持续重连，后端 SSE 连接会泄漏
      es.close();
    };
  }, [printerId, sseToken, applySnapshot]);

  // —— 轮询兜底（SSE 在部分代理 / 移动网络下会被阻断）——
  useEffect(() => {
    if (!printerId) return undefined;

    let cancelled = false;

    async function pull() {
      try {
        const rep = await getLatestReport(printerId);
        if (cancelled || !rep) return;
        applySnapshot(rep.event, {
          type: rep.type ?? null,
          eventId: rep.event_id ?? null,
          occurredAt: rep.occurred_at ?? null
        });
      } catch (_err) {
        // 轮询失败保持静默：连接状态已经在上方指示，不刷屏 toast
      }
    }

    pull();
    const interval = connection === "connected" ? 15000 : 4000;
    const timer = setInterval(pull, interval);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [printerId, connection, applySnapshot]);

  /** 控制成功后手动拉一次最新状态（轮询也会兜住，这里让反馈更快）。 */
  const refreshLatest = useCallback(async () => {
    if (!printerId) return;
    try {
      const rep = await getLatestReport(printerId);
      if (!rep) return;
      applySnapshot(rep.event, {
        type: rep.type ?? null,
        eventId: rep.event_id ?? null,
        occurredAt: rep.occurred_at ?? null
      });
    } catch (err) {
      toast.error(err?.message ? String(err.message) : "刷新实时数据失败");
    }
  }, [printerId, applySnapshot]);

  function reconnect() {
    setSseToken((n) => n + 1);
    refreshLatest();
  }

  const connMeta = CONNECTION_META[connection] || CONNECTION_META.connecting;
  const title = printer?.alias || printer?.serial || (printerId ? "设备详情" : "缺少设备 ID");

  return (
    <div className="space-y-6">
      {/* —— 顶部：返回 + 设备标识 + 连接状态 —— */}
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 space-y-2">
          <Button asChild variant="ghost" size="sm" className="-ml-3">
            <Link href="/printers" aria-label="返回打印机列表">
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
                className="mr-1"
                aria-hidden="true"
              >
                <path d="m15 18-6-6 6-6" />
              </svg>
              返回打印机
            </Link>
          </Button>

          <div className="flex flex-wrap items-center gap-2">
            <h1 className="min-w-0 break-all text-2xl font-semibold tracking-tight">{title}</h1>
            {printer ? <Badge variant={statusVariant(printer.status)}>{printer.status || "unknown"}</Badge> : null}
            {liveState ? (
              <Badge variant={gcodeStateVariant(liveState.gcode_state)}>{formatGcodeState(liveState.gcode_state)}</Badge>
            ) : null}
          </div>

          <dl className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground">
            <div className="flex gap-1">
              <dt>序列号</dt>
              <dd className="break-all font-mono">{printer?.serial || "-"}</dd>
            </div>
            <div className="flex gap-1">
              <dt>型号</dt>
              <dd>{printer?.model || "-"}</dd>
            </div>
            <div className="flex gap-1">
              <dt>IP</dt>
              <dd className="font-mono">{printer?.ip || "-"}</dd>
            </div>
            <div className="flex gap-1">
              <dt>通路</dt>
              <dd>{linkLabel(printer?.link_used)}</dd>
            </div>
            <div className="flex gap-1">
              <dt>最后连接</dt>
              <dd>{printer?.last_seen ? formatDateTime(printer.last_seen) : "-"}</dd>
            </div>
          </dl>
        </div>

        <div className="flex flex-col items-start gap-2 lg:items-end">
          <div
            className="flex items-center gap-2 rounded-full border border-black/[0.06] px-3 py-1.5 text-xs dark:border-white/10"
            role="status"
            aria-live="polite"
          >
            <span className={`h-2 w-2 shrink-0 rounded-full ${connMeta.dot}`} aria-hidden="true" />
            <span className={`font-medium ${connMeta.text}`}>{connMeta.label}</span>
          </div>
          <p className="max-w-xs text-xs text-muted-foreground lg:text-right">{connMeta.hint}</p>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={refreshLatest}>
              刷新数据
            </Button>
            {connection === "closed" ? (
              <Button size="sm" onClick={reconnect}>
                重新连接
              </Button>
            ) : null}
          </div>
        </div>
      </div>

      {/* —— 加载 / 错误 —— */}
      {!printerId ? (
        <Card>
          <CardHeader>
            <CardTitle>缺少设备 ID</CardTitle>
            <CardDescription>请从打印机列表进入设备详情。</CardDescription>
          </CardHeader>
          <CardContent>
            <Button asChild variant="outline">
              <Link href="/printers">返回打印机列表</Link>
            </Button>
          </CardContent>
        </Card>
      ) : null}

      {printerError && !printer ? (
        <Card className="border-destructive/40">
          <CardHeader>
            <CardTitle className="text-destructive">无法加载设备</CardTitle>
            <CardDescription className="break-all">{printerError}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => setSseToken((n) => n + 1)}>
              重试
            </Button>
            <Button asChild variant="ghost">
              <Link href="/printers">返回打印机列表</Link>
            </Button>
          </CardContent>
        </Card>
      ) : null}

      {printerLoading && !printer && !printerError ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">加载设备信息…</CardContent>
        </Card>
      ) : null}

      {/* —— HMS 故障告警（非空才渲染，位于页面顶部显眼处）—— */}
      <DetailHmsAlert hms={liveState?.hms} />

      {/* —— Tab 切换 —— */}
      <div className="space-y-4">
        <div
          className="flex gap-1 rounded-full bg-[#f5f5f7] p-1 dark:bg-white/10"
          role="tablist"
          aria-label="设备详情视图"
        >
          <button
            type="button"
            role="tab"
            id="tab-realtime"
            aria-selected={tab === "realtime"}
            aria-controls="panel-realtime"
            onClick={() => setTab("realtime")}
            className={`flex-1 cursor-pointer rounded-full px-4 py-2 text-sm font-medium transition-colors ${
              tab === "realtime"
                ? "bg-white text-foreground shadow-[0_1px_3px_rgba(0,0,0,0.12)] dark:bg-[#1d1d1f] dark:text-white"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            实时数据
          </button>
          <button
            type="button"
            role="tab"
            id="tab-control"
            aria-selected={tab === "control"}
            aria-controls="panel-control"
            onClick={() => setTab("control")}
            className={`flex-1 cursor-pointer rounded-full px-4 py-2 text-sm font-medium transition-colors ${
              tab === "control"
                ? "bg-white text-foreground shadow-[0_1px_3px_rgba(0,0,0,0.12)] dark:bg-[#1d1d1f] dark:text-white"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            设备控制
          </button>
        </div>

        {tab === "realtime" ? (
          <div role="tabpanel" id="panel-realtime" aria-labelledby="tab-realtime">
            <DetailRealtimePanel liveState={liveState} eventMeta={eventMeta} />
          </div>
        ) : (
          <div role="tabpanel" id="panel-control" aria-labelledby="tab-control">
            <DetailControlPanel printerId={printerId} liveState={liveState} onRefresh={refreshLatest} />
          </div>
        )}
      </div>
    </div>
  );
}
