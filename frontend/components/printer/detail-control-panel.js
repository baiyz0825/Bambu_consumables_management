"use client";

import { useState } from "react";
import { toast } from "sonner";

import {
  CALIBRATION_BITS,
  SPEED_LEVELS,
  amsChange,
  calibrate,
  describeBitmask,
  describeControlError,
  extrudeFilament,
  formatTempPair,
  homeAxes,
  motionLockedReason,
  moveAxis,
  pausePrint,
  resumePrint,
  sendGcode,
  setBedTemp,
  setLed,
  setNozzleTemp,
  setSpeedLevel,
  speedLevelLabel,
  stopPrint,
  toNumber
} from "../../lib/printer-control-api";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "../ui/dialog";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { NativeSelect } from "../ui/native-select";

/** 后端 G-code 白名单（与 bambu_protocol.ALLOWED_GCODE 保持一致，仅用于提示）。 */
const ALLOWED_GCODE_HINT = "G28 / G0 / G1 / G90 / G91 / G92 / M82 / M83 / M104 / M106 / M107 / M117 / M140 / M220 / M221 / M900";

/** 错误类型 → 视觉形态：409（状态冲突）与 502（打印机不可达）必须一眼分清。 */
const ERROR_TONE = {
  conflict: {
    box: "border-[#ff9500]/50 bg-[#ff9500]/[0.08]",
    badge: "warning",
    badgeText: "状态冲突 409"
  },
  unreachable: {
    box: "border-destructive/50 bg-destructive/[0.06]",
    badge: "destructive",
    badgeText: "打印机不可达 502"
  },
  invalid: {
    box: "border-black/10 bg-black/[0.03] dark:border-white/15 dark:bg-white/5",
    badge: "outline",
    badgeText: "输入/参数不合法"
  },
  notfound: {
    box: "border-destructive/50 bg-destructive/[0.06]",
    badge: "destructive",
    badgeText: "设备不存在 404"
  },
  unknown: {
    box: "border-black/10 bg-black/[0.03] dark:border-white/15 dark:bg-white/5",
    badge: "outline",
    badgeText: "操作失败"
  }
};

function toneOf(kind) {
  return ERROR_TONE[kind] || ERROR_TONE.unknown;
}

/** 小节标题：统一「标题 + 说明 + 右侧内容」，避免每个卡片重复写 flex。 */
function Section({ title, description, children, locked = false, lockedText = "" }) {
  return (
    <div className={`rounded-xl border p-3 ${locked ? "border-[#ff9500]/40 bg-[#ff9500]/[0.05]" : "border-black/[0.06] dark:border-white/10"}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-sm font-semibold">{title}</div>
          {description ? <div className="mt-1 text-xs text-muted-foreground">{description}</div> : null}
        </div>
        {locked ? (
          <Badge variant="warning" className="shrink-0">
            已禁用
          </Badge>
        ) : null}
      </div>
      {locked && lockedText ? <div className="mt-2 text-xs text-[#8a5a00] dark:text-[#ffb340]">{lockedText}</div> : null}
      <div className="mt-3">{children}</div>
    </div>
  );
}

/**
 * 设备控制面板（Tab 2）。
 *
 * 设计要点：
 *
 * - **提前拦截**：打印中（RUNNING / PREPARE）时，运动类控件直接禁用并显示原因，
 *   不等后端 409 —— 让用户少点一次、少看一次报错；
 * - **错误可分辨**：409 / 502 / 400 用不同配色与文案（见 ERROR_TONE），
 *   成功/失败都有 toast，且失败时优先展示后端返回的中文 `detail`；
 * - **loading 可见**：所有下发按钮在请求期间进入「下发中…」并禁用，避免重复下发。
 */
export function DetailControlPanel({ printerId, liveState, onRefresh }) {
  const [pending, setPending] = useState(null);
  const [lastError, setLastError] = useState(null);
  const [stopOpen, setStopOpen] = useState(false);

  // 温度
  const [tempMode, setTempMode] = useState("nozzle");
  const [tempValue, setTempValue] = useState("");

  // 轴移动
  const [axis, setAxis] = useState("X");
  const [moveDistance, setMoveDistance] = useState("10");
  const [moveSpeed, setMoveSpeed] = useState("3000");

  // 挤出 / 退料
  const [extrudeValue, setExtrudeValue] = useState("10");

  // AMS 换料
  const [amsTarget, setAmsTarget] = useState("0");

  // 校准位掩码
  const [mask, setMask] = useState(1);

  // G-code
  const [gcode, setGcode] = useState("");

  const busy = pending !== null;

  const gcodeState = liveState?.gcode_state ?? null;
  const lockReason = motionLockedReason(gcodeState);
  const motionLocked = Boolean(lockReason);

  const currentSpeed = toNumber(liveState?.spd_lvl);
  const chamberLightMode = String(liveState?.lights?.chamber_light || "").toLowerCase();
  const lightOn = chamberLightMode === "on";
  const lightKnown = chamberLightMode === "on" || chamberLightMode === "off" || chamberLightMode === "flashing";

  const tempPair =
    tempMode === "nozzle"
      ? formatTempPair(liveState?.nozzle_temper, liveState?.nozzle_target_temper)
      : formatTempPair(liveState?.bed_temper, liveState?.bed_target_temper);

  /** 统一的下发流程：loading → 成功 toast / 失败 toast，成功后触发一次状态刷新。 */
  async function run(key, fn, okMessage) {
    if (!printerId || busy) return false;
    setPending(key);
    setLastError(null);
    try {
      const res = await fn();
      const detail = res && typeof res.detail === "string" && res.detail.trim() ? res.detail.trim() : null;
      toast.success(detail || okMessage);
      if (typeof onRefresh === "function") onRefresh();
      return true;
    } catch (err) {
      const info = describeControlError(err);
      setLastError(info);
      // 409 用 warning（可恢复的时序问题），其余用 error（真失败）
      if (info.kind === "conflict") toast.warning(info.message, { description: info.title });
      else toast.error(info.message, { description: info.title });
      return false;
    } finally {
      setPending(null);
    }
  }

  /** 前端本地校验失败：不发请求，直接提示（避免把可预判的错误丢给后端）。 */
  function rejectLocal(message) {
    const info = { status: 0, kind: "invalid", title: "输入有误", message };
    setLastError(info);
    toast.error(message, { description: "输入有误" });
  }

  // —— 各动作的提交函数（校验 → 下发）——

  function submitTemp() {
    const value = toNumber(tempValue);
    const limit = tempMode === "nozzle" ? 300 : 120;
    const label = tempMode === "nozzle" ? "喷嘴" : "热床";
    if (value === null || !Number.isInteger(value) || value < 0) {
      rejectLocal(`请输入 0-${limit} 之间的整数温度`);
      return;
    }
    if (value > limit) {
      rejectLocal(`${label}目标温度 ${value} ℃ 超过安全上限 ${limit} ℃`);
      return;
    }
    run(
      "temp",
      () => (tempMode === "nozzle" ? setNozzleTemp(printerId, value) : setBedTemp(printerId, value)),
      `已下发 ${label}目标温度 ${value} ℃`
    );
  }

  function submitMove() {
    const distance = toNumber(moveDistance);
    const speed = toNumber(moveSpeed);
    if (distance === null || distance === 0) {
      rejectLocal("移动距离不能为 0");
      return;
    }
    if (Math.abs(distance) > 200) {
      rejectLocal("单次移动不能超过 200 mm");
      return;
    }
    if (speed !== null && (speed < 60 || speed > 12000)) {
      rejectLocal("移动速度需在 60-12000 mm/min 之间（留空则用默认 3000）");
      return;
    }
    run("move", () => moveAxis(printerId, { axis, distance, speed }), `已下发移动 ${axis}${distance}mm`);
  }

  function submitExtrude() {
    const distance = toNumber(extrudeValue);
    if (distance === null || distance === 0) {
      rejectLocal("挤出长度不能为 0（正数进料、负数退料）");
      return;
    }
    if (Math.abs(distance) > 100) {
      rejectLocal("单次挤出不能超过 100 mm");
      return;
    }
    run("extrude", () => extrudeFilament(printerId, distance), `已下发挤出 ${distance}mm`);
  }

  function submitCalibrate() {
    const value = toNumber(mask);
    if (value === null || !Number.isInteger(value) || value < 1 || value > 15) {
      rejectLocal("校准位掩码需为 1-15 的整数");
      return;
    }
    run("calibrate", () => calibrate(printerId, value), `已下发校准（${describeBitmask(value)}）`);
  }

  function submitGcode() {
    const line = String(gcode || "").trim();
    if (!line) {
      rejectLocal("请输入一条 G-code");
      return;
    }
    if (line.includes("\n") || line.includes("\r")) {
      rejectLocal("只允许单行 G-code，禁止一次提交多条指令");
      return;
    }
    run("gcode", () => sendGcode(printerId, line), `已下发 G-code：${line.split(/\s+/)[0].toUpperCase()}`);
  }

  const errorTone = lastError ? toneOf(lastError.kind) : null;

  return (
    <div className="space-y-4">
      {/* —— 顶部：错误横幅（409/502 视觉可区分）—— */}
      {lastError && errorTone ? (
        <div
          className={`flex flex-wrap items-start justify-between gap-2 rounded-xl border p-3 ${errorTone.box}`}
          role="alert"
        >
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={errorTone.badge}>{errorTone.badgeText}</Badge>
              <span className="text-sm font-medium">{lastError.title}</span>
            </div>
            <p className="mt-1 break-words text-sm text-muted-foreground">{lastError.message}</p>
          </div>
          <Button variant="ghost" size="sm" onClick={() => setLastError(null)}>
            清除
          </Button>
        </div>
      ) : null}

      {/* —— 打印流程 —— */}
      <Card>
        <CardHeader>
          <CardTitle>打印流程</CardTitle>
          <CardDescription>
            暂停 / 恢复可反复下发；停止会中断当前任务且不可恢复，需二次确认。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-2">
            <Button
              onClick={() => run("pause", () => pausePrint(printerId), "暂停命令已下发")}
              disabled={busy}
            >
              {pending === "pause" ? "下发中…" : "暂停"}
            </Button>
            <Button
              variant="outline"
              onClick={() => run("resume", () => resumePrint(printerId), "恢复命令已下发")}
              disabled={busy}
            >
              {pending === "resume" ? "下发中…" : "恢复"}
            </Button>
            <Button variant="destructive" onClick={() => setStopOpen(true)} disabled={busy}>
              停止打印
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            当前状态：{gcodeState ? String(gcodeState).toUpperCase() : "-"}
          </p>
        </CardContent>
      </Card>

      {/* —— 速度档位 —— */}
      <Card>
        <CardHeader>
          <CardTitle>速度档位</CardTitle>
          <CardDescription>
            1=静音 2=标准 3=运动 4=狂暴；高亮来自实时数据 spd_lvl，点击即刻下发。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {SPEED_LEVELS.map((item) => {
              const active = currentSpeed === item.level;
              return (
                <Button
                  key={item.level}
                  variant={active ? "default" : "outline"}
                  onClick={() => run(`speed-${item.level}`, () => setSpeedLevel(printerId, item.level), `已切换到 ${item.level} 档（${item.label}）`)}
                  disabled={busy}
                  aria-pressed={active}
                >
                  {pending === `speed-${item.level}` ? "下发中…" : `${item.level} 档 · ${item.label}`}
                </Button>
              );
            })}
          </div>
          <p className="text-xs text-muted-foreground">
            当前：{currentSpeed === null ? "-" : `${currentSpeed} 档 · ${speedLevelLabel(currentSpeed)}`}
          </p>
        </CardContent>
      </Card>

      {/* —— 灯光 —— */}
      <Card>
        <CardHeader>
          <CardTitle>腔灯</CardTitle>
          <CardDescription>对应 lights.chamber_light；开/关为幂等命令。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant={lightOn ? "default" : "outline"}
              onClick={() => run("led-on", () => setLed(printerId, { node: "chamber_light", mode: "on" }), "已下发开灯")}
              disabled={busy}
              aria-pressed={lightOn}
            >
              {pending === "led-on" ? "下发中…" : "开灯"}
            </Button>
            <Button
              variant={lightKnown && !lightOn ? "default" : "outline"}
              onClick={() => run("led-off", () => setLed(printerId, { node: "chamber_light", mode: "off" }), "已下发关灯")}
              disabled={busy}
              aria-pressed={lightKnown && !lightOn}
            >
              {pending === "led-off" ? "下发中…" : "关灯"}
            </Button>
            <Badge variant="outline">
              当前：{lightOn ? "开" : chamberLightMode === "off" ? "关" : chamberLightMode === "flashing" ? "闪烁" : "未上报"}
            </Badge>
          </div>
        </CardContent>
      </Card>

      {/* —— 温度设置（走 gcode：M104 / M140）—— */}
      <Card>
        <CardHeader>
          <CardTitle>温度设置</CardTitle>
          <CardDescription>
            通过 G-code 白名单端点下发：喷嘴用 M104、热床用 M140，温度作为 S 参数；上限 300℃ / 120℃。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="grid gap-2">
              <Label htmlFor="temp-mode">加热部位</Label>
              <NativeSelect
                id="temp-mode"
                value={tempMode}
                onChange={(e) => setTempMode(e.target.value)}
                disabled={busy}
              >
                <option value="nozzle">喷嘴</option>
                <option value="bed">热床</option>
              </NativeSelect>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="temp-value">目标温度（℃）</Label>
              <Input
                id="temp-value"
                type="number"
                inputMode="numeric"
                min={0}
                max={tempMode === "nozzle" ? 300 : 120}
                step={1}
                placeholder={tempMode === "nozzle" ? "例如 220" : "例如 60"}
                value={tempValue}
                onChange={(e) => setTempValue(e.target.value)}
                disabled={busy}
              />
            </div>
            <div className="flex items-end">
              <Button className="w-full" onClick={submitTemp} disabled={busy}>
                {pending === "temp" ? "下发中…" : "提交温度"}
              </Button>
            </div>
          </div>
          <p className="text-xs text-muted-foreground">
            当前：{tempMode === "nozzle" ? "喷嘴" : "热床"} {tempPair.text}
            {tempPair.reached ? "（已达标）" : ""}
          </p>
        </CardContent>
      </Card>

      {/* —— 运动控制（打印中整体锁定）—— */}
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle>运动控制</CardTitle>
            {motionLocked ? <Badge variant="warning">打印中已锁定</Badge> : null}
          </div>
          <CardDescription>
            轴移动 / 回零 / 挤出都会带动机器动作，打印中（RUNNING、PREPARE）前端直接禁用，后端同样会返回 409。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {motionLocked ? (
            <div
              className="flex items-start gap-2 rounded-xl border border-[#ff9500]/50 bg-[#ff9500]/[0.08] p-3 text-xs"
              role="note"
            >
              <Badge variant="warning" className="shrink-0">
                原因
              </Badge>
              <span className="leading-relaxed">{lockReason}</span>
            </div>
          ) : null}

          {/* 轴移动 */}
          <Section
            title="轴移动"
            description="相对移动，单次上限 200mm；速度为 mm/min（60-12000）。"
            locked={motionLocked}
            lockedText="打印中禁止运动控制"
          >
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
              <div className="grid gap-2">
                <Label htmlFor="move-axis">轴</Label>
                <NativeSelect
                  id="move-axis"
                  value={axis}
                  onChange={(e) => setAxis(e.target.value)}
                  disabled={busy || motionLocked}
                >
                  <option value="X">X</option>
                  <option value="Y">Y</option>
                  <option value="Z">Z</option>
                </NativeSelect>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="move-distance">距离（mm）</Label>
                <Input
                  id="move-distance"
                  type="number"
                  inputMode="decimal"
                  min={-200}
                  max={200}
                  step={1}
                  placeholder="-200 ~ 200"
                  value={moveDistance}
                  onChange={(e) => setMoveDistance(e.target.value)}
                  disabled={busy || motionLocked}
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="move-speed">速度（mm/min）</Label>
                <Input
                  id="move-speed"
                  type="number"
                  inputMode="numeric"
                  min={60}
                  max={12000}
                  step={100}
                  placeholder="默认 3000"
                  value={moveSpeed}
                  onChange={(e) => setMoveSpeed(e.target.value)}
                  disabled={busy || motionLocked}
                />
              </div>
              <div className="flex items-end">
                <Button className="w-full" variant="outline" onClick={submitMove} disabled={busy || motionLocked}>
                  {pending === "move" ? "下发中…" : "移动"}
                </Button>
              </div>
            </div>
          </Section>

          {/* 回零 */}
          <Section
            title="回零"
            description="G28；全轴或单轴回零，回零期间请清空打印平台周边。"
            locked={motionLocked}
            lockedText="打印中禁止运动控制"
          >
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                onClick={() => run("home-xyz", () => homeAxes(printerId, "XYZ"), "已下发全轴回零")}
                disabled={busy || motionLocked}
              >
                {pending === "home-xyz" ? "下发中…" : "全轴 XYZ"}
              </Button>
              {["X", "Y", "Z"].map((a) => (
                <Button
                  key={a}
                  variant="outline"
                  onClick={() => run(`home-${a}`, () => homeAxes(printerId, a), `已下发 ${a} 轴回零`)}
                  disabled={busy || motionLocked}
                >
                  {pending === `home-${a}` ? "下发中…" : `${a} 轴`}
                </Button>
              ))}
            </div>
          </Section>

          {/* 挤出 / 退料 */}
          <Section
            title="挤出 / 退料"
            description="正数进料、负数退料，单次上限 100mm；需喷嘴已加热，否则固件会冷挤出保护。"
            locked={motionLocked}
            lockedText="打印中禁止运动控制"
          >
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <div className="grid gap-2 sm:col-span-2">
                <Label htmlFor="extrude-distance">长度（mm，正进负退）</Label>
                <Input
                  id="extrude-distance"
                  type="number"
                  inputMode="decimal"
                  min={-100}
                  max={100}
                  step={1}
                  placeholder="例如 10 或 -10"
                  value={extrudeValue}
                  onChange={(e) => setExtrudeValue(e.target.value)}
                  disabled={busy || motionLocked}
                />
              </div>
              <div className="flex items-end">
                <Button className="w-full" variant="outline" onClick={submitExtrude} disabled={busy || motionLocked}>
                  {pending === "extrude" ? "下发中…" : "执行"}
                </Button>
              </div>
            </div>
          </Section>
        </CardContent>
      </Card>

      {/* —— AMS 换料 —— */}
      <Card>
        <CardHeader>
          <CardTitle>AMS 换料</CardTitle>
          <CardDescription>目标槽位：0-3 为 AMS 四槽，254 / 255 为外挂料盘。</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="grid gap-2 sm:col-span-2">
              <Label htmlFor="ams-target">目标槽位</Label>
              <NativeSelect
                id="ams-target"
                value={amsTarget}
                onChange={(e) => setAmsTarget(e.target.value)}
                disabled={busy}
              >
                <option value="0">槽位 0</option>
                <option value="1">槽位 1</option>
                <option value="2">槽位 2</option>
                <option value="3">槽位 3</option>
                <option value="254">外挂料盘 254</option>
                <option value="255">外挂料盘 255</option>
              </NativeSelect>
            </div>
            <div className="flex items-end">
              <Button
                className="w-full"
                variant="outline"
                onClick={() => run("ams", () => amsChange(printerId, Number(amsTarget)), `已下发 AMS 切换到 ${amsTarget}`)}
                disabled={busy}
              >
                {pending === "ams" ? "下发中…" : "切换槽位"}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* —— 校准 —— */}
      <Card>
        <CardHeader>
          <CardTitle>校准</CardTitle>
          <CardDescription>位掩码按位或：1=调平 2=震动 4=流量 8=电机噪音（合法范围 1-15）。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-2">
            {CALIBRATION_BITS.map((item) => {
              const active = (mask & item.bit) !== 0;
              return (
                <Button
                  key={item.bit}
                  size="sm"
                  variant={active ? "default" : "outline"}
                  aria-pressed={active}
                  onClick={() => setMask((prev) => (Number(prev) || 0) ^ item.bit)}
                  disabled={busy}
                >
                  {item.label}（{item.bit}）
                </Button>
              );
            })}
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="grid gap-2">
              <Label htmlFor="calibrate-mask">位掩码</Label>
              <Input
                id="calibrate-mask"
                type="number"
                inputMode="numeric"
                min={1}
                max={15}
                step={1}
                value={mask}
                onChange={(e) => setMask(e.target.value === "" ? 0 : Number(e.target.value))}
                disabled={busy}
              />
            </div>
            <div className="flex items-end text-xs text-muted-foreground sm:col-span-1">
              当前组合：{describeBitmask(mask)}
            </div>
            <div className="flex items-end">
              <Button className="w-full" variant="outline" onClick={submitCalibrate} disabled={busy}>
                {pending === "calibrate" ? "下发中…" : "开始校准"}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* —— G-code —— */}
      <Card>
        <CardHeader>
          <CardTitle>G-code</CardTitle>
          <CardDescription>仅白名单指令会被后端放行；一次只允许一行。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="grid gap-2 sm:col-span-2">
              <Label htmlFor="gcode-line">指令</Label>
              <Input
                id="gcode-line"
                placeholder="例如 M104 S200"
                value={gcode}
                onChange={(e) => setGcode(e.target.value)}
                disabled={busy}
                autoComplete="off"
                spellCheck={false}
              />
            </div>
            <div className="flex items-end">
              <Button className="w-full" onClick={submitGcode} disabled={busy}>
                {pending === "gcode" ? "下发中…" : "下发"}
              </Button>
            </div>
          </div>
          <p className="break-words text-xs text-muted-foreground">白名单：{ALLOWED_GCODE_HINT}</p>
        </CardContent>
      </Card>

      {/* —— 停止打印二次确认（不可恢复）—— */}
      <Dialog open={stopOpen} onOpenChange={setStopOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>确认停止打印？</DialogTitle>
            <DialogDescription>
              停止命令不可恢复：当前任务会被立即中断，已打印部分无法继续。请确认平台上没有需要保留的成品。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setStopOpen(false)} disabled={pending === "stop"}>
              取消
            </Button>
            <Button
              variant="destructive"
              disabled={pending === "stop"}
              onClick={async () => {
                const ok = await run("stop", () => stopPrint(printerId), "停止命令已下发");
                if (ok) setStopOpen(false);
              }}
            >
              {pending === "stop" ? "下发中…" : "确认停止"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
