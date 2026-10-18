"use client";

/**
 * 数字孪生视图容器。
 *
 * 必须在父组件用 `next/dynamic({ ssr: false })` 引入：
 * Three.js 依赖 WebGL 与 window，服务端渲染会直接报错。
 */

import { Canvas } from "@react-three/fiber";
import { ContactShadows, OrbitControls } from "@react-three/drei";

import { A1Model } from "./a1-model";

export function TwinView({ state, layerIndex = null }) {
  return (
    <div className="relative h-[420px] w-full overflow-hidden rounded-xl bg-[#0b0d12] ring-1 ring-black/10 dark:ring-white/10">
      <Canvas
        camera={{ position: [700, 470, 780], fov: 34, near: 1, far: 7000 }}
        dpr={[1, 2]}
        gl={{ antialias: true }}
      >
        <ambientLight intensity={0.65} />
        <directionalLight position={[420, 760, 520]} intensity={1.35} />
        <directionalLight position={[-480, 320, -420]} intensity={0.5} color="#bcd4ff" />
        <directionalLight position={[900, 260, 200]} intensity={0.35} color="#ffe9c7" />
        <A1Model state={state} layerIndex={layerIndex} />
        <ContactShadows
          position={[0, -85, 0]}
          opacity={0.55}
          scale={2000}
          blur={2.6}
          far={520}
          resolution={512}
        />
        <OrbitControls
          enablePan
          minDistance={380}
          maxDistance={2400}
          maxPolarAngle={Math.PI / 2.05}
          target={[130, 170, 0]}
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
