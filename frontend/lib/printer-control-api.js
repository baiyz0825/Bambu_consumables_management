import { apiBaseUrl, fetchJson } from "./api";

/**
 * 打印机设备详情页（`app/printers/[id]/page.js`）的状态查询 + 控制封装。
 *
 * 端点来源（路径与请求体严格对齐后端，不要自行改写）：
 *
 * - 状态：`backend/app/api/routers/printers.py`
 *   - `GET /printers/{id}`            → PrinterDetail（id/ip/serial/alias/model/status/link_used/last_seen）
 *   - `GET /printers/{id}/latest-report` → { printer_id, event, type, event_id, occurred_at }
 *   - SSE `GET /realtime/printers/{id}` → `event: printer` + `data: {printer_id, type, event_id, occurred_at, data}`
 * - 控制：`backend/app/api/routers/controls.py`（全部 `POST /printers/{id}/...`）
 * - 故障文案：`backend/app/api/routers/hms.py`（`/hms/meta`、`/hms/lookup`）
 *
 * 错误约定（前端据此区分视觉提示）：
 *
 * - `400` 参数不合法 / G-code 未过白名单 / 温度超上限 → 提示用户改参数；
 * - `409` 打印中拒绝运动控制 → 状态冲突（不是参数错）；
 * - `502` 打印机 MQTT 不可达 → 上游设备不可达（响应体仍是 `{accepted:false, detail}`）；
 * - `404` 打印机不存在。
 */

const PRINTERS = "/printers";

/** 拼 `/printers/{id}{suffix}`，id 做 encode 以防异常字符破坏路径。 */
function printerPath(printerId, suffix = "") {
  return `${PRINTERS}/${encodeURIComponent(String(printerId ?? "").trim())}${suffix}`;
}

/** 统一 POST：无请求体时只发 method（后端这些端点都不带 body）。 */
function post(path, body) {
  return fetchJson(path, body === undefined ? { method: "POST" } : { method: "POST", body: JSON.stringify(body) });
}

// ---------------------------------------------------------------------------
// 状态查询
// ---------------------------------------------------------------------------

/** 设备基础信息（别名 / 序列号 / 型号 / IP / 在线状态）。 */
export function getPrinter(printerId) {
  return fetchJson(printerPath(printerId));
}

/**
 * 最近一次归一化上报。
 *
 * 注意：SSE 只在**出现新事件**时才推送，进页面时必须先用本接口兜底渲染，
 * 否则空闲设备会长时间白屏。
 */
export function getLatestReport(printerId) {
  return fetchJson(printerPath(printerId, "/latest-report"));
}

/** SSE 订阅地址，交给 `new EventSource(...)` 使用。 */
export function printerRealtimeUrl(printerId) {
  return `${apiBaseUrl()}/realtime/printers/${encodeURIComponent(String(printerId ?? "").trim())}`;
}

// ---------------------------------------------------------------------------
// 打印流程控制
// ---------------------------------------------------------------------------

/** 暂停打印（`print.pause`）。 */
export function pausePrint(printerId) {
  return post(printerPath(printerId, "/pause"));
}

/** 恢复打印（`print.resume`）。 */
export function resumePrint(printerId) {
  return post(printerPath(printerId, "/resume"));
}

/** 停止打印（`print.stop`）——**不可恢复**，前端必须二次确认。 */
export function stopPrint(printerId) {
  return post(printerPath(printerId, "/stop"));
}

/** 速度档位：1=静音 2=标准 3=运动 4=狂暴。 */
export function setSpeedLevel(printerId, level) {
  return post(printerPath(printerId, "/speed"), { level: Number(level) });
}

// ---------------------------------------------------------------------------
// 灯光
// ---------------------------------------------------------------------------

/**
 * 机身 LED。
 * @param {{node?: "chamber_light"|"work_light", mode?: "on"|"off"|"flashing"}} options
 */
export function setLed(printerId, { node = "chamber_light", mode = "on" } = {}) {
  return post(printerPath(printerId, "/led"), { node, mode });
}

// ---------------------------------------------------------------------------
// 温度（走 G-code 白名单端点：M104 喷嘴 / M140 热床）
// ---------------------------------------------------------------------------

/** 单行 G-code（后端会做白名单与温度上限校验）。 */
export function sendGcode(printerId, line) {
  return post(printerPath(printerId, "/gcode"), { line: String(line ?? "").trim() });
}

/** 设定喷嘴目标温度，发 `M104 S{temp}`。 */
export function setNozzleTemp(printerId, temp) {
  return sendGcode(printerId, `M104 S${Math.round(Number(temp))}`);
}

/** 设定热床目标温度，发 `M140 S{temp}`。 */
export function setBedTemp(printerId, temp) {
  return sendGcode(printerId, `M140 S${Math.round(Number(temp))}`);
}

// ---------------------------------------------------------------------------
// 运动控制（打印中后端 409 拒绝，前端应提前禁用）
// ---------------------------------------------------------------------------

/**
 * 单轴相对移动。
 * @param {{axis: "X"|"Y"|"Z", distance: number, speed?: number|null}} options
 *        distance 绝对值 ≤ 200mm；speed 缺省 3000，范围 60-12000 mm/min。
 */
export function moveAxis(printerId, { axis, distance, speed = null }) {
  const payload = { axis, distance: Number(distance) };
  if (speed !== null && speed !== undefined && String(speed).trim() !== "") payload.speed = Number(speed);
  return post(printerPath(printerId, "/move"), payload);
}

/** 回零（`G28`）；axes 缺省 "XYZ"，可为 "X"/"Z"/"XY"。 */
export function homeAxes(printerId, axes = "XYZ") {
  return post(printerPath(printerId, "/home"), { axes });
}

/**
 * 挤出 / 回抽，正数进料、负数退料。
 * 绝对值 ≤ 100mm，且**需喷嘴已加热**，否则固件冷挤出保护会拒绝。
 */
export function extrudeFilament(printerId, distance) {
  return post(printerPath(printerId, "/extrude"), { distance: Number(distance) });
}

// ---------------------------------------------------------------------------
// AMS / 校准
// ---------------------------------------------------------------------------

/**
 * AMS 换料。
 * @param {number} target 0-3 为 AMS 四槽，254/255 为外挂料盘。
 */
export function amsChange(printerId, target) {
  return post(printerPath(printerId, "/ams/change"), { target: Number(target) });
}

/**
 * 校准位掩码（1-15，按位或）：1=调平 2=震动 4=流量 8=电机噪音。
 */
export function calibrate(printerId, bitmask) {
  return post(printerPath(printerId, "/calibrate"), { bitmask: Number(bitmask) });
}

// ---------------------------------------------------------------------------
// HMS 故障码表
// ---------------------------------------------------------------------------

/** 码表元信息（含 `modules`：`"07" → "AMS"` 的模块名映射）。 */
export function hmsMeta() {
  return fetchJson("/hms/meta", { timeoutMs: 8000 });
}

/**
 * 批量查故障文案。
 * @param {string[]|string} ecodes 8 位 ecode 列表（或逗号分隔串）
 * @returns {Promise<{codes: Record<string,{intro?:string,actions?:number[]}>, missing: string[]}>}
 */
export function hmsLookup(ecodes) {
  const list = (Array.isArray(ecodes) ? ecodes : String(ecodes || "").split(","))
    .map((v) => String(v || "").trim().toUpperCase())
    .filter(Boolean);
  if (list.length === 0) return Promise.resolve({ codes: {}, missing: [] });
  return fetchJson(`/hms/lookup?ecodes=${encodeURIComponent(list.join(","))}`, { timeoutMs: 8000 });
}

// ---------------------------------------------------------------------------
// 以下为「纯展示 / 纯校验」辅助函数（无副作用，组件与页面共用）
// ---------------------------------------------------------------------------

/** 安全转数字：空串 / null / NaN / 非数字一律返回 null。 */
export function toNumber(value) {
  if (value === null || value === undefined) return null;
  const s = typeof value === "string" ? value.trim() : value;
  if (s === "") return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

/** `gcode_state` 中文映射（未知状态回退原始值，不臆造中文名）。 */
export const GCODE_STATE_LABELS = {
  IDLE: "空闲",
  RUNNING: "打印中",
  PAUSE: "暂停",
  PAUSED: "暂停",
  PREPARE: "准备中",
  PREPARING: "准备中",
  FINISH: "已完成",
  FINISHED: "已完成",
  FAILED: "失败",
  SLICING: "切片中"
};

export function formatGcodeState(value) {
  if (value === null || value === undefined) return "-";
  const key = String(value).trim().toUpperCase();
  if (!key) return "-";
  return GCODE_STATE_LABELS[key] || key;
}

/** 状态徽标配色（沿用 ui/badge 的 variant）。 */
export function gcodeStateVariant(value) {
  const key = String(value || "").trim().toUpperCase();
  if (key === "RUNNING") return "info";
  if (key === "PAUSE" || key === "PAUSED") return "warning";
  if (key === "FAILED") return "destructive";
  if (key === "FINISH" || key === "FINISHED") return "success";
  if (key === "PREPARE" || key === "PREPARING") return "info";
  return "outline";
}

/**
 * 运动控制锁：与后端 `MOTION_BLOCKING_STATES = {RUNNING, PREPARE}` 保持一致。
 * 返回 `null` 表示可操作，否则返回禁用原因文案（直接展示给用户）。
 */
export function motionLockedReason(gcodeState) {
  const key = String(gcodeState || "").trim().toUpperCase();
  if (key === "RUNNING") return "打印中禁止运动控制（避免撞件）";
  if (key === "PREPARE") return "准备阶段禁止运动控制（喷头随时会动）";
  return null;
}

/** 速度档位文案：1=静音 2=标准 3=运动 4=狂暴。 */
export const SPEED_LEVELS = [
  { level: 1, label: "静音" },
  { level: 2, label: "标准" },
  { level: 3, label: "运动" },
  { level: 4, label: "狂暴" }
];

export function speedLevelLabel(level) {
  const n = toNumber(level);
  if (n == null) return null;
  const hit = SPEED_LEVELS.find((s) => s.level === n);
  return hit ? hit.label : `第 ${n} 档`;
}

/** 校准位掩码组成（后端注释：1=调平 2=震动 4=流量 8=电机噪音）。 */
export const CALIBRATION_BITS = [
  { bit: 1, label: "调平" },
  { bit: 2, label: "震动" },
  { bit: 4, label: "流量" },
  { bit: 8, label: "电机噪音" }
];

/** 把位掩码拆成中文清单，例如 5 → 「调平 / 流量」。 */
export function describeBitmask(mask) {
  const n = toNumber(mask);
  if (n == null) return "-";
  const parts = CALIBRATION_BITS.filter((b) => (n & b.bit) !== 0).map((b) => b.label);
  return parts.length > 0 ? parts.join(" / ") : "无";
}

/** 温度对（当前 → 目标），差值 < 5℃ 视为达标。 */
export function formatTempPair(current, target) {
  const c = toNumber(current);
  const t = toNumber(target);
  if (c === null && t === null) return { text: "-", reached: false, current: null, target: null };
  const cs = c === null ? "-" : c.toFixed(1);
  const ts = t === null ? "-" : String(Math.round(t));
  const reached = c !== null && t !== null && t > 0 && Math.abs(c - t) < 5;
  return { text: `${cs} → ${ts} ℃`, reached, current: c, target: t };
}

/**
 * 风扇转速：固件可能回传 0-100 的百分比，也可能回传 0-255 的原始 PWM。
 * 用「>100 即视为 0-255」做兼容判断，并把原始值一并回传供页面标注。
 */
export function describeFan(value) {
  const n = toNumber(value);
  if (n === null) return { percent: null, raw: null, text: "-" };
  if (n <= 100 && n >= 0) return { percent: Math.round(n), raw: n, text: `${Math.round(n)}%` };
  const clamped = Math.min(255, Math.max(0, n));
  const percent = Math.round((clamped / 255) * 100);
  return { percent, raw: n, text: `${percent}%（原始 ${n}）` };
}

/**
 * AMS 颜色：固件是 `RRGGBBAA`（偶见 `AARRGGBB`），统一转 `#RRGGBB`。
 * 无法解析返回 null（调用方展示原始值或 "-"）。
 */
export function normalizeColorHex(value) {
  if (value === null || value === undefined) return null;
  const raw = String(value).trim();
  if (!raw) return null;
  const hex = (raw.startsWith("#") ? raw.slice(1) : raw).toUpperCase();
  if (!/^[0-9A-F]+$/.test(hex)) return null;
  if (hex.length === 6) return `#${hex}`;
  if (hex.length === 8) {
    // 常规是 RRGGBBAA（如 `FFFFFF00`）；尾字节既不是 FF 也不是 00 时，
    // 再回头判断是否其实是 AARRGGBB，两者都不像就保留前 6 位。
    if (hex.endsWith("FF") || hex.endsWith("00")) return `#${hex.slice(0, 6)}`;
    if (hex.startsWith("FF") || hex.startsWith("00")) return `#${hex.slice(-6)}`;
    return `#${hex.slice(0, 6)}`;
  }
  return null;
}

/** 余量归一化：≤1 视为小数比例，≤100 视为百分比，其余无法判定返回 null。 */
export function normalizeRemainPct(value) {
  const n = toNumber(value);
  if (n === null || n < 0) return null;
  if (n <= 1) return n * 100;
  if (n <= 100) return n;
  return null;
}

/** 槽位号文案：0-3 为 AMS，254/255 为外挂料盘，其余原样显示。 */
export function formatTraySlot(value) {
  const n = toNumber(value);
  if (n === null) return "-";
  if (n === 255 || n === 254) return `${n}（外挂料盘）`;
  return `槽位 ${n}`;
}

/** 时间格式化：无法解析时回退原始字符串，避免出现 Invalid Date。 */
export function formatDateTime(iso) {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return d.toLocaleString();
}

/**
 * 把控制类错误归一成「一眼能分辨」的提示。
 *
 * 409（状态冲突）与 502（打印机不可达）必须视觉可区分：前者是「现在不能做」，
 * 后者是「机器连不上」，用户的后续动作完全不同。
 *
 * @returns {{status:number, kind:"conflict"|"unreachable"|"invalid"|"notfound"|"unknown", title:string, message:string}}
 */
export function describeControlError(err) {
  const status = Number(err?.status ?? 0);
  const detail = err?.detail;
  const message =
    typeof detail === "string" && detail.trim()
      ? detail.trim()
      : err?.message && String(err.message).trim()
        ? String(err.message).trim()
        : "未知错误，请稍后重试";

  if (status === 409) return { status, kind: "conflict", title: "状态冲突（409）", message };
  if (status === 502) return { status, kind: "unreachable", title: "打印机不可达（502）", message };
  if (status === 400) return { status, kind: "invalid", title: "请求被拒绝（400）", message };
  if (status === 404) return { status, kind: "notfound", title: "设备不存在（404）", message };
  if (status === 0) return { status, kind: "unknown", title: "网络异常", message };
  return { status, kind: "unknown", title: `操作失败（${status || "未知状态码"}）`, message };
}
