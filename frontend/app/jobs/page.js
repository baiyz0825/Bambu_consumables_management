"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { fetchJson } from "../../lib/api";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { DataCell, DataTable } from "../../components/ui/data-table";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { NativeSelect } from "../../components/ui/native-select";

export default function Page() {
  const [items, setItems] = useState([]);
  const [printers, setPrinters] = useState([]);
  const [loading, setLoading] = useState(false);
  const [printerId, setPrinterId] = useState("");
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");

  async function reload() {
    try {
      setLoading(true);
      const qs = new URLSearchParams();
      if (printerId) qs.set("printer_id", printerId);
      if (status) qs.set("status", status);
      const data = await fetchJson(`/jobs${qs.toString() ? `?${qs.toString()}` : ""}`);
      setItems(data);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    (async () => {
      try {
        const ps = await fetchJson("/printers");
        setPrinters(Array.isArray(ps) ? ps : []);
      } catch (e) {
        toast.error(String(e?.message || e));
      } finally {
        reload();
      }
    })();
  }, []);

  useEffect(() => {
    reload();
  }, [printerId, status]);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return items;
    return items.filter((j) => {
      const hay = `${j.file_name || ""} ${j.job_key || ""} ${j.status || ""}`.toLowerCase();
      return hay.includes(needle);
    });
  }, [items, q]);

  function fmtTime(iso) {
    if (!iso) return "-";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso);
    return d.toLocaleString();
  }

  function statusVariant(st) {
    const s = String(st || "").toLowerCase();
    if (s === "running") return "info";
    if (s === "ended" || s === "finished" || s === "finish") return "success";
    if (s === "failed") return "destructive";
    if (s === "cancelled" || s === "canceled" || s === "cancel") return "outline";
    return "outline";
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">任务历史</h1>
          <p className="text-sm text-muted-foreground">任务历史：可筛选、查看详情、并手工补录扣料。</p>
        </div>
        <Button variant="outline" onClick={reload} disabled={loading} className="w-full sm:w-auto">
          {loading ? "加载中…" : "刷新"}
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>筛选</CardTitle>
          <CardDescription>按打印机/状态筛选，支持文件名/任务关键字搜索。</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <div className="grid gap-2">
              <Label>打印机</Label>
              <NativeSelect value={printerId} onChange={(e) => setPrinterId(e.target.value)} aria-label="打印机">
                <option value="">全部</option>
                {printers.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.alias || p.serial}
                  </option>
                ))}
              </NativeSelect>
            </div>
            <div className="grid gap-2">
              <Label>状态</Label>
              <NativeSelect value={status} onChange={(e) => setStatus(e.target.value)} aria-label="状态">
                <option value="">全部</option>
                <option value="running">运行中</option>
                <option value="ended">已结束</option>
                <option value="failed">失败</option>
                <option value="cancelled">已取消</option>
              </NativeSelect>
            </div>
            <div className="grid gap-2 sm:col-span-2">
              <Label>搜索</Label>
              <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="文件名 / 任务关键字 / 状态" />
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>任务列表</CardTitle>
          <CardDescription>共 {filtered.length} 条（点击进入详情查看扣料与快照）。</CardDescription>
        </CardHeader>
        <CardContent>
          <DataTable className="lg:min-w-[640px]">
            <thead className="bg-muted/50">
              <tr className="text-left">
                <th className="px-3 py-2">状态</th>
                <th className="px-3 py-2">开始时间</th>
                <th className="px-3 py-2">结束时间</th>
                <th className="px-3 py-2">文件</th>
                <th className="px-3 py-2">打印机</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((j) => {
                const printer = printers.find((p) => p.id === j.printer_id);
                const printerLabel = printer?.alias || printer?.serial || (j.printer_id ? `${String(j.printer_id).slice(0, 8)}…` : "-");
                return (
                  <tr key={j.id} className="border-t">
                    <DataCell label="状态">
                      <Badge variant={statusVariant(j.status)}>{j.status}</Badge>
                    </DataCell>
                    <DataCell label="开始时间">{fmtTime(j.started_at)}</DataCell>
                    <DataCell label="结束时间">{j.ended_at ? fmtTime(j.ended_at) : "-"}</DataCell>
                    <DataCell label="文件">
                      <Link className="font-medium hover:underline" href={`/jobs/${j.id}`}>
                        {j.file_name || "查看详情"}
                      </Link>
                      {j.job_key ? <div className="break-all text-xs text-muted-foreground">{j.job_key}</div> : null}
                      <Button asChild size="sm" variant="outline" className="mt-2 lg:hidden">
                        <Link href={`/jobs/${j.id}`}>查看详情</Link>
                      </Button>
                    </DataCell>
                    <DataCell label="打印机">{printerLabel}</DataCell>
                  </tr>
                );
              })}
              {filtered.length === 0 ? (
                <tr>
                  <td className="px-3 py-8 text-center text-muted-foreground" colSpan={5}>
                    暂无数据
                  </td>
                </tr>
              ) : null}
            </tbody>
          </DataTable>
        </CardContent>
      </Card>
    </div>
  );
}


