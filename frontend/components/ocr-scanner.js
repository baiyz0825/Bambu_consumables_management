"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "./ui/button";
import { Badge } from "./ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "./ui/dialog";
import { cn } from "../lib/utils";
import { extractDominantColor, loadImageFromFile } from "../lib/color-extractor";
import { parseFilamentLabel } from "../lib/filament-parser";

/**
 * 耗材标签拍照 OCR 识别组件。
 *
 * 工作流程：
 * 1. 用户拍照或上传图片（调用摄像头 input[accept=image/*][capture] 或文件选择）
 * 2. 同时做两件事：
 *    a. Tesseract.js 识别文字（中英文）
 *    b. canvas 提取图片主色调 hex
 * 3. 用正则从 OCR 文本提取材质/重量/颜色名/品牌
 * 4. 颜色优先级：图像取色 hex > OCR 文本颜色名映射 hex > null
 * 5. 把结构化结果回调给父组件预填表单
 *
 * 设计要点：
 * - Tesseract.js 通过 next/dynamic 动态导入（仅客户端，避免 SSR 报错）
 * - 语言包从 jsdelivr CDN 加载（chi_sim + eng），首次约 10MB
 * - 识别过程有进度条，支持取消
 * - 识别结果展示在 Dialog 中，用户确认后再预填
 */

// Tesseract.js 的 createWorker 通过运行时动态 import 加载（仅客户端），
// 首次会从 CDN 下载 chi_sim + eng 语言包（约 10MB）。

/**
 * 颜色 hex → 中文名（用于展示）
 */
const HEX_TO_CN = {
  "#000000": "黑色",
  "#FFFFFF": "白色",
  "#E60012": "红色",
  "#FF6600": "橙色",
  "#FFE500": "黄色",
  "#00C853": "绿色",
  "#0066FF": "蓝色",
  "#00BFFF": "青色",
  "#8E24AA": "紫色",
  "#FF69B4": "粉色",
  "#9E9E9E": "灰色",
  "#795548": "棕色",
  "#FFD700": "金色"
};

function hexToColorName(hex) {
  if (!hex) return null;
  return HEX_TO_CN[hex.toUpperCase()] || null;
}

export function OcrScanner({ open, onOpenChange, onResult }) {
  const [imageSrc, setImageSrc] = useState(null);
  const [imageFile, setImageFile] = useState(null);
  const [status, setStatus] = useState("idle"); // idle | loading | ocr | done | error
  const [progress, setProgress] = useState(0);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const workerRef = useRef(null);
  const fileInputRef = useRef(null);

  // 动态拿到 createWorker 函数
  const [createWorker, setCreateWorker] = useState(null);
  useEffect(() => {
    if (typeof window === "undefined") return;
    import("tesseract.js")
      .then((m) => setCreateWorker(() => m.createWorker))
      .catch((e) => setError(`OCR 模块加载失败：${e.message}`));
  }, []);

  const reset = useCallback(() => {
    setImageSrc(null);
    setImageFile(null);
    setStatus("idle");
    setProgress(0);
    setResult(null);
    setError(null);
  }, []);

  // 关闭 Dialog 时清理
  useEffect(() => {
    if (!open) {
      reset();
      // 终止 worker（下次重新创建，避免内存泄漏）
      if (workerRef.current) {
        workerRef.current.terminate();
        workerRef.current = null;
      }
    }
  }, [open, reset]);

  const handleFile = useCallback(
    async (file) => {
      if (!file) return;
      reset();
      setError(null);

      const url = URL.createObjectURL(file);
      setImageSrc(url);
      setImageFile(file);
      setStatus("loading");

      try {
        const img = await loadImageFromFile(file);

        // 并行：图像取色（同步快） + OCR（异步慢）
        const colorResult = extractDominantColor(img);

        if (!createWorker) {
          setError("OCR 模块尚未加载完成，请稍候重试");
          setStatus("error");
          return;
        }

        setStatus("ocr");
        setProgress(0);

        // 创建 worker（首次会下载语言包，约 10MB）
        const worker = await createWorker(["chi_sim", "eng"], 1, {
          logger: (m) => {
            if (m.status === "recognizing text") {
              setProgress(Math.round(m.progress * 100));
            }
          }
        });
        workerRef.current = worker;

        const { data } = await worker.recognize(file);
        const parsed = parseFilamentLabel(data.text, data.confidence);

        // 颜色优先级：图像取色 > OCR 文本颜色名
        let finalColorHex = colorResult?.hex || parsed.color_hex || null;
        let finalColorName =
          colorResult?.name ||
          parsed.color_name ||
          hexToColorName(finalColorHex);

        const finalResult = {
          ...parsed,
          color_hex: finalColorHex,
          color_name: finalColorName,
          image_color: colorResult // 调试用
        };

        setResult(finalResult);
        setStatus("done");
      } catch (e) {
        console.error("OCR 识别失败:", e);
        setError(`识别失败：${e?.message || "未知错误"}`);
        setStatus("error");
      }
    },
    [createWorker, reset]
  );

  const handleConfirm = useCallback(() => {
    if (result) {
      onResult?.(result);
    }
    onOpenChange?.(false);
  }, [result, onResult, onOpenChange]);

  const hasResult = status === "done" && result;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>拍照识别耗材</DialogTitle>
          <DialogDescription>
            拍摄或上传耗材标签照片，自动识别材质、颜色、重量、品牌。识别不准时可手动修改。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* 图片预览区 */}
          {imageSrc ? (
            <div className="relative">
              <img
                src={imageSrc}
                alt="耗材标签"
                className="mx-auto max-h-48 w-auto rounded-md border"
              />
              {/* 状态遮罩 */}
              {(status === "loading" || status === "ocr") && (
                <div className="absolute inset-0 flex flex-col items-center justify-center rounded-md bg-black/60 text-white">
                  <div className="text-sm">
                    {status === "loading" ? "加载图片中..." : "文字识别中..."}
                  </div>
                  {status === "ocr" && (
                    <div className="mt-2 h-1.5 w-32 overflow-hidden rounded-full bg-white/20">
                      <div
                        className="h-full bg-primary transition-all"
                        style={{ width: `${progress}%` }}
                      />
                    </div>
                  )}
                  {status === "ocr" && (
                    <div className="mt-1 text-xs opacity-70">{progress}%</div>
                  )}
                </div>
              )}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center rounded-md border border-dashed py-10 text-muted-foreground">
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="32"
                height="32"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3Z" />
                <circle cx="12" cy="13" r="3" />
              </svg>
              <p className="mt-2 text-xs">拍照或选择图片开始识别</p>
            </div>
          )}

          {/* 操作按钮 */}
          <div className="flex gap-2">
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              capture="environment"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) handleFile(f);
                e.target.value = ""; // 允许重复选同一文件
              }}
            />
            <Button
              type="button"
              variant="outline"
              className="flex-1"
              onClick={() => fileInputRef.current?.click()}
              disabled={status === "loading" || status === "ocr"}
            >
              {imageSrc ? "重新拍摄" : "拍照 / 选择图片"}
            </Button>
          </div>

          {/* 错误提示 */}
          {error && (
            <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
              {error}
            </div>
          )}

          {/* 识别结果 */}
          {hasResult && (
            <div className="space-y-3 rounded-md border bg-muted/30 p-3">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium">识别结果</span>
                <Badge variant={result.confidence > 70 ? "default" : "secondary"}>
                  置信度 {result.confidence}%
                </Badge>
              </div>
              <div className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
                <ResultField label="材质" value={result.material} />
                <ResultField
                  label="单卷重量"
                  value={
                    result.weight_grams
                      ? `${result.weight_grams}g (${(result.weight_grams / 1000).toFixed(2)}kg)`
                      : null
                  }
                />
                <ResultField label="品牌" value={result.brand} />
                <ResultField
                  label="颜色名"
                  value={result.color_name}
                />
                <ResultField
                  label="色值"
                  value={result.color_hex}
                  extra={
                    result.color_hex ? (
                      <span
                        className="ml-2 inline-block h-4 w-8 rounded border"
                        style={{ backgroundColor: result.color_hex }}
                      />
                    ) : null
                  }
                />
                <ResultField
                  label="图像取色"
                  value={
                    result.image_color
                      ? `${result.image_color.hex} (${Math.round(result.image_color.coverage * 100)}%)`
                      : "未提取到彩色"
                  }
                  extra={
                    result.image_color ? (
                      <span
                        className="ml-2 inline-block h-4 w-8 rounded border"
                        style={{ backgroundColor: result.image_color.hex }}
                      />
                    ) : null
                  }
                />
              </div>
              {/* 字段缺失提示 */}
              {(!result.material || !result.weight_grams) && (
                <p className="text-xs text-muted-foreground">
                  ⚠ 部分字段未识别到，确认后可在表单中手动补充。
                </p>
              )}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange?.(false)}
          >
            取消
          </Button>
          <Button
            type="button"
            onClick={handleConfirm}
            disabled={!hasResult}
          >
            填入表单
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ResultField({ label, value, extra }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="flex items-center font-medium">
        {value || <span className="text-muted-foreground">—</span>}
        {extra}
      </div>
    </div>
  );
}
