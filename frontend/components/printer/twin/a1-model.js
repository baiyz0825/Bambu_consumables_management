"use client";

/**
 * Bambu Lab A1 参数化数字孪生模型。
 *
 * 结构依据（对照实机照片）：
 * - A1 是**双立柱门式（gantry）**结构，不是 A1 mini 那种单柱悬臂；
 * - 两根立柱在左右靠后，顶部横梁连接，横梁整体沿 Z 升降，喷头沿横梁走 X；
 * - 热床在底座上方前后移动（Y）；
 * - AMS lite 是**独立落地支架**，4 个料盘竖直悬挂、2 列 × 2 行，每个料盘上方有进料器。
 *
 * 坐标约定（mm）：
 *   three.x = 打印 X（左右）
 *   three.y = 打印 Z（高度，y=0 为床面）
 *   three.z = -打印 Y（热床前后；+z 朝向观察者）
 *
 * 尺寸来源：A1 公开规格 —— 打印体积 256³，机身 385×410×430。
 */

import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";

const PRINT_VOLUME = 256;

const BASE = { w: 385, h: 62, d: 410 };
const POST = { w: 52, h: 420, d: 52, x: 168, z: -175 };
const BEAM = { w: 384, h: 34, d: 40 };
const BED_FRAME = { w: 300, h: 14, d: 300 };
const BED_PLATE = { w: 256, h: 8, d: 256 };
const TOOL = { w: 74, h: 92, d: 56 };

//: 料盘（AMS lite）：盘片用带孔环片，正面能看到线材，而不是实心圆
const COIL = { outer: 90, wire: 72, thickness: 44 };

//: 横梁中心相对当前层高的偏移量，使喷嘴尖端恰好落在层高上。
//: 推导：喷头中心 = 层高 + TOOL.h/2 + 30（喷嘴伸出 30），
//: 横梁 = 喷头中心 + TOOL.h/2 + BEAM.h/2 = 层高 + 92 + 17 + 30 = 层高 + 139
const GANTRY_OFFSET = TOOL.h + BEAM.h / 2 + 30;

//: Bambu 的床坐标原点在床角（0..256），模型以床中心为原点
const BED_CENTER = 128;

const COLORS = {
  base: "#eceef2",
  post: "#c6ccd4",
  beam: "#cfd4db",
  bedFrame: "#2a2d32",
  bedPlate: "#23262b",
  tool: "#f1f3f6",
  toolDark: "#3c4149",
  screen: "#0a0c0f",
  accent: "#0071e3",
  amsFrame: "#c3c8d0",
  coilSide: "#4b5058",
  metal: "#9aa1aa"
};

const COLD = new THREE.Color("#5d6470");
const WARM = new THREE.Color("#ff8a3d");
const HOT = new THREE.Color("#ff3b30");

const _color = new THREE.Color();

/** 把温度映射成「冷灰 → 橙 → 红」。 */
function heatColor(celsius) {
  const c = Math.max(0, Math.min(280, Number(celsius) || 0));
  const t = c / 280;
  if (t < 0.5) return _color.copy(COLD).lerp(WARM, t / 0.5);
  return _color.copy(WARM).lerp(HOT, (t - 0.5) / 0.5);
}

function num(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

/** RRGGBBAA → #RRGGBB */
function trayColor(value, fallback = "#8e8e93") {
  if (typeof value !== "string") return fallback;
  const s = value.trim().replace(/^#/, "");
  return s.length >= 6 ? `#${s.slice(0, 6)}` : fallback;
}

function damp(current, target, lambda, dt) {
  return THREE.MathUtils.damp(current, target, lambda, dt);
}

export function A1Model({ state, layerIndex = null }) {
  const gantryRef = useRef(null);
  const toolRef = useRef(null);
  const bedRef = useRef(null);
  const partRef = useRef(null);
  const fanRef = useRef(null);
  const lampRef = useRef(null);
  const nozzleMatRef = useRef(null);
  const bedMatRef = useRef(null);
  const frameMatRef = useRef(null);
  const columnMats = useRef([]);
  const beamMatRef = useRef(null);
  const toolMatRef = useRef(null);
  const coilRefs = useRef([]);
  const partHRef = useRef(0);

  const targets = useMemo(
    () => ({ toolY: 40, toolX: 0, bedZ: 0, partH: 0, fan: 0, lamp: 0 }),
    []
  );

  const trays = Array.isArray(state?.ams_trays) ? state.ams_trays.slice(0, 4) : [];
  const trayColors = [0, 1, 2, 3].map((i) => trayColor(trays[i]?.color));
  // 料卷原始自发光色：故障脉冲结束后要能恢复
  const coilBase = trayColors.map((color) => new THREE.Color(color));

  const trayNowNum = num(state?.tray_now);
  const activeTray = trayNowNum !== null && trayNowNum >= 0 && trayNowNum < 4 ? trayNowNum : 0;

  // 层索引：rows[n] = [z, xMin, xMax, yMin, yMax]
  const layerRows = layerIndex?.layers ?? null;

  // 打印件占地用层索引的总体 bbox，比固定方块更接近真实投影
  const bbox = layerIndex?.bbox;
  const partW = bbox ? Math.max(40, Math.min(150, bbox[1] - bbox[0])) : 140;
  const partD = bbox ? Math.max(40, Math.min(150, bbox[3] - bbox[2])) : 140;

  useFrame((_, delta) => {
    const dt = Math.min(delta, 0.05);
    const t = performance.now() / 1000;

    const running = state?.gcode_state === "RUNNING";
    const layer = num(state?.layer_num);
    const total = num(state?.total_layer_num);
    const progress = num(state?.progress);

    const ratio = layer !== null && total ? layer / total : (progress ?? 0) / 100;
    const clamped = Math.max(0, Math.min(1, ratio));

    // —— 目标位置 ——
    if (layerRows && layerRows.length > 0 && layer !== null) {
      const index = Math.max(1, Math.min(layerRows.length, Math.round(layer)));
      const row = layerRows[index - 1];
      const xMin = row[1];
      const xMax = row[2];
      const yMin = row[3];
      const yMax = row[4];
      // 层内没有逐条轨迹，按时间沿 bbox 对角线匀速插值（刻意取舍）
      const fraction = running ? (t * 0.35) % 1 : 0.5;
      const printX = xMin + (xMax - xMin) * fraction;
      const printY = yMin + (yMax - yMin) * fraction;

      targets.toolX = printX - BED_CENTER;
      targets.bedZ = -(printY - BED_CENTER);
      targets.toolY = row[0];
      targets.partH = row[0];
    } else {
      targets.toolY = 10 + clamped * (PRINT_VOLUME - 30);
      targets.toolX = running ? Math.sin(t * 1.15) * 82 : 0;
      targets.bedZ = running ? Math.sin(t * 0.72) * 54 : 0;
      targets.partH = clamped * 200;
    }

    // —— 阻尼跟随 ——
    if (gantryRef.current) {
      // 横梁中心比喷嘴尖端高 GANTRY_OFFSET，保证喷嘴落在当前层高
      gantryRef.current.position.y = damp(
        gantryRef.current.position.y,
        targets.toolY + GANTRY_OFFSET,
        6,
        dt
      );
    }
    if (toolRef.current) {
      toolRef.current.position.x = damp(toolRef.current.position.x, targets.toolX, 7, dt);
    }
    if (bedRef.current) {
      bedRef.current.position.z = damp(bedRef.current.position.z, targets.bedZ, 5, dt);
    }
    if (partRef.current) {
      const h = damp(partHRef.current, targets.partH, 5, dt);
      partHRef.current = h;
      const scaleY = Math.max(0.001, h / 200);
      partRef.current.scale.y = scaleY;
      partRef.current.position.y = (200 * scaleY) / 2;
    }

    // —— 温度颜色（喷嘴 / 热床）——
    const nozzleT = num(state?.nozzle_temper) ?? 0;
    const bedT = num(state?.bed_temper) ?? 0;
    const nozzleHeat = heatColor(nozzleT).clone();
    // 热床是黑色 PEI 板，60℃ 时视觉上只该"微微发暖"，不要渲染成通红
    const bedHeat = heatColor(bedT * 0.85).clone();
    if (nozzleMatRef.current) {
      nozzleMatRef.current.color.copy(nozzleHeat);
      nozzleMatRef.current.emissive.copy(nozzleHeat).multiplyScalar(0.3);
    }
    if (bedMatRef.current) {
      bedMatRef.current.emissive.copy(bedHeat).multiplyScalar(0.1);
    }

    // —— 风扇 ——
    const fanSpeed = num(state?.cooling_fan_speed) ?? 0;
    targets.fan = fanSpeed > 100 ? fanSpeed / 255 : fanSpeed / 100;
    if (fanRef.current) {
      fanRef.current.rotation.z += dt * targets.fan * 26;
    }

    // —— 腔灯 ——
    const lightOn = state?.lights?.chamber_light === "on";
    targets.lamp = lightOn ? 1.8 : 0;
    if (lampRef.current) {
      lampRef.current.intensity = damp(lampRef.current.intensity, targets.lamp, 8, dt);
    }

    // —— HMS 故障：按模块号定位部件 ——
    // ecode 前两位是模块号：03 运动控制 / 05 主板 / 07 AMS / 0C 视觉
    const hmsList = Array.isArray(state?.hms) ? state.hms : [];
    const modules = new Set(hmsList.map((item) => String(item?.module ?? "").toUpperCase()));
    const known = ["03", "05", "07"];
    const hasKnown = known.some((code) => modules.has(code));
    const allOn = hmsList.length > 0 && !hasKnown;
    const pulse = hmsList.length > 0 ? (Math.sin(t * 5) * 0.5 + 0.5) * 0.8 : 0;

    const paint = (material, active) => {
      if (!material) return;
      material.emissive.setRGB(active ? pulse : 0, 0, 0);
    };

    paint(frameMatRef.current, allOn || modules.has("05"));
    columnMats.current.forEach((material) => paint(material, allOn || modules.has("03")));
    paint(beamMatRef.current, allOn || modules.has("03"));
    paint(toolMatRef.current, allOn || modules.has("03") || modules.has("05"));

    const amsFault = allOn || modules.has("07");
    coilRefs.current.forEach((mat, index) => {
      if (!mat) return;
      const active = num(state?.tray_tar) === index;
      if (amsFault) {
        mat.emissive.setRGB(pulse, 0, 0);
        mat.emissiveIntensity = 1;
      } else {
        mat.emissive.copy(coilBase[index]);
        mat.emissiveIntensity = active ? 0.5 + Math.sin(t * 6) * 0.3 : 0.12;
      }
    });
  });

  // AMS lite 4 个料盘：2 行 × 2 列，纵向拉开到盘径的 1.3 倍，避免视角上叠成一团
  const coilPositions = [
    [258, -118],
    [258, 118],
    [100, -118],
    [100, 118]
  ];

  return (
    <group position={[0, 0, 0]}>
      {/* ============ 底座 ============ */}
      <mesh position={[0, -22 - BASE.h / 2, 0]} castShadow receiveShadow>
        <boxGeometry args={[BASE.w, BASE.h, BASE.d]} />
        <meshStandardMaterial ref={frameMatRef} color={COLORS.base} metalness={0.15} roughness={0.55} />
      </mesh>

      {/* 底座前沿蓝色饰条 */}
      <mesh position={[0, -22 - BASE.h + 12, BASE.d / 2 + 1]}>
        <boxGeometry args={[BASE.w * 0.86, 7, 4]} />
        <meshStandardMaterial color={COLORS.accent} emissive={COLORS.accent} emissiveIntensity={0.55} />
      </mesh>

      {/* 屏幕（右前角，倾斜） */}
      <group position={[118, -8, 200]} rotation={[-0.42, 0, 0]}>
        <mesh castShadow>
          <boxGeometry args={[74, 52, 9]} />
          <meshStandardMaterial color="#d5d9df" metalness={0.2} roughness={0.5} />
        </mesh>
        <mesh position={[0, 0, 5]}>
          <boxGeometry args={[64, 42, 1.5]} />
          <meshStandardMaterial color={COLORS.screen} emissive="#1d3a5c" emissiveIntensity={0.9} />
        </mesh>
      </group>

      {/* ============ 双立柱（门式结构） ============ */}
      {[-1, 1].map((side) => (
        <mesh key={side} position={[side * POST.x, -22 + POST.h / 2, POST.z]} castShadow>
          <boxGeometry args={[POST.w, POST.h, POST.d]} />
          <meshStandardMaterial
            ref={(el) => {
              columnMats.current[side === -1 ? 0 : 1] = el;
            }}
            color={COLORS.post}
            metalness={0.45}
            roughness={0.38}
          />
        </mesh>
      ))}

      {/* 立柱顶部黑色角件 */}
      {[-1, 1].map((side) => (
        <mesh key={`cap-${side}`} position={[side * POST.x, 396, POST.z]}>
          <boxGeometry args={[POST.w + 8, 18, POST.d + 8]} />
          <meshStandardMaterial color="#2c3037" metalness={0.3} roughness={0.6} />
        </mesh>
      ))}

      {/* 顶部固定连接梁（结构件，不随 Z 移动；比可动横梁更细更深，避免视觉混淆） */}
      <mesh position={[0, 390, POST.z]} castShadow>
        <boxGeometry args={[BEAM.w + 8, 16, BEAM.d + 4]} />
        <meshStandardMaterial color="#a9b0b9" metalness={0.6} roughness={0.4} />
      </mesh>

      {/* ============ 龙门（随层高升降） ============ */}
      <group ref={gantryRef} position={[0, 40 + GANTRY_OFFSET, POST.z]}>
        {/* X 轴横梁 */}
        <mesh castShadow>
          <boxGeometry args={[BEAM.w, BEAM.h, BEAM.d]} />
          <meshStandardMaterial ref={beamMatRef} color={COLORS.beam} metalness={0.5} roughness={0.32} />
        </mesh>

        {/* 横梁上的导轨 */}
        <mesh position={[0, -BEAM.h / 2 - 2, 2]}>
          <boxGeometry args={[BEAM.w - 30, 6, 12]} />
          <meshStandardMaterial color={COLORS.metal} metalness={0.75} roughness={0.25} />
        </mesh>

        {/* 喷头组件（沿横梁走 X，向前伸出） */}
        <group ref={toolRef} position={[0, -BEAM.h / 2 - TOOL.h / 2, 44]}>
          <mesh castShadow>
            <boxGeometry args={[TOOL.w, TOOL.h, TOOL.d]} />
            <meshStandardMaterial ref={toolMatRef} color={COLORS.tool} metalness={0.2} roughness={0.5} />
          </mesh>

          {/* 喷头前脸深色装饰 */}
          <mesh position={[0, 6, TOOL.d / 2 + 1]}>
            <boxGeometry args={[52, 44, 4]} />
            <meshStandardMaterial color={COLORS.toolDark} metalness={0.3} roughness={0.6} />
          </mesh>

          {/* 散热风扇 */}
          <group position={[0, 10, TOOL.d / 2 + 5]}>
            <mesh rotation={[Math.PI / 2, 0, 0]}>
              <cylinderGeometry args={[22, 22, 9, 22]} />
              <meshStandardMaterial color="#15181c" metalness={0.4} roughness={0.6} />
            </mesh>
            <group ref={fanRef}>
              {[0, 1, 2, 3, 4, 5].map((i) => (
                <mesh key={i} rotation={[0, 0, (Math.PI * 2 * i) / 6]} position={[0, 5, 0]}>
                  <boxGeometry args={[34, 1.6, 6]} />
                  <meshStandardMaterial color="#8d949d" metalness={0.65} roughness={0.35} />
                </mesh>
              ))}
            </group>
          </group>

          {/* 喷嘴（温度变色） */}
          <mesh position={[0, -TOOL.h / 2 - 15, 0]} castShadow>
            <coneGeometry args={[9, 30, 16]} />
            <meshStandardMaterial ref={nozzleMatRef} color="#8b929c" metalness={0.8} roughness={0.3} />
          </mesh>
        </group>
      </group>

      {/* ============ 热床（前后移动） ============ */}
      <group ref={bedRef} position={[0, 0, 0]}>
        {/* 床架 */}
        <mesh position={[0, -15, 0]} castShadow receiveShadow>
          <boxGeometry args={[BED_FRAME.w, BED_FRAME.h, BED_FRAME.d]} />
          <meshStandardMaterial color={COLORS.bedFrame} metalness={0.35} roughness={0.6} />
        </mesh>

        {/* 加热板（温度变色） */}
        <mesh position={[0, -4, 0]} receiveShadow>
          <boxGeometry args={[BED_PLATE.w, BED_PLATE.h, BED_PLATE.d]} />
          <meshStandardMaterial ref={bedMatRef} color={COLORS.bedPlate} metalness={0.25} roughness={0.85} />
        </mesh>

        {/* 打印件：高度随层数生长 */}
        <mesh ref={partRef} position={[0, 0, 0]} scale={[1, 0.001, 1]} castShadow>
          <boxGeometry args={[partW, 200, partD]} />
          <meshStandardMaterial
            color={trayColors[activeTray] ?? trayColors[0]}
            roughness={0.72}
            metalness={0.05}
            transparent
            opacity={0.94}
          />
        </mesh>
      </group>

      {/* ============ 腔灯 ============ */}
      <pointLight ref={lampRef} position={[0, 300, 40]} color="#ffffff" intensity={0} distance={1100} decay={1.5} />
      <mesh position={[0, 400, 60]}>
        <boxGeometry args={[260, 6, 14]} />
        <meshStandardMaterial color="#f7f8fa" emissive="#ffffff" emissiveIntensity={0.45} />
      </mesh>

      {/* ============ AMS lite（独立落地支架） ============ */}
      <group position={[400, 0, -70]} scale={0.82}>
        {/* 支架立柱：放在料盘靠机器一侧，避免遮挡盘面 */}
        {[-1, 1].map((side) => (
          <mesh key={`ams-post-${side}`} position={[-70, 172, side * 166]} castShadow>
            <boxGeometry args={[22, 344, 22]} />
            <meshStandardMaterial color={COLORS.amsFrame} metalness={0.3} roughness={0.5} />
          </mesh>
        ))}
        {/* 立柱与料盘轴之间的横撑 */}
        {[-1, 1].map((side) => (
          <mesh key={`ams-arm-${side}`} position={[-36, 286, side * 166]}>
            <boxGeometry args={[74, 14, 14]} />
            <meshStandardMaterial color={COLORS.amsFrame} metalness={0.3} roughness={0.5} />
          </mesh>
        ))}
        {/* 底座 */}
        <mesh position={[-22, 6, 0]} castShadow receiveShadow>
          <boxGeometry args={[138, 14, 450]} />
          <meshStandardMaterial color={COLORS.amsFrame} metalness={0.25} roughness={0.55} />
        </mesh>

        {coilPositions.map(([y, z], i) => (
          <group key={i} position={[0, y, z]}>
            {/* 料盘轴心（沿 x 方向） */}
            <group rotation={[0, 0, Math.PI / 2]}>
              {/* 线材 */}
              <mesh castShadow>
                <cylinderGeometry args={[COIL.wire, COIL.wire, COIL.thickness, 32]} />
                <meshStandardMaterial
                  ref={(el) => {
                    coilRefs.current[i] = el;
                  }}
                  color={trayColors[i]}
                  emissive={trayColors[i]}
                  emissiveIntensity={0.12}
                  roughness={0.68}
                  metalness={0.05}
                />
              </mesh>
              {/* 两侧盘片：带孔环片，正面能露出线材，避免实心圆"8 字形"观感 */}
              {[-1, 1].map((side) => (
                <mesh key={side} position={[0, side * (COIL.thickness / 2 + 3), 0]}>
                  <ringGeometry args={[COIL.wire + 1, COIL.outer, 44]} />
                  <meshStandardMaterial
                    color={COLORS.coilSide}
                    metalness={0.15}
                    roughness={0.65}
                    side={THREE.DoubleSide}
                  />
                </mesh>
              ))}
              {/* 中心孔 */}
              <mesh>
                <cylinderGeometry args={[20, 20, COIL.thickness + 16, 20]} />
                <meshStandardMaterial color="#2b2f36" metalness={0.4} roughness={0.6} />
              </mesh>
            </group>

            {/* 进料器（料盘上方） */}
            <mesh position={[0, COIL.outer - 8, 0]} castShadow>
              <boxGeometry args={[62, 46, 52]} />
              <meshStandardMaterial color={COLORS.toolDark} metalness={0.3} roughness={0.6} />
            </mesh>
            {/* 进料齿轮（黄色） */}
            <mesh position={[0, COIL.outer - 34, 28]} rotation={[Math.PI / 2, 0, 0]}>
              <cylinderGeometry args={[9, 9, 8, 14]} />
              <meshStandardMaterial color="#f2c200" metalness={0.5} roughness={0.4} />
            </mesh>
          </group>
        ))}
      </group>

      {/* 地面：靠容器级 ContactShadows 提供落地感（浅色/深色主题通用） */}
    </group>
  );
}
