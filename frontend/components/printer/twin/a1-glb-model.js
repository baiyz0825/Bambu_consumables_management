"use client";

/**
 * 使用真实 GLB 模型渲染 A1 孪生体。
 *
 * 与参数化模型（a1-model.js）的分工：
 * - 本组件：外观来自真实建模（Sketchfab / MakerWorld 转出的 GLB），负责"像不像"
 * - 参数化模型：兜底，负责"能不能跑"（没有 GLB 时仍可展示与联动）
 *
 * 自动绑定策略：
 * 遍历 GLB 的浅层节点，按名称关键词归类到 龙门 / 喷头 / 热床 / AMS / 屏幕。
 * 命中则驱动其**相对位移**，未命中则整体静态——不会因为拆件不全而导致模型错乱。
 *
 * 相对位移的原因：GLB 里部件原点各不相同，无法知道「喷头原点对应第几层」。
 * 以页面收到第一条数据的层高为**零点**，之后按层高差移动，避免中途打开页面时瞬移。
 *
 * 坐标归一化：按「整机高 ≈ 430mm」自动缩放，底部对齐 y=0（床面），水平居中。
 */

import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { useGLTF } from "@react-three/drei";
import * as THREE from "three";

const TARGET_HEIGHT_MM = 430;
const BED_CENTER = 128;
const PRINT_VOLUME = 256;

//: 部件识别规则（按顺序匹配，先命中者优先）
const PART_RULES = [
  { key: "toolhead", match: /toolhead|tool_head|extruder|hotend|hot_end|nozzle|print_?head|工具头|喷头/i },
  { key: "gantry", match: /gantry|x_?axis|xaxis|beam|rail|carriage|龙门|横梁/i },
  { key: "bed", match: /heatbed|heat_?bed|build_?plate|bed_?plate|^bed\b|热床|床板/i },
  { key: "ams", match: /ams\b|spool|filament|料盘/i },
  { key: "screen", match: /screen|display|touch|屏幕/i }
];

function classifyName(name) {
  for (const rule of PART_RULES) {
    if (rule.match.test(name)) return rule.key;
  }
  return null;
}

/** 收集部件：只向下找两层，避免把内部零件误判成运动件 */
function collectParts(root) {
  const buckets = { gantry: [], toolhead: [], bed: [], ams: [], screen: [] };

  const visit = (node, depth) => {
    if (!node || depth > 2) return;
    const key = classifyName(node.name || "");
    if (key) {
      buckets[key].push(node);
      return; // 命中即整棵子树归该部件
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

export function A1GlbModel({ state, layerIndex = null }) {
  const { scene } = useGLTF("/models/a1.glb");

  // 归一化：缩放 + 居中 + 底部对齐床面
  const root = useMemo(() => {
    const clone = scene.clone(true);

    clone.traverse((node) => {
      if (node.isMesh) {
        node.castShadow = true;
        node.receiveShadow = true;
      }
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

  // 记录各部件初始位移，动画只在其基础上叠加
  const initial = useMemo(() => {
    const map = new Map();
    Object.values(parts).forEach((list) => {
      list.forEach((obj) => {
        if (!map.has(obj)) {
          map.set(obj, { x: obj.position.x, y: obj.position.y, z: obj.position.z });
        }
      });
    });
    return map;
  }, [parts]);

  // 零点：页面收到第一条数据时的层高 / 床位，避免中途打开导致瞬移
  const zeroY = useRef(null);
  const zeroBedZ = useRef(null);

  useFrame((_, delta) => {
    const dt = Math.min(delta, 0.05);
    const running = state?.gcode_state === "RUNNING";
    const layer = num(state?.layer_num);
    const total = num(state?.total_layer_num);
    const progress = num(state?.progress);
    const ratio = layer !== null && total ? layer / total : (progress ?? 0) / 100;
    const clamped = Math.max(0, Math.min(1, ratio));
    const t = performance.now();

    // 目标值（mm，与模型同一坐标系）
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

    // 龙门与喷头：随层高升降
    [...parts.gantry, ...parts.toolhead].forEach((obj) => {
      const base = initial.get(obj);
      if (!base) return;
      obj.position.y = damp(obj.position.y, base.y + dy, 6, dt);
    });

    // 喷头：额外走 X
    parts.toolhead.forEach((obj) => {
      const base = initial.get(obj);
      if (!base) return;
      obj.position.x = damp(obj.position.x, base.x + dx, 7, dt);
    });

    // 热床：走 Y（three 的 z）
    parts.bed.forEach((obj) => {
      const base = initial.get(obj);
      if (!base) return;
      obj.position.z = damp(obj.position.z, base.z + dBedZ, 5, dt);
    });

    // AMS：换料目标槽位轻微摆动，提示"在动作"
    const trayTar = num(state?.tray_tar);
    if (trayTar !== null) {
      parts.ams.forEach((obj, index) => {
        obj.rotation.x = Math.sin(t / 600 + index) * 0.04;
      });
    }
  });

  return <primitive object={root} />;
}
