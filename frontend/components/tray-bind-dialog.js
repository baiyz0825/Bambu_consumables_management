"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "./ui/dialog";
import { Input } from "./ui/input";
import { fetchJson } from "../lib/api";

/**
 * 托盘绑定库存选择器 Dialog。
 *
 * 功能：
 * 1. 展示该托盘当前绑定的库存项（如有）
 * 2. 支持解绑当前绑定
 * 3. 库存列表可搜索（材质/颜色/品牌），点击选择并绑定
 *
 * 绑定后端路由：POST /tray-mappings { printer_id, tray_id, stock_id }
 * 解绑路由：POST /tray-mappings/unbind { printer_id, tray_id }
 */
export function TrayBindDialog({
  open,
  onOpenChange,
  printerId,
  trayId,
  currentBinding, // { stock_id, stock_material, stock_color, stock_brand, stock_remaining_grams } | null
  stocks, // 可选的 MaterialStock 列表
  onBound // 绑定/解绑成功后的回调
}) {
  const [query, setQuery] = useState("");
  const [binding, setBinding] = useState(false);

  const reset = useCallback(() => {
    setQuery("");
    setBinding(false);
  }, []);

  useEffect(() => {
    if (!open) reset();
  }, [open, reset]);

  // 按材质/颜色/品牌过滤库存
  const filteredStocks = (Array.isArray(stocks) ? stocks : []).filter((s) => {
    const q = query.trim().toLowerCase();
    if (!q) return true;
    return (
      String(s.material || "").toLowerCase().includes(q) ||
      String(s.color || "").toLowerCase().includes(q) ||
      String(s.brand || "").toLowerCase().includes(q)
    );
  });

  const handleBind = useCallback(
    async (stockId) => {
      if (!printerId || trayId == null) return;
      setBinding(true);
      try {
        await fetchJson("/tray-mappings", {
          method: "POST",
          body: JSON.stringify({
            printer_id: printerId,
            tray_id: Number(trayId),
            stock_id: stockId
          })
        });
        toast.success(`托盘 ${trayId} 已绑定`);
        onBound?.();
        onOpenChange?.(false);
      } catch (e) {
        toast.error(`绑定失败：${String(e?.message || e)}`);
      } finally {
        setBinding(false);
      }
    },
    [printerId, trayId, onBound, onOpenChange]
  );

  const handleUnbind = useCallback(async () => {
    if (!printerId || trayId == null) return;
    setBinding(true);
    try {
      await fetchJson("/tray-mappings/unbind", {
        method: "POST",
        body: JSON.stringify({
          printer_id: printerId,
          tray_id: Number(trayId)
        })
      });
      toast.success(`托盘 ${trayId} 已解绑`);
      onBound?.();
      onOpenChange?.(false);
    } catch (e) {
      toast.error(`解绑失败：${String(e?.message || e)}`);
    } finally {
      setBinding(false);
    }
  }, [printerId, trayId, onBound, onOpenChange]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>托盘 {trayId} 绑定库存</DialogTitle>
          <DialogDescription>
            手动指定该托盘当前装入的耗材对应哪个库存项。绑定后打印消耗会优先从此库存扣减。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          {/* 当前绑定 */}
          {currentBinding?.stock_id ? (
            <div className="rounded-md border bg-muted/30 p-3">
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">当前绑定</span>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={handleUnbind}
                  disabled={binding}
                >
                  解绑
                </Button>
              </div>
              <div className="mt-2 text-sm font-medium">
                {currentBinding.stock_material} · {currentBinding.stock_color}
              </div>
              <div className="text-xs text-muted-foreground">
                {currentBinding.stock_brand} · 剩余 {currentBinding.stock_remaining_grams}g
              </div>
            </div>
          ) : (
            <div className="rounded-md border border-dashed p-3 text-center text-xs text-muted-foreground">
              当前未绑定库存项（系统会按颜色自动匹配）
            </div>
          )}

          {/* 搜索框 */}
          <Input
            placeholder="搜索材质/颜色/品牌…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />

          {/* 库存列表 */}
          <div className="max-h-60 space-y-1 overflow-y-auto">
            {filteredStocks.length === 0 ? (
              <div className="py-6 text-center text-xs text-muted-foreground">
                没有匹配的库存项，请先到「库存」页添加
              </div>
            ) : (
              filteredStocks.map((s) => {
                const isCurrent = s.id === currentBinding?.stock_id;
                return (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => handleBind(s.id)}
                    disabled={binding || isCurrent}
                    className="flex w-full items-center justify-between rounded-md border p-2 text-left transition-colors hover:bg-accent disabled:opacity-50"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium">
                          {s.material} · {s.color}
                        </span>
                        {isCurrent && <Badge variant="secondary">已绑定</Badge>}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {s.brand} · 剩余 {s.remaining_grams}g
                        {s.color_hex && (
                          <span
                            className="ml-2 inline-block h-3 w-6 rounded border align-middle"
                            style={{ backgroundColor: s.color_hex }}
                          />
                        )}
                      </div>
                    </div>
                    {!isCurrent && (
                      <span className="ml-2 text-xs text-primary">选择</span>
                    )}
                  </button>
                );
              })
            )}
          </div>
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange?.(false)}>
            关闭
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
