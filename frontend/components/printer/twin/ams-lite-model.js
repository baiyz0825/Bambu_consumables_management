"use client";

/**
 * AMS Lite 参数化组件（配合真实 GLB 模型使用）。
 *
 * 背景：A1 的官方 CAD（GLB）只有打印本体，不含 AMS Lite；
 * 社区也没找到比例正确的整机模型（现有 STL 是内部送料组件，
 * 归一化后 400×745×663，与真实约 400×285×400 相差太远）。
 *
 * 方案：用 three.js 参数化几何画一个示意级的 AMS Lite，叠加在 GLB 旁边。
 * 几何与联动逻辑提取自 a1-model.js（参数化兜底模型），保证两种模式下观感一致。
 *
 * 联动：
 * - 料盘颜色来自 state.ams_trays[0..3].color（RRGGBBAA → #RRGGBB）
 * - 换料时目标槽位（tray_tar）的线材自发光脉冲
 * - HMS 模块 07（AMS）或未知模块故障时，四个料盘红色脉冲
 */

import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";

/** 料盘尺寸：外径 90 / 线材外沿 72 / 盘厚 44（与参数化模型一致） */
const COIL = { outer: 90, wire: 72, thickness: 44 };

const AMS_FRAME = "#c3c8d0";
const COIL_SIDE = "#4b5058";
const TOOL_DARK = "#3c4149";

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

/**
 * 4 个料盘位置 [y, z]：2 行 × 2 列，纵向拉开到盘径的 1.3 倍，
 * 避免视角上叠成一团（与参数化模型相同的取舍）。
 */
const COIL_POSITIONS = [
  [258, -118],
  [258, 118],
  [100, -118],
  [100, 118]
];

export function AmsLiteModel({ state }) {
  const coilRefs = useRef([]);

  const trays = Array.isArray(state?.ams_trays) ? state.ams_trays.slice(0, 4) : [];
  const trayColors = useMemo(
    () => [0, 1, 2, 3].map((i) => trayColor(trays[i]?.color)),
    [trays]
  );
  // 料卷原始自发光色：故障脉冲结束后要能恢复
  const coilBase = useMemo(
    () => trayColors.map((color) => new THREE.Color(color)),
    [trayColors.join(",")]
  );

  useFrame(() => {
    const t = performance.now() / 1000;

    // —— HMS 故障：模块 07 = AMS；未知模块时全部件告警（与打印机本体策略一致）——
    const hmsList = Array.isArray(state?.hms) ? state.hms : [];
    const modules = new Set(hmsList.map((item) => String(item?.module ?? "").toUpperCase()));
    const hasKnown = ["03", "05", "07"].some((code) => modules.has(code));
    const amsFault = hmsList.length > 0 && (!hasKnown || modules.has("07"));
    const pulse = hmsList.length > 0 ? (Math.sin(t * 5) * 0.5 + 0.5) * 0.8 : 0;

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

  return (
    <group position={[420, 0, -70]} scale={0.82}>
      {/* 支架立柱：放在料盘靠机器一侧，避免遮挡盘面 */}
      {[-1, 1].map((side) => (
        <mesh key={`ams-post-${side}`} position={[-70, 172, side * 166]} castShadow>
          <boxGeometry args={[22, 344, 22]} />
          <meshStandardMaterial color={AMS_FRAME} metalness={0.3} roughness={0.5} />
        </mesh>
      ))}
      {/* 立柱与料盘轴之间的横撑 */}
      {[-1, 1].map((side) => (
        <mesh key={`ams-arm-${side}`} position={[-36, 286, side * 166]}>
          <boxGeometry args={[74, 14, 14]} />
          <meshStandardMaterial color={AMS_FRAME} metalness={0.3} roughness={0.5} />
        </mesh>
      ))}
      {/* 底座 */}
      <mesh position={[-22, 6, 0]} castShadow receiveShadow>
        <boxGeometry args={[138, 14, 450]} />
        <meshStandardMaterial color={AMS_FRAME} metalness={0.25} roughness={0.55} />
      </mesh>

      {COIL_POSITIONS.map(([y, z], i) => (
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
            {/* 两侧盘片：带孔环片，正面能露出线材，避免实心圆的"8 字形"观感 */}
            {[-1, 1].map((side) => (
              <mesh key={side} position={[0, side * (COIL.thickness / 2 + 3), 0]}>
                <ringGeometry args={[COIL.wire + 1, COIL.outer, 44]} />
                <meshStandardMaterial
                  color={COIL_SIDE}
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
            <meshStandardMaterial color={TOOL_DARK} metalness={0.3} roughness={0.6} />
          </mesh>
          {/* 进料齿轮（黄色） */}
          <mesh position={[0, COIL.outer - 34, 28]} rotation={[Math.PI / 2, 0, 0]}>
            <cylinderGeometry args={[9, 9, 8, 14]} />
            <meshStandardMaterial color="#f2c200" metalness={0.5} roughness={0.4} />
          </mesh>
        </group>
      ))}
    </group>
  );
}
