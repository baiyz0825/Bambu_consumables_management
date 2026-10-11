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
 * 局域网扫描拓竹打印机组件，提供两种发现方式：
 *
 * 1. mDNS 扫描（默认）：后端用 zeroconf 监听拓竹服务类型，可拿到序列号/型号；
 *    依赖组播可用，AP 隔离 / 跨 VLAN / 打印机未广播时可能扫不到。
 * 2. 网段扫描（兜底）：并发 TCP 探测 8883（局域网 MQTT 端口），
 *    只要 IP 可达就能发现，但拿不到序列号（需用户手输）。
 *
 * 选中设备后回调 onSelect 预填添加表单，用户只需补 LAN Access Code。
 */
export function PrinterScanDialog({ open, onOpenChange, onSelect, existingSerials = [] }) {
  const [mode, setMode] = useState("mdns"); // "mdns" | "subnet"
  const [scanning, setScanning] = useState(false);
  const [devices, setDevices] = useState([]);
  const [scanError, setScanError] = useState(null);

  // 网段扫描输入：打开时向后端询问建议网段（服务端所在网段）
  const [subnet, setSubnet] = useState("");
  const [subnetHint, setSubnetHint] = useState("");

  const reset = useCallback(() => {
    setDevices([]);
    setScanError(null);
    setScanning(false);
  }, []);

  useEffect(() => {
    if (!open) {
      reset();
      return;
    }
    // 拉取后端网络信息用于预填网段（失败静默，用户可手输）
    let cancelled = false;
    (async () => {
      try {
        const info = await fetchJson("/printers/network-info");
        if (cancelled) return;
        if (info?.suggested_subnet) {
          setSubnet((prev) => prev || info.suggested_subnet);
          setSubnetHint(`后端所在网段 ${info.suggested_subnet}${info?.host_ip ? `（${info.host_ip}）` : ""}`);
        }
      } catch {
        // 忽略：预填失败不影响手动输入
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, reset]);

  const startMdnsScan = useCallback(async () => {
    setScanning(true);
    setScanError(null);
    setDevices([]);
    try {
      const data = await fetchJson("/printers/scan?timeout=8");
      const list = Array.isArray(data?.devices) ? data.devices : [];
      setDevices(list);
      if (list.length === 0) {
        toast.info("mDNS 未发现设备，可切换到「网段扫描」按 IP 探测");
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

  const startSubnetScan = useCallback(async () => {
    const value = subnet.trim();
    if (!value) {
      toast.error("请输入网段或 IP，例如 192.168.9 或 192.168.9.37");
      return;
    }
    setScanning(true);
    setScanError(null);
    setDevices([]);
    try {
      const data = await fetchJson("/printers/scan-subnet", {
        method: "POST",
        body: JSON.stringify({ subnet: value })
      });
      const list = Array.isArray(data?.devices) ? data.devices : [];
      setDevices(list);
      if (list.length === 0) {
        toast.info("该网段未发现开放 8883 端口的设备，请确认网段与打印机开机状态");
      } else {
        toast.success(`发现 ${list.length} 台在线设备（按 8883 端口探测）`);
      }
    } catch (e) {
      const msg = String(e?.message || e);
      setScanError(msg);
      toast.error(`扫描失败：${msg}`);
    } finally {
      setScanning(false);
    }
  }, [subnet]);

  const handleSelect = useCallback(
    (device) => {
      onSelect?.({
        ip: device.ip,
        // 网段扫描拿不到序列号，留空由用户手输
        serial: device.serial || "",
        model: device.model || "",
        alias: device.name || device.hostname || ""
      });
      onOpenChange?.(false);
    },
    [onSelect, onOpenChange]
  );

  const tabClass = (active) =>
    `flex-1 rounded-md px-3 py-2 text-sm font-medium transition-colors ${
      active ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"
    }`;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[calc(100%-2rem)] max-w-lg">
        <DialogHeader>
          <DialogTitle>扫描局域网拓竹打印机</DialogTitle>
          <DialogDescription>
            选中设备后仅需手输 LAN Access Code（打印机屏幕「设置 → 网络」查看）。mDNS 扫不到时请用网段扫描按 IP 探测。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          {/* 模式切换 */}
          <div className="flex gap-2">
            <button type="button" className={tabClass(mode === "mdns")} onClick={() => { setMode("mdns"); reset(); }}>
              mDNS 扫描
            </button>
            <button type="button" className={tabClass(mode === "subnet")} onClick={() => { setMode("subnet"); reset(); }}>
              网段扫描
            </button>
          </div>

          {/* 网段扫描输入 */}
          {mode === "subnet" ? (
            <div className="space-y-1.5">
              <Label htmlFor="scan-subnet">网段 / IP</Label>
              <Input
                id="scan-subnet"
                className="h-11"
                placeholder="192.168.9 或 192.168.9.37"
                value={subnet}
                onChange={(e) => setSubnet(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") startSubnetScan();
                }}
              />
              <p className="text-xs text-muted-foreground">
                {subnetHint || "支持网段（192.168.9）、CIDR（192.168.9.0/24）或单个 IP"}
              </p>
            </div>
          ) : null}

          {/* 扫描按钮 */}
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              onClick={mode === "mdns" ? startMdnsScan : startSubnetScan}
              disabled={scanning}
              className="h-11 flex-1 sm:flex-none"
            >
              {scanning ? (
                <>
                  <svg className="mr-2 h-4 w-4 animate-spin" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" className="opacity-25" />
                    <path fill="currentColor" className="opacity-75" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
                  </svg>
                  {mode === "mdns" ? "扫描中（约 8 秒）…" : "探测中…"}
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
                  {mode === "mdns" ? "开始扫描" : "扫描网段"}
                </>
              )}
            </Button>
            {!scanning && devices.length > 0 && (
              <span className="text-xs text-muted-foreground">发现 {devices.length} 台</span>
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
            <div className="max-h-72 space-y-2 overflow-y-auto">
              {devices.map((d, i) => (
                <div
                  key={`${d.ip}-${i}`}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-md border p-3 transition-colors hover:bg-accent"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-sm font-medium">{d.ip}</span>
                      {d.already_added && <Badge variant="secondary">已添加</Badge>}
                      {mode === "subnet" && Array.isArray(d.open_ports) && d.open_ports.length > 0 && (
                        <Badge variant="outline">端口 {d.open_ports.join("/")}</Badge>
                      )}
                    </div>
                    <div className="mt-0.5 truncate text-xs text-muted-foreground">
                      {d.model || "未知型号"} · {d.serial || "序列号需手输"} · {d.hostname || ""}
                    </div>
                    {d.fw_version && <div className="text-xs text-muted-foreground">固件 {d.fw_version}</div>}
                  </div>
                  {!d.already_added && (
                    <Button type="button" size="sm" variant="outline" className="h-9" onClick={() => handleSelect(d)}>
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
                <p className="mt-2 text-xs">
                  {mode === "mdns" ? "点击上方按钮开始扫描" : "输入网段后点击「扫描网段」"}
                </p>
                <p className="mt-1 text-xs opacity-70">
                  {mode === "mdns" ? "需打印机与本机同一局域网且组播可用" : "按 8883 端口探测，可绕过 mDNS 限制"}
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
