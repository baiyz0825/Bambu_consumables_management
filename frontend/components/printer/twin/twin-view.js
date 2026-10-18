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
import { ContactShadows, Environment, Lightformer, OrbitControls } from "@react-three/drei";

import { A1Model } from "./a1-model";
import { A1GlbModel } from "./a1-glb-model";
import { AmsLiteModel } from "./ams-lite-model";
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
    <div
      className={
        "relative h-[420px] w-full overflow-hidden rounded-xl ring-1 ring-black/10 dark:ring-white/10 " +
        // 摄影棚「无缝背景墙」：径向渐变，上亮下收，避免纯黑的生硬对比
        "bg-[radial-gradient(120%_95%_at_50%_0%,#f8fafc_0%,#e9eef5_55%,#dbe2ec_100%)] " +
        "dark:bg-[radial-gradient(120%_95%_at_50%_0%,#1d2432_0%,#141925_58%,#0e121b_100%)]"
      }
    >
      <Canvas
        camera={{ position: [820, 560, 960], fov: 30, near: 1, far: 8000 }}
        dpr={[1, 2]}
        gl={{ antialias: true, alpha: true }}
        style={{ background: "transparent" }}
      >
        {/*
          IBL（基于图像的环境光照）：产品查看器的业界标准配方。
          用 Lightformer 程序化生成环境贴图（不下载 HDRI 文件，内网可用），
          材质获得真实反射光泽，比纯方向光的「塑料感」高一档。
          frames 默认静态渲染一次，无运行时开销。
        */}
        <Environment resolution={256}>
          {/* 顶部大柔光箱：主反射来源 */}
          <Lightformer intensity={2.2} rotation-x={Math.PI / 2} position={[0, 5, 0]} scale={[12, 12, 1]} color="#ffffff" />
          {/* 左侧冷条形光：勾出机身棱线 */}
          <Lightformer intensity={1.6} position={[-5, 1.5, -1]} rotation-y={Math.PI / 2} scale={[8, 2.5, 1]} color="#e8f0ff" />
          {/* 右侧暖光：与主光呼应 */}
          <Lightformer intensity={1.2} position={[5, 1, 1]} rotation-y={-Math.PI / 2} scale={[8, 2.5, 1]} color="#fff2e2" />
          {/* 背部轮廓光：把模型从背景里「切」出来 */}
          <Lightformer intensity={1.1} position={[0, 2, -6]} scale={[10, 4, 1]} color="#cdd9ff" />
          {/* 地面弱反弹 */}
          <Lightformer intensity={0.5} rotation-x={-Math.PI / 2} position={[0, -4, 0]} scale={[12, 12, 1]} color="#b8bec9" />
        </Environment>

        {/* 直光只负责方向性阴影感，环境亮度交给上面的 IBL（分工原则：环境归 IBL，方向归直光） */}
        <directionalLight position={[420, 760, 520]} intensity={1.1} color="#fff2e2" />
        <directionalLight position={[-480, 320, -420]} intensity={0.45} color="#bcd4ff" />

        {usingGlb ? (
          <ModelBoundary
            fallback={<A1Model state={state} layerIndex={layerIndex} />}
            onError={() => setMode("procedural")}
          >
            <Suspense fallback={null}>
              <A1GlbModel state={state} layerIndex={layerIndex} />
              {/* GLB 只有打印本体：AMS Lite 用参数化几何补齐 */}
              <AmsLiteModel state={state} />
            </Suspense>
          </ModelBoundary>
        ) : (
          <A1Model state={state} layerIndex={layerIndex} />
        )}

        <ContactShadows
          position={[0, -85, 0]}
          opacity={0.45}
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
          target={[0, 215, 0]}
        />
      </Canvas>

      <div className="pointer-events-none absolute bottom-2 left-3 text-[11px] text-slate-500/80 dark:text-white/45">
        拖拽旋转 · 滚轮缩放
      </div>
      <div className="pointer-events-none absolute right-3 top-2 rounded-full bg-slate-900/5 px-2 py-0.5 text-[11px] text-slate-600 ring-1 ring-slate-900/10 dark:bg-white/10 dark:text-white/70 dark:ring-white/10">
        {usingGlb ? "真实模型 (GLB)" : "参数化模型"}
        {layerIndex ? " · 层索引驱动" : ""}
      </div>
    </div>
  );
}
