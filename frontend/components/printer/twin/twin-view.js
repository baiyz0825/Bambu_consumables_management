"use client";

/**
 * 数字孪生视图容器。
 *
 * 必须在父组件用 `next/dynamic({ ssr: false })` 引入：
 * Three.js 依赖 WebGL 与 window，服务端渲染会直接报错。
 */

import { Canvas } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";

import { A1Model } from "./a1-model";

export function TwinView({ state }) {
  return (
    <div className="relative h-[420px] w-full overflow-hidden rounded-xl bg-[#0b0d12] ring-1 ring-black/10 dark:ring-white/10">
      <Canvas
        camera={{ position: [560, 430, 630], fov: 30, near: 1, far: 5000 }}
        dpr={[1, 2]}
        gl={{ antialias: true }}
      >
        <ambientLight intensity={0.55} />
        <directionalLight position={[380, 640, 420]} intensity={1.15} />
        <directionalLight position={[-420, 260, -380]} intensity={0.35} />
        <A1Model state={state} />
        <OrbitControls
          enablePan
          minDistance={320}
          maxDistance={1800}
          maxPolarAngle={Math.PI / 2.05}
          target={[0, 90, 0]}
        />
      </Canvas>

      <div className="pointer-events-none absolute bottom-2 left-3 text-[11px] text-white/45">
        拖拽旋转 · 滚轮缩放
      </div>
      <div className="pointer-events-none absolute right-3 top-2 rounded-full bg-white/10 px-2 py-0.5 text-[11px] text-white/70">
        参数化模型 · 喷嘴 XY 为估算
      </div>
    </div>
  );
}
