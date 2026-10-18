"use client";

import dynamic from "next/dynamic";

import {
  describeFan,
  formatDateTime,
  formatGcodeState,
  gcodeStateVariant,
  formatTempPair,
  formatTraySlot,
  normalizeColorHex,
  normalizeRemainPct,
  speedLevelLabel,
  toNumber
} from "../../lib/printer-control-api";
import { Badge } from "../ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../ui/card";
const TwinView = dynamic(() => import("./twin/twin-view").then((m) => m.TwinView), {
  ssr: false,
  loading: () => (
    <div className="flex h-[420px] w-full items-center justify-center rounded-xl bg-[#0b0d12] text-sm text-white/50">
      3D 模型加载中…
    </div>
  )
});

/** 进度条（无外部依赖）：null 值渲染 0%，但标签显示 "-"。 */
function Bar({ value, label, tone = "blue" }) {
  const pct = toNumber(value);
  const clamped = pct === null ? 0 : Math.max(0, Math.min(100, pct));
  return (
    <div
      className="h-2 w-full overflow-hidden rounded-full bg-black/[0.08] dark:bg-white/15"
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(clamped)}
      aria-label={label}
    >
      <div
        className={`h-full rounded-full transition-[width] duration-500 ${tone === "green" ? "bg-[#34c759]" : "bg-[#0071e3]"}`}
        style={{ width: `${clamped}%` }}
      />
    </div>
  );
}

/** 指标小块：标签 + 主值 + 可选补充说明。 */
function Metric({ label, value, hint, valueClassName = "" }) {
  return (
    <div className="min-w-0 rounded-xl bg-[#f5f5f7] p-3 dark:bg-white/5">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`mt-1 break-words text-sm font-medium ${valueClassName}`}>{value ?? "-"}</div>
      {hint ? <div className="mt-1 break-words text-xs text-muted-foreground">{hint}</div> : null}
    </div>
  );
}

/** 温度块：接近目标（差值 < 5℃）时变绿，并标注「已达标」。 */
function TempMetric({ label, current, target }) {
  const t = formatTempPair(current, target);
  const targetAbsent = t.target === null || t.target <= 0;
  return (
    <div className="min-w-0 rounded-xl bg-[#f5f5f7] p-3 dark:bg-white/5">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-muted-foreground">{label}</span>
        {t.reached ? (
          <Badge variant="success" className="shrink-0">
            已达标
          </Badge>
        ) : targetAbsent ? (
          <Badge variant="outline" className="shrink-0">
            未加热
          </Badge>
        ) : null}
      </div>
      <div
        className={`mt-1 font-mono text-lg font-semibold tabular-nums ${
          t.reached ? "text-[#248a3d] dark:text-[#30d158]" : "text-foreground"
        }`}
      >
        {t.text}
      </div>
      <div className="mt-1 text-xs text-muted-foreground">
        {t.current === null && t.target === null ? "设备未上报温度" : t.reached ? "温度已稳定在目标附近" : "差距 ≥ 5℃，仍在升温/降温"}
      </div>
    </div>
  );
}

/** 灯光：`{"chamber_light":"on"}` → 开 / 关 / 闪烁。 */
function ledText(mode) {
  const key = String(mode || "").toLowerCase();
  if (key === "on") return "开";
  if (key === "off") return "关";
  if (key === "flashing") return "闪烁";
  return "-";
}

/**
 * 实时数据面板（Tab 1）。
 *
 * 上半部分是 3D 占位卡（后续替换数据面板区域时只动这里），
 * 下半部分是归一化状态的可读视图。所有字段都可能为 null，一律兜底为 "-"。
 */
export function DetailRealtimePanel({ liveState, eventMeta, layerIndex = null, layerSource = null }) {
  const state = liveState && typeof liveState === "object" ? liveState : null;
  const hasData = Boolean(state);

  const gcodeState = state?.gcode_state ?? null;
  const progress = toNumber(state?.progress);
  const layerNum = toNumber(state?.layer_num);
  const totalLayer = toNumber(state?.total_layer_num);
  const layerPct = layerNum !== null && totalLayer !== null && totalLayer > 0 ? (layerNum / totalLayer) * 100 : null;

  const lights = state?.lights && typeof state.lights === "object" ? state.lights : null;
  const trayNow = state?.tray_now ?? null;
  const trayTar = state?.tray_tar ?? null;
  const trays = Array.isArray(state?.ams_trays) ? state.ams_trays.filter((t) => t && typeof t === "object") : [];

  const spdLvl = toNumber(state?.spd_lvl);
  const spdMag = toNumber(state?.spd_mag);
  const stage = toNumber(state?.mc_print_stage);

  return (
    <div className="space-y-4">
      {/* —— 数字孪生：参数化 A1 模型，随实时状态联动 —— */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">数字孪生</CardTitle>
          <CardDescription>
            按 A1 真实规格建模：喷嘴/热床随温度变色，打印件随层数生长，风扇转速、腔灯与 4 个料卷实时联动。
          </CardDescription>
        </CardHeader>
        <CardContent>
          <TwinView state={state} layerIndex={layerIndex} />
          <p className="mt-2 text-xs text-muted-foreground">
            {layerIndex
              ? `喷嘴位置来自 G-code 层索引（${layerIndex.count} 层${layerSource ? ` · ${layerSource}` : ""}），层内为匀速插值。`
              : "未匹配到合盘产物，喷嘴位置为估算摆动。合盘并下发后会自动使用层索引。"}
          </p>
          {state?.hms?.length ? (
            <p className="mt-1 text-xs text-[#ff3b30]">
              故障定位：底座=主板 · 立柱/横梁/热床=运动系统 · 料卷=AMS（未识别模块号时整机脉冲）
            </p>
          ) : null}
        </CardContent>
      </Card>

      {!hasData ? (
        <Card>
          <CardHeader>
            <CardTitle>等待打印机上报</CardTitle>
            <CardDescription>
              还没有收到这台设备的归一化事件。请确认打印机已开机、局域网 MQTT 已连通，稍后会自动刷新。
            </CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <>
          {/* —— 打印状态 —— */}
          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <CardTitle>打印状态</CardTitle>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={gcodeStateVariant(gcodeState)}>{formatGcodeState(gcodeState)}</Badge>
                  {eventMeta?.occurredAt ? (
                    <span className="text-xs text-muted-foreground">上报：{formatDateTime(eventMeta.occurredAt)}</span>
                  ) : null}
                </div>
              </div>
              <CardDescription className="break-all">
                任务：{state?.subtask_name || state?.gcode_file || "-"}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">总进度</span>
                  <span className="font-mono tabular-nums">{progress === null ? "-" : `${Math.round(progress)}%`}</span>
                </div>
                <Bar value={progress} label="打印总进度" />
              </div>

              <div className="space-y-2">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">层数</span>
                  <span className="font-mono tabular-nums">
                    {layerNum === null && totalLayer === null
                      ? "-"
                      : `第 ${layerNum ?? "-"} / ${totalLayer ?? "-"} 层`}
                  </span>
                </div>
                <Bar value={layerPct} label="层进度" tone="green" />
              </div>

              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <Metric
                  label="速度档位"
                  value={spdLvl === null ? "-" : `${spdLvl} 档 · ${speedLevelLabel(spdLvl)}`}
                  hint={spdMag === null ? null : `倍率 ${spdMag}`}
                />
                <Metric
                  label="阶段码（mc_print_stage）"
                  value={stage === null ? "-" : String(stage)}
                  hint="后端暂无 78 态映射表，此处显示原始数字"
                />
                <Metric label="当前槽位" value={formatTraySlot(trayNow)} hint="AMS 换料来源" />
                <Metric label="目标槽位" value={formatTraySlot(trayTar)} hint="换料目标" />
              </div>
            </CardContent>
          </Card>

          {/* —— 温度 —— */}
          <Card>
            <CardHeader>
              <CardTitle>温度</CardTitle>
              <CardDescription>「当前 → 目标」，差值小于 5℃ 视为已达温。</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                <TempMetric label="喷嘴" current={state?.nozzle_temper} target={state?.nozzle_target_temper} />
                <TempMetric label="热床" current={state?.bed_temper} target={state?.bed_target_temper} />
                {toNumber(state?.chamber_temper) === null ? null : (
                  <div className="min-w-0 rounded-xl bg-[#f5f5f7] p-3 dark:bg-white/5">
                    <div className="text-xs text-muted-foreground">腔体温度</div>
                    <div className="mt-1 font-mono text-lg font-semibold tabular-nums">
                      {toNumber(state.chamber_temper).toFixed(1)} ℃
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">仅在有腔温传感器时上报</div>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>

          {/* —— 风扇 / 灯光 —— */}
          <Card>
            <CardHeader>
              <CardTitle>风扇与灯光</CardTitle>
              <CardDescription>风扇若回传 0-255 原始值，会换算成百分比并保留原始值。</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <Metric
                  label="模型冷却风扇"
                  value={describeFan(state?.cooling_fan_speed).text}
                  hint="cooling_fan_speed"
                />
                <Metric label="机箱风扇" value={describeFan(state?.big_fan1_speed).text} hint="big_fan1_speed" />
                <Metric
                  label="喉管风扇"
                  value={describeFan(state?.heatbreak_fan_speed).text}
                  hint="heatbreak_fan_speed"
                />
                <Metric
                  label="腔灯"
                  value={ledText(lights?.chamber_light)}
                  hint={lights?.work_light ? `工作灯：${ledText(lights.work_light)}` : "lights.chamber_light"}
                />
              </div>
            </CardContent>
          </Card>

          {/* —— AMS 槽位 —— */}
          <Card>
            <CardHeader>
              <CardTitle>AMS 槽位</CardTitle>
              <CardDescription>
                颜色为固件 `RRGGBBAA`，此处转成 `#RRGGBB`；余量 ≤ 1 视为比例、≤ 100 视为百分比。
              </CardDescription>
            </CardHeader>
            <CardContent>
              {trays.length === 0 ? (
                <p className="text-sm text-muted-foreground">设备未上报 AMS 槽位（可能未装 AMS 或为空槽）。</p>
              ) : (
                <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  {trays.map((tray, idx) => {
                    const trayId = tray?.id ?? idx;
                    const colorHex = normalizeColorHex(tray?.color);
                    const remainPct = normalizeRemainPct(tray?.remain);
                    const isActive = trayNow !== null && Number(trayNow) === Number(trayId);
                    return (
                      <li
                        key={`${trayId}-${idx}`}
                        className={`min-w-0 rounded-xl border p-3 ${
                          isActive
                            ? "border-[#0071e3]/40 bg-[#0071e3]/[0.06] dark:border-[#0a84ff]/40 dark:bg-[#0a84ff]/10"
                            : "border-black/[0.06] bg-white dark:border-white/10 dark:bg-white/5"
                        }`}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-sm font-medium">托盘 {trayId}</span>
                          {isActive ? <Badge variant="info">使用中</Badge> : null}
                        </div>
                        <div className="mt-2 flex items-center gap-2">
                          <span
                            className="h-6 w-6 shrink-0 rounded border border-black/10 dark:border-white/20"
                            style={{ backgroundColor: colorHex || "#cccccc" }}
                            aria-label={`托盘 ${trayId} 颜色`}
                            title={colorHex || String(tray?.color || "未知颜色")}
                          />
                          <span className="min-w-0 break-all text-xs text-muted-foreground">
                            {colorHex || (tray?.color ? String(tray.color) : "未知颜色")}
                          </span>
                        </div>
                        <div className="mt-2 text-sm">{tray?.type || "材质未知"}</div>
                        <div className="mt-1 text-xs text-muted-foreground">
                          余量：{remainPct === null ? (tray?.remain === undefined || tray?.remain === null ? "-" : String(tray.remain)) : `${Math.round(remainPct)}%`}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
