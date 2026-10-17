"use client";

import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../ui/card";

/**
 * 「数字孪生预览」占位卡。
 *
 * 本轮不做 3D：这里只负责**把位置占住**，后续接入 GLB 资产时
 * 只需替换本组件内部实现（父组件 DetailRealtimePanel 的布局无需改动）。
 *
 * 明确的边界：不引入 three.js / 不渲染任何真实模型，虚线框内的线框只是示意。
 */
export function DetailTwinPlaceholder() {
  return (
    <Card data-slot="twin-viewport">
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle>数字孪生预览</CardTitle>
          <Badge variant="outline">待接入</Badge>
        </div>
        <CardDescription>
          后续将在此渲染打印机 3D 模型（GLB），实时反映各轴位置、温度热区与故障部件高亮。
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div
          className="flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed border-black/15 p-6 text-center dark:border-white/20 sm:p-10"
          aria-label="3D 模型占位区域"
          role="img"
        >
          {/* 纯装饰性线框：仅示意「这里以后是一台打印机的模型」 */}
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="112"
            height="96"
            viewBox="0 0 112 96"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="text-muted-foreground/60"
            aria-hidden="true"
          >
            <path d="M16 88h80" />
            <path d="M24 88V28h64v60" />
            <path d="M24 28 56 12l32 16" />
            <path d="M40 88V60h32v28" />
            <path d="M40 60h32" />
            <path d="M56 12v22" strokeDasharray="4 4" />
            <rect x="48" y="34" width="16" height="10" rx="2" />
            <path d="M56 44v10" strokeDasharray="4 4" />
            <path d="M32 20 24 12M80 20l8-8" strokeDasharray="3 3" />
          </svg>
          <p className="text-sm text-muted-foreground">3D 模型接入中（需 GLB 资产）</p>
          <Button variant="outline" disabled title="3D 视图尚未接入，暂不可用">
            旋转视角
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
