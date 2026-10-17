"use client";

/**
 * Bambu Lab A1 参数化数字孪生模型。
 *
 * 为什么不用 GLB：
 * 1. 官方没有整机模型，社区 STEP 需要在 Blender 里手工拆件并重设原点；
 * 2. 孪生要驱动 5 个独立部件（龙门/热床/喷头/料卷/灯），程序化建模天然可动；
 * 3. **坐标正确性**：按 A1 真实规格建模，喷嘴 XYZ 才能与 G-code 层索引对上。
 *
 * 坐标约定（单位 mm）：
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
const BASE = { w: 385, h: 70, d: 410 };
const BED = { w: 256, h: 8, d: 256 };
const COLUMN = { w: 96, h: 430, d: 74 };
const BEAM = { w: 384, h: 42, d: 46 };
const TOOL = { w: 76, h: 96, d: 62 };
const COIL = { radius: 92, thickness: 44 };

const COLORS = {
  frame: "#2b2f36",
  frameEdge: "#3b424b",
  bedFrame: "#1a1d22",
  bedPlate: "#4a5058",
  tool: "#1e2228",
  accent: "#0071e3"
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

export function A1Model({ state }) {
  const gantryRef = useRef(null);
  const toolRef = useRef(null);
  const bedRef = useRef(null);
  const partRef = useRef(null);
  const fanRef = useRef(null);
  const lampRef = useRef(null);
  const nozzleMatRef = useRef(null);
  const bedMatRef = useRef(null);
  const frameMatRef = useRef(null);
  const coilRefs = useRef([]);
  const partHRef = useRef(0);

  // 每帧只写这几个目标值，再对实际位置做阻尼跟随，避免数据 1s 一跳造成跳帧
  const targets = useMemo(
    () => ({ toolY: 40, toolX: 0, bedZ: 0, partH: 0, fan: 0, lamp: 0 }),
    []
  );

  const trays = Array.isArray(state?.ams_trays) ? state.ams_trays.slice(0, 4) : [];
  const trayColors = [0, 1, 2, 3].map((i) => trayColor(trays[i]?.color));

  // 打印件颜色跟随当前使用的槽位
  const trayNowNum = num(state?.tray_now);
  const activeTray = trayNowNum !== null && trayNowNum >= 0 && trayNowNum < 4 ? trayNowNum : 0;

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
    targets.toolY = 10 + clamped * (PRINT_VOLUME - 30);
    // 暂无真实 X 坐标（协议不回传），打印中用摆动近似"喷头在走线"
    targets.toolX = running ? Math.sin(t * 1.15) * 82 : 0;
    targets.bedZ = running ? Math.sin(t * 0.72) * 54 : 0;
    targets.partH = clamped * 200;

    // —— 阻尼跟随 ——
    if (gantryRef.current) {
      gantryRef.current.position.y = damp(gantryRef.current.position.y, targets.toolY, 6, dt);
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
    const bedHeat = heatColor(bedT * 1.6).clone();
    if (nozzleMatRef.current) {
      nozzleMatRef.current.color.copy(nozzleHeat);
      nozzleMatRef.current.emissive.copy(nozzleHeat).multiplyScalar(0.25);
    }
    if (bedMatRef.current) {
      bedMatRef.current.color.copy(bedHeat);
      bedMatRef.current.emissive.copy(bedHeat).multiplyScalar(0.12);
    }

    // —— 风扇 ——
    const fanSpeed = num(state?.cooling_fan_speed) ?? 0;
    targets.fan = fanSpeed > 100 ? fanSpeed / 255 : fanSpeed / 100;
    if (fanRef.current) {
      fanRef.current.rotation.z += dt * targets.fan * 26;
    }

    // —— 腔灯 ——
    const lightOn = state?.lights?.chamber_light === "on";
    targets.lamp = lightOn ? 1.6 : 0;
    if (lampRef.current) {
      lampRef.current.intensity = damp(lampRef.current.intensity, targets.lamp, 8, dt);
    }

    // —— HMS 故障：整机红脉冲 ——
    const hms = Array.isArray(state?.hms) ? state.hms.length : 0;
    if (frameMatRef.current) {
      const pulse = hms > 0 ? (Math.sin(t * 5) * 0.5 + 0.5) * 0.55 : 0;
      frameMatRef.current.emissive.setRGB(pulse, 0, 0);
    }

    // —— 换料：料卷高亮 ——
    const target = num(state?.tray_tar);
    coilRefs.current.forEach((mat, index) => {
      if (!mat) return;
      const active = target !== null && target === index;
      mat.emissiveIntensity = active ? 0.45 + Math.sin(t * 6) * 0.25 : 0.05;
    });
  });

  return (
    <group position={[0, 0, 0]}>
      {/* 底座 */}
      <mesh position={[0, -(BASE.h / 2) - BED.h, 0]} castShadow receiveShadow>
        <boxGeometry args={[BASE.w, BASE.h, BASE.d]} />
        <meshStandardMaterial ref={frameMatRef} color={COLORS.frame} metalness={0.35} roughness={0.62} />
      </mesh>

      {/* 底座前沿装饰条 */}
      <mesh position={[0, -BED.h - BASE.h + 6, BASE.d / 2 + 1]}>
        <boxGeometry args={[BASE.w * 0.82, 10, 6]} />
        <meshStandardMaterial color={COLORS.accent} emissive={COLORS.accent} emissiveIntensity={0.5} />
      </mesh>

      {/* Z 立柱（A1 为单立柱悬臂结构） */}
      <mesh position={[0, COLUMN.h / 2 - BED.h, -(BASE.d / 2) + 30]} castShadow>
        <boxGeometry args={[COLUMN.w, COLUMN.h, COLUMN.d]} />
        <meshStandardMaterial color={COLORS.frameEdge} metalness={0.4} roughness={0.55} />
      </mesh>

      {/* 龙门横梁（随打印层高上下移动） */}
      <group ref={gantryRef} position={[0, 40, -(BASE.d / 2) + 62]}>
        <mesh castShadow>
          <boxGeometry args={[BEAM.w, BEAM.h, BEAM.d]} />
          <meshStandardMaterial color={COLORS.frameEdge} metalness={0.45} roughness={0.5} />
        </mesh>

        {/* 喷头组件（沿横梁左右移动） */}
        <group ref={toolRef} position={[0, 0, 18]}>
          <mesh castShadow>
            <boxGeometry args={[TOOL.w, TOOL.h, TOOL.d]} />
            <meshStandardMaterial color={COLORS.tool} metalness={0.3} roughness={0.65} />
          </mesh>

          {/* 散热风扇 */}
          <group position={[0, 6, TOOL.d / 2 + 3]}>
            <mesh rotation={[Math.PI / 2, 0, 0]}>
              <cylinderGeometry args={[20, 20, 8, 20]} />
              <meshStandardMaterial color="#14171b" metalness={0.5} roughness={0.5} />
            </mesh>
            <group ref={fanRef}>
              {[0, 1, 2, 3, 4].map((i) => (
                <mesh key={i} rotation={[0, 0, (Math.PI * 2 * i) / 5]} position={[0, 5, 0]}>
                  <boxGeometry args={[30, 1.6, 6]} />
                  <meshStandardMaterial color="#7d858f" metalness={0.6} roughness={0.4} />
                </mesh>
              ))}
            </group>
          </group>

          {/* 喷嘴（温度变色） */}
          <mesh position={[0, -TOOL.h / 2 - 12, 0]} castShadow>
            <coneGeometry args={[9, 30, 14]} />
            <meshStandardMaterial ref={nozzleMatRef} color="#8b929c" metalness={0.75} roughness={0.35} />
          </mesh>
        </group>
      </group>

      {/* 热床（前后移动） */}
      <group ref={bedRef} position={[0, -BED.h / 2, 0]}>
        <mesh castShadow receiveShadow>
          <boxGeometry args={[BED.w, BED.h, BED.d]} />
          <meshStandardMaterial color={COLORS.bedFrame} metalness={0.2} roughness={0.85} />
        </mesh>
        <mesh position={[0, BED.h / 2 + 1, 0]} receiveShadow>
          <boxGeometry args={[BED.w * 0.97, 2, BED.d * 0.97]} />
          <meshStandardMaterial ref={bedMatRef} color="#4a5058" metalness={0.15} roughness={0.9} />
        </mesh>

        {/* 打印件：高度随层数生长 */}
        <mesh ref={partRef} position={[0, 0, 0]} scale={[1, 0.001, 1]} castShadow>
          <boxGeometry args={[170, 200, 170]} />
          <meshStandardMaterial
            color={trayColors[activeTray] ?? trayColors[0]}
            roughness={0.75}
            metalness={0.05}
            transparent
            opacity={0.92}
          />
        </mesh>
      </group>

      {/* 腔灯 */}
      <pointLight ref={lampRef} position={[0, 240, -60]} color="#ffffff" intensity={0} distance={900} decay={1.6} />
      <mesh position={[0, 232, -(BASE.d / 2) + 40]}>
        <boxGeometry args={[150, 8, 16]} />
        <meshStandardMaterial color="#f5f5f7" emissive="#ffffff" emissiveIntensity={0.35} />
      </mesh>

      {/* AMS lite：4 个料卷（颜色来自上报） */}
      <group position={[300, 130, -150]}>
        {[0, 1, 2, 3].map((i) => (
          <group key={i} position={[0, 0, i * 108]} rotation={[0, 0, Math.PI / 2]}>
            <mesh castShadow>
              <cylinderGeometry args={[COIL.radius, COIL.radius, COIL.thickness, 28]} />
              <meshStandardMaterial
                ref={(el) => {
                  coilRefs.current[i] = el;
                }}
                color={trayColors[i]}
                emissive={trayColors[i]}
                emissiveIntensity={0.05}
                roughness={0.7}
              />
            </mesh>
            <mesh>
              <cylinderGeometry args={[COIL.radius * 0.42, COIL.radius * 0.42, COIL.thickness + 6, 20]} />
              <meshStandardMaterial color="#2f333a" metalness={0.4} roughness={0.6} />
            </mesh>
          </group>
        ))}
      </group>

      {/* 地面参考网格：给出打印空间与尺度感 */}
      <gridHelper args={[900, 18, "#22262c", "#191c21"]} position={[0, -BED.h - BASE.h - 2, 0]} />
    </group>
  );
}
