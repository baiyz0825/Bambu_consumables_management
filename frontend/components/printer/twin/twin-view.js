"use client";

/**
 * 数字孪生视图容器。
 *
 * 必须在父组件用 `next/dynamic({ ssr: false })` 引入：
 * Three.js 依赖 WebGL 与 window，服务端渲染会直接报错。
 *
 * 模型选择：
 * - 若 `public/models/a1.glb` 存在 → 用真实建模（外观准确）
 * - 否则回退到参数化模型（结构正确、可驱动，但外观朴素）
 */

import { Suspense, useEffect, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { ContactShadows, OrbitControls } from "@react-three/drei";

import { A1Model } from "./a1-model";
import { A1GlbModel } from "./a1-glb-model";
import { ModelBoundary } from "./model-boundary";

export function TwinView({ state, layerIndex = null }) {
  const [mode, setMode] = useState("checking");

  useEffect(() => {
    let cancelled = false;
    fetch("/models/a1.glb", { method: "HEAD" })
      .then((res) => {
        if (!cancelled) setMode(res.ok ? "glb" : "procedural");
      })
      .catch(() => {
        if (!cancelled) setMode("procedural");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const usingGlb = mode === "glb";

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

        {usingGlb ? (
          <ModelBoundary
            fallback={<A1Model state={state} layerIndex={layerIndex} />}
            onError={() => setMode("procedural")}
          >
            <Suspense fallback={null}>
              <A1GlbModel state={state} layerIndex={layerIndex} />
            </Suspense>
          </ModelBoundary>
        ) : (
          <A1Model state={state} layerIndex={layerIndex} />
        )}

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
        {usingGlb ? "真实模型 (GLB)" : "参数化模型"}
        {layerIndex ? " · 层索引驱动" : ""}
      </div>
    </div>
  );
}
