"use client";

/**
 * 使用真实 CAD 模型（GLB）渲染 A1 孪生体。
 *
 * 模型来源：Bambu A1 官方结构 CAD（STEP）→ cascadio 转 GLB，
 * 保留 25 个装配部件（Toolhead / X axis / heatbed / frame …）。
 *
 * 与参数化模型（a1-model.js）的分工：
 * - 本组件：外观来自真实建模，负责"像不像"
 * - 参数化模型：兜底 + 提供完整的数据联动参考实现
 *
 * 联动策略：
 * - **位移**：按名称识别到的部件做增量位移（有零点，避免中途打开页面瞬移）
 * - **温度**：直接改喷头/热床部件的 emissive，不依赖材质结构
 * - **打印件**：GLB 里没有"正在打印的物体"，额外渲染一个随层生长的方块
 * - **故障**：所有部件红色脉冲
 */

import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { useGLTF } from "@react-three/drei";
import * as THREE from "three";

const TARGET_HEIGHT_MM = 430;
const BED_CENTER = 128;
const PRINT_VOLUME = 256;

const PART_RULES = [
  { key: "toolhead", match: /toolhead|tool_head|extruder|hotend|hot_end|nozzle|print_?head|工具头|喷头/i },
  { key: "gantry", match: /gantry|x[\s_-]?axis|xaxis|beam|rail|carriage|龙门|横梁/i },
  { key: "bed", match: /heatbed|heat_?bed|build_?plate|bed_?plate|^bed\b|热床|床板/i },
  { key: "ams", match: /ams|spool|filament|料盘/i },
  { key: "screen", match: /screen|display|touch|屏幕/i }
];

function classifyName(name) {
  for (const rule of PART_RULES) {
    if (rule.match.test(name)) return rule.key;
  }
  return null;
}

/** 收集部件：浅层匹配，命中即整棵子树归该部件 */
function collectParts(root) {
  const buckets = { gantry: [], toolhead: [], bed: [], ams: [], screen: [] };

  const visit = (node, depth) => {
    if (!node || depth > 2) return;
    const key = classifyName(node.name || "");
    if (key) {
      buckets[key].push(node);
      return;
    }
    node.children.forEach((child) => visit(child, depth + 1));
  };

  root.children.forEach((child) => visit(child, 0));
  return buckets;
}

function num(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function damp(current, target, lambda, dt) {
  return THREE.MathUtils.damp(current, target, lambda, dt);
}

function heatColor(celsius) {
  const c = Math.max(0, Math.min(280, Number(celsius) || 0));
  const t = c / 280;
  const cold = new THREE.Color("#5d6470");
  const warm = new THREE.Color("#ff8a3d");
  const hot = new THREE.Color("#ff3b30");
  return t < 0.5 ? cold.lerp(warm, t / 0.5) : warm.lerp(hot, (t - 0.5) / 0.5);
}

export function A1GlbModel({ state, layerIndex = null }) {
  const { scene } = useGLTF("/models/a1.glb");

  // 归一化 + 材质克隆（避免改一个部件的颜色影响全部）
  const root = useMemo(() => {
    const clone = scene.clone(true);

    clone.traverse((node) => {
      if (!node.isMesh) return;
      node.castShadow = true;
      node.receiveShadow = true;

      const isArray = Array.isArray(node.material);
      node.material = isArray ? node.material.map((m) => m.clone()) : node.material.clone();

      const list = Array.isArray(node.material) ? node.material : [node.material];
      list.forEach((mat) => {
        if (!mat) return;
        if ("metalness" in mat) mat.metalness = Math.min(Number(mat.metalness) || 0, 0.35);
        if ("roughness" in mat) mat.roughness = Math.max(Number(mat.roughness) || 0.5, 0.45);
        mat.needsUpdate = true;
      });
    });

    const box = new THREE.Box3().setFromObject(clone);
    const size = new THREE.Vector3();
    box.getSize(size);

    const scale = size.y > 0 ? TARGET_HEIGHT_MM / size.y : 1;
    clone.scale.setScalar(scale);

    const scaled = new THREE.Box3().setFromObject(clone);
    const center = new THREE.Vector3();
    scaled.getCenter(center);

    clone.position.x -= center.x;
    clone.position.z -= center.z;
    clone.position.y -= scaled.min.y;

    return clone;
  }, [scene]);

  const parts = useMemo(() => collectParts(root), [root]);

  // 记录初始位移
  const initial = useMemo(() => {
    const map = new Map();
    Object.values(parts).forEach((list) =>
      list.forEach((obj) => {
        if (!map.has(obj)) map.set(obj, { x: obj.position.x, y: obj.position.y, z: obj.position.z });
      })
    );
    return map;
  }, [parts]);

  // 收集需要变色的材质
  const heatMaterials = useMemo(() => {
    const collect = (list) => {
      const out = [];
      list.forEach((obj) =>
        obj.traverse((n) => {
          if (!n.isMesh || !n.material) return;
          const arr = Array.isArray(n.material) ? n.material : [n.material];
          arr.forEach((m) => {
            if (m && m.emissive) out.push(m);
          });
        })
      );
      return out;
    };
    return { toolhead: collect(parts.toolhead), bed: collect(parts.bed) };
  }, [parts]);

  // 热床位置（世界坐标），用于放打印件
  const bedInfo = useMemo(() => {
    if (parts.bed.length === 0) {
      return { x: 0, y: 2, z: 0, w: 200, d: 200 };
    }
    const box = new THREE.Box3();
    parts.bed.forEach((o) => box.expandByObject(o));
    const center = new THREE.Vector3();
    const size = new THREE.Vector3();
    box.getCenter(center);
    box.getSize(size);
    return {
      x: center.x,
      y: box.max.y,
      z: center.z,
      w: Math.min(220, size.x * 0.8) || 180,
      d: Math.min(220, size.z * 0.8) || 180
    };
  }, [parts]);

  const partRef = useRef(null);
  const partHRef = useRef(0);
  const zeroY = useRef(null);
  const zeroBedZ = useRef(null);

  const trayNow = num(state?.tray_now);
  const activeTray = trayNow !== null && trayNow >= 0 && trayNow < 4 ? trayNow : 0;
  const trays = Array.isArray(state?.ams_trays) ? state.ams_trays.slice(0, 4) : [];
  const partColor = (() => {
    const raw = trays[activeTray]?.color;
    if (typeof raw !== "string") return "#c9ccd1";
    const s = raw.trim().replace(/^#/, "");
    return s.length >= 6 ? `#${s.slice(0, 6)}` : "#c9ccd1";
  })();

  useFrame((_, delta) => {
    const dt = Math.min(delta, 0.05);
    const running = state?.gcode_state === "RUNNING";
    const layer = num(state?.layer_num);
    const total = num(state?.total_layer_num);
    const progress = num(state?.progress);
    const ratio = layer !== null && total ? layer / total : (progress ?? 0) / 100;
    const clamped = Math.max(0, Math.min(1, ratio));
    const t = performance.now();

    let targetY;
    let targetX;
    let targetBedZ;

    const rows = layerIndex?.layers ?? null;
    if (rows && rows.length > 0 && layer !== null) {
      const row = rows[Math.max(1, Math.min(rows.length, Math.round(layer))) - 1];
      targetY = row[0];
      targetX = (row[1] + row[2]) / 2 - BED_CENTER;
      targetBedZ = -((row[3] + row[4]) / 2 - BED_CENTER);
    } else {
      targetY = 10 + clamped * (PRINT_VOLUME - 30);
      targetX = running ? Math.sin(t / 900) * 70 : 0;
      targetBedZ = running ? Math.sin(t / 1400) * 46 : 0;
    }

    if (zeroY.current === null) zeroY.current = targetY;
    if (zeroBedZ.current === null) zeroBedZ.current = targetBedZ;

    const dy = targetY - zeroY.current;
    const dx = targetX;
    const dBedZ = targetBedZ - zeroBedZ.current;

    [...parts.gantry, ...parts.toolhead].forEach((obj) => {
      const base = initial.get(obj);
      if (!base) return;
      obj.position.y = damp(obj.position.y, base.y + dy, 6, dt);
    });

    parts.toolhead.forEach((obj) => {
      const base = initial.get(obj);
      if (!base) return;
      obj.position.x = damp(obj.position.x, base.x + dx, 7, dt);
    });

    parts.bed.forEach((obj) => {
      const base = initial.get(obj);
      if (!base) return;
      obj.position.z = damp(obj.position.z, base.z + dBedZ, 5, dt);
    });

    // 打印件：随层生长，并跟随床移动
    if (partRef.current) {
      const h = damp(partHRef.current, targetY, 5, dt);
      partHRef.current = h;
      const scaleY = Math.max(0.001, h / 200);
      partRef.current.scale.y = scaleY;
      partRef.current.position.y = bedInfo.y + (200 * scaleY) / 2;
      partRef.current.position.z = bedInfo.z + dBedZ;
    }

    // 温度变色（直接写 emissive，绕开材质结构差异）
    const nozzleHeat = heatColor(num(state?.nozzle_temper) ?? 0);
    heatMaterials.toolhead.forEach((m) => m.emissive.copy(nozzleHeat).multiplyScalar(0.3));

    const bedHeat = heatColor((num(state?.bed_temper) ?? 0) * 0.85);
    heatMaterials.bed.forEach((m) => m.emissive.copy(bedHeat).multiplyScalar(0.25));

    // 故障：所有部件红脉冲
    const hms = Array.isArray(state?.hms) ? state.hms.length : 0;
    if (hms > 0) {
      const pulse = (Math.sin(t / 200) * 0.5 + 0.5) * 0.7;
      Object.values(parts)
        .flat()
        .forEach((obj) =>
          obj.traverse((n) => {
            if (!n.isMesh || !n.material) return;
            const arr = Array.isArray(n.material) ? n.material : [n.material];
            arr.forEach((m) => m?.emissive && m.emissive.setRGB(pulse, 0, 0));
          })
        );
    }
  });

  return (
    <group>
      <primitive object={root} />
      <mesh ref={partRef} position={[bedInfo.x, bedInfo.y, bedInfo.z]} scale={[1, 0.001, 1]} castShadow>
        <boxGeometry args={[bedInfo.w, 200, bedInfo.d]} />
        <meshStandardMaterial color={partColor} roughness={0.72} metalness={0.05} />
      </mesh>
    </group>
  );
}
