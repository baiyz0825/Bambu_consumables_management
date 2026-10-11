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
import { Label } from "./ui/label";
import { fetchJson } from "../lib/api";

/**
 * 局域网 mDNS 扫描拓竹打印机组件。
 *
 * 工作流程：
 * 1. 点击「扫描局域网」按钮，调用后端 GET /printers/scan
 * 2. 后端用 zeroconf 监听 _bambu-discovery._tcp.local.，5 秒窗口
 * 3. 返回发现的设备列表（IP/Serial/Model/固件版本），标记已添加
 * 4. 用户点击未添加的设备 → 调 onSelect 回调预填到添加表单
 * 5. 用户只需在打印机屏幕查看并手输 LAN Access Code 即可提交
 *
 * 注意：mDNS 扫描依赖后端所在机器与打印机在同一局域网/广播域，
 * 跨子网或 VPN 隔离环境下可能扫不到，需手动添加。
 */
export function PrinterScanDialog({ open, onOpenChange, onSelect, existingSerials = [] }) {
  const [scanning, setScanning] = useState(false);
  const [devices, setDevices] = useState([]);
  const [scanError, setScanError] = useState(null);

  const reset = useCallback(() => {
    setDevices([]);
    setScanError(null);
    setScanning(false);
  }, []);

  useEffect(() => {
    if (!open) reset();
  }, [open, reset]);

  const startScan = useCallback(async () => {
    setScanning(true);
    setScanError(null);
    setDevices([]);
    try {
      const data = await fetchJson("/printers/scan?timeout=5");
      const list = Array.isArray(data?.devices) ? data.devices : [];
      setDevices(list);
      if (list.length === 0) {
        toast.info("未发现拓竹打印机，请确认打印机已开机并连入同一局域网");
      } else {
        toast.success(`发现 ${list.length} 台拓竹打印机`);
      }
    } catch (e) {
      const msg = String(e?.message || e);
      setScanError(msg);
      toast.error(`扫描失败：${msg}`);
    } finally {
      setScanning(false);
    }
  }, []);

  const handleSelect = useCallback(
    (device) => {
      onSelect?.({
        ip: device.ip,
        serial: device.serial || "",
        model: device.model || "",
        alias: device.name || device.hostname || "",
      });
      onOpenChange?.(false);
    },
    [onSelect, onOpenChange]
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>扫描局域网拓竹打印机</DialogTitle>
          <DialogDescription>
            通过 mDNS 自动发现局域网内的拓竹打印机。选中后只需手动输入 LAN Access Code（在打印机屏幕「设置 → 网络」中查看）即可完成添加。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          {/* 扫描按钮 + 状态 */}
          <div className="flex items-center gap-3">
            <Button
              type="button"
              onClick={startScan}
              disabled={scanning}
              className="flex-1"
            >
              {scanning ? (
                <>
                  <svg
                    className="mr-2 h-4 w-4 animate-spin"
                    xmlns="http://www.w3.org/2000/svg"
                    fill="none"
                    viewBox="0 0 24 24"
                  >
                    <circle
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      strokeWidth="4"
                      className="opacity-25"
                    />
                    <path
                      fill="currentColor"
                      className="opacity-75"
                      d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
                    />
                  </svg>
                  扫描中（约 5 秒）…
                </>
              ) : (
                <>
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    className="mr-2"
                  >
                    <circle cx="12" cy="12" r="10" />
                    <path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
                  </svg>
                  开始扫描
                </>
              )}
            </Button>
            {!scanning && devices.length > 0 && (
              <span className="text-xs text-muted-foreground">
                发现 {devices.length} 台
              </span>
            )}
          </div>

          {/* 错误提示 */}
          {scanError && (
            <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
              {scanError}
            </div>
          )}

          {/* 扫描结果列表 */}
          {devices.length > 0 ? (
            <div className="max-h-80 space-y-2 overflow-y-auto">
              {devices.map((d, i) => (
                <div
                  key={`${d.ip}-${i}`}
                  className="flex items-center justify-between rounded-md border p-3 transition-colors hover:bg-accent"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-sm font-medium">{d.ip}</span>
                      {d.already_added && (
                        <Badge variant="secondary">已添加</Badge>
                      )}
                    </div>
                    <div className="mt-0.5 truncate text-xs text-muted-foreground">
                      {d.model || "未知型号"} ·{" "}
                      {d.serial || "无序列号"} ·{" "}
                      {d.hostname || ""}
                    </div>
                    {d.fw_version && (
                      <div className="text-xs text-muted-foreground">
                        固件 {d.fw_version}
                      </div>
                    )}
                  </div>
                  {!d.already_added && (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => handleSelect(d)}
                    >
                      选择
                    </Button>
                  )}
                </div>
              ))}
            </div>
          ) : (
            !scanning &&
            !scanError &&
            devices.length === 0 && (
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
                  <path d="M5 12.55a11 11 0 0 1 14.08 0" />
                  <path d="M1.42 9a16 16 0 0 1 21.16 0" />
                  <path d="M8.53 16.11a6 6 0 0 1 6.95 0" />
                  <line x1="12" y1="20" x2="12.01" y2="20" />
                </svg>
                <p className="mt-2 text-xs">点击上方按钮开始扫描</p>
                <p className="mt-1 text-xs opacity-70">
                  需打印机与本机同一局域网
                </p>
              </div>
            )
          )}
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
