"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { ApiError } from "../../../lib/api";
import {
  deleteOutput,
  dispatch,
  downloadOutput,
  formatBytes,
  listOutputs
} from "../../../lib/plate-merger-api";
import { Badge } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../../components/ui/card";
import { DataCell, DataTable } from "../../../components/ui/data-table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "../../../components/ui/dialog";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { NativeSelect } from "../../../components/ui/native-select";

/** 下发表单的初始值（wait_s 默认 15 秒，与后端 DispatchIn 默认值一致）。 */
const EMPTY_FORM = {
  path: "",
  host: "",
  access_code: "",
  serial: "",
  use_ams: false,
  ams_mapping: "",
  wait_s: "15"
};

/** 秒级 Unix 时间戳 → 本地化时间字符串 */
function fmtTime(seconds) {
  const n = Number(seconds);
  if (!Number.isFinite(n) || n <= 0) return "-";
  const d = new Date(n * 1000);
  if (Number.isNaN(d.getTime())) return "-";
  return d.toLocaleString("zh-CN");
}

/** 统一把异常变成可读文案（ApiError 优先取 message） */
function errText(e) {
  if (e instanceof ApiError) return e.message || `请求失败（${e.status ?? "未知"}）`;
  return String(e?.message || e);
}

export default function Page() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadError, setLoadError] = useState("");

  // 删除确认
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleting, setDeleting] = useState(false);

  // 下发打印
  const [dispatchOpen, setDispatchOpen] = useState(false);
  const [dispatchTarget, setDispatchTarget] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [errors, setErrors] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [dispatchNote, setDispatchNote] = useState(null); // { tone, text }

  const reload = useCallback(async () => {
    setRefreshing(true);
    try {
      const data = await listOutputs();
      setItems(Array.isArray(data) ? data : []);
      setLoadError("");
    } catch (e) {
      const msg = errText(e);
      setLoadError(msg);
      toast.error(msg);
    } finally {
      setRefreshing(false);
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const totalSize = useMemo(
    () => items.reduce((sum, it) => sum + (Number(it?.size) || 0), 0),
    [items]
  );

  function setField(key, value) {
    setForm((current) => ({ ...current, [key]: value }));
    setErrors((current) => {
      if (!current[key]) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });
  }

  function handleDownload(item) {
    try {
      downloadOutput(item.name);
      toast.success("已开始下载：" + item.name);
    } catch (e) {
      toast.error(errText(e));
    }
  }

  function openDelete(item) {
    setDeleteTarget(item);
    setDeleteOpen(true);
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      const res = await deleteOutput(deleteTarget.name);
      const deletedName = res?.deleted || deleteTarget.name;
      toast.success("已删除：" + deletedName);
      setDeleteOpen(false);
      setDeleteTarget(null);
      await reload();
    } catch (e) {
      toast.error(errText(e));
    } finally {
      setDeleting(false);
    }
  }

  function openDispatch(item) {
    setDispatchTarget(item);
    setForm({
      ...EMPTY_FORM,
      // 产物库只拿到文件名，这里按后端默认产物目录预填，允许用户改成真实路径
      path: `/tmp/plate-merger/${item.name}`
    });
    setErrors({});
    setDispatchNote(null);
    setDispatchOpen(true);
  }

  function closeDispatch() {
    setDispatchOpen(false);
    setDispatchTarget(null);
    setForm(EMPTY_FORM);
    setErrors({});
    setDispatchNote(null);
  }

  async function submitDispatch(event) {
    event.preventDefault();

    const nextErrors = {};
    const path = form.path.trim();
    const host = form.host.trim();
    const accessCode = form.access_code.trim();
    const serial = form.serial.trim();
    const waitNum = Number(form.wait_s);

    if (!path) nextErrors.path = "请填写服务端的文件绝对路径";
    if (!host) nextErrors.host = "请填写打印机 IP 或主机名";
    if (!accessCode) nextErrors.access_code = "请填写 Access Code";
    if (!serial) nextErrors.serial = "请填写序列号";
    if (!Number.isFinite(waitNum) || waitNum < 1 || waitNum > 120) {
      nextErrors.wait_s = "等待确认秒数需在 1~120 之间";
    }

    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;

    setSubmitting(true);
    setDispatchNote(null);
    try {
      const res = await dispatch({
        path,
        host,
        access_code: accessCode,
        serial,
        use_ams: Boolean(form.use_ams),
        ams_mapping: form.use_ams ? form.ams_mapping.trim() : "",
        wait_s: waitNum
      });
      const detail = String(res?.detail || "").trim();
      const remoteName = String(res?.remote_name || "").trim();

      if (res?.accepted) {
        toast.success(detail ? `已下发：${detail}` : `已下发${remoteName ? `（${remoteName}）` : ""}`);
        closeDispatch();
      } else {
        toast.warning(detail ? `打印机未确认接收：${detail}` : "打印机未确认接收，请检查打印机状态");
        setDispatchNote({
          tone: "warning",
          text: detail || "打印机未在等待时间内确认接收，任务可能未开始。"
        });
      }
    } catch (e) {
      const msg = errText(e);
      toast.error(msg);
      setDispatchNote({ tone: "error", text: msg });
    } finally {
      setSubmitting(false);
    }
  }

  const busy = loading || refreshing;

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <div className="text-sm text-muted-foreground">
            <Link className="hover:underline" href="/production">
              生产
            </Link>{" "}
            / 产物库
          </div>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">产物库</h1>
          <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
            合盘生成的 G-code 文件都在这里：可直接下载留存，也可以下发到局域网内的打印机。
          </p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <Button
            variant="outline"
            onClick={reload}
            disabled={busy}
            className="w-full sm:w-auto"
            aria-live="polite"
          >
            {refreshing ? "刷新中…" : "刷新"}
          </Button>
          <Button asChild variant="outline" className="w-full sm:w-auto">
            <Link href="/production/merge">返回合盘向导</Link>
          </Button>
        </div>
      </div>

      {loadError ? (
        <div className="rounded-2xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          加载产物列表失败：{loadError}
          <Button variant="link" className="ml-1 h-auto px-1 py-0" onClick={reload} disabled={busy}>
            重试
          </Button>
        </div>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>合盘产物</CardTitle>
          <CardDescription>
            {loading
              ? "正在读取服务端产物目录…"
              : items.length > 0
                ? `共 ${items.length} 个文件，合计 ${formatBytes(totalSize)}（按生成时间倒序）。`
                : "服务端暂无可用的合盘产物。"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-3" aria-busy="true" aria-live="polite">
              <span className="sr-only">加载中…</span>
              {[0, 1, 2].map((i) => (
                <div key={i} className="h-12 animate-pulse rounded-xl bg-[#f5f5f7] dark:bg-[#2c2c2e]" />
              ))}
            </div>
          ) : items.length === 0 ? (
            <div className="flex flex-col items-center gap-3 rounded-2xl border border-dashed px-4 py-10 text-center">
              <div className="text-sm font-medium">还没有合盘产物，去合盘向导生成一个</div>
              <p className="max-w-sm text-sm text-muted-foreground">
                合盘完成后回到这里，即可下载产物或直接下发到局域网打印机。
              </p>
              <Button asChild className="mt-1">
                <Link href="/production/merge">去合盘向导</Link>
              </Button>
            </div>
          ) : (
            <DataTable className="lg:min-w-[720px]">
              <thead className="bg-muted/50">
                <tr className="text-left">
                  <th className="px-3 py-2">文件名</th>
                  <th className="px-3 py-2">大小</th>
                  <th className="px-3 py-2">生成时间</th>
                  <th className="px-3 py-2">操作</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.name} className="border-t">
                    <DataCell label="文件名">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium break-all">{item.name}</span>
                        <Badge variant="outline">3MF</Badge>
                      </div>
                    </DataCell>
                    <DataCell label="大小">{formatBytes(item.size)}</DataCell>
                    <DataCell label="生成时间">{fmtTime(item.mtime)}</DataCell>
                    <DataCell label="操作">
                      <div className="flex flex-wrap gap-2">
                        <Button size="sm" variant="outline" onClick={() => handleDownload(item)}>
                          下载
                        </Button>
                        <Button size="sm" onClick={() => openDispatch(item)}>
                          下发打印
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          className="text-destructive hover:text-destructive"
                          onClick={() => openDelete(item)}
                        >
                          删除
                        </Button>
                      </div>
                    </DataCell>
                  </tr>
                ))}
              </tbody>
            </DataTable>
          )}
        </CardContent>
      </Card>

      {/* 删除二次确认 */}
      <Dialog
        open={deleteOpen}
        onOpenChange={(open) => {
          setDeleteOpen(open);
          if (!open) setDeleteTarget(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>删除产物</DialogTitle>
            <DialogDescription>删除后服务端文件将被移除，无法恢复（已下载到本地的副本不受影响）。</DialogDescription>
          </DialogHeader>
          <div className="text-sm">
            你将删除：
            <span className="ml-1 font-medium break-all">{deleteTarget ? deleteTarget.name : "-"}</span>
          </div>
          {deleteTarget ? (
            <div className="text-sm text-muted-foreground">
              文件大小：{formatBytes(deleteTarget.size)} · 生成时间：{fmtTime(deleteTarget.mtime)}
            </div>
          ) : null}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setDeleteOpen(false)} disabled={deleting}>
              取消
            </Button>
            <Button type="button" variant="destructive" onClick={confirmDelete} disabled={deleting || !deleteTarget}>
              {deleting ? "删除中…" : "确认删除"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 下发打印 */}
      <Dialog
        open={dispatchOpen}
        onOpenChange={(open) => {
          if (open) setDispatchOpen(true);
          else closeDispatch();
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>下发打印</DialogTitle>
            <DialogDescription>
              通过局域网 MQTT 把服务端上的文件推送到打印机，并在等待时间内确认打印机是否接收。
            </DialogDescription>
          </DialogHeader>

          <div className="rounded-xl bg-[#f5f5f7] px-3 py-2 text-sm dark:bg-[#2c2c2e]">
            <span className="text-muted-foreground">文件：</span>
            <span className="font-medium break-all">{dispatchTarget ? dispatchTarget.name : "-"}</span>
            {dispatchTarget ? (
              <span className="ml-2 text-xs text-muted-foreground">{formatBytes(dispatchTarget.size)}</span>
            ) : null}
          </div>

          <form className="grid gap-4" onSubmit={submitDispatch}>
            <div className="grid gap-2">
              <Label htmlFor="dispatch-path">服务端文件路径 *</Label>
              <Input
                id="dispatch-path"
                value={form.path}
                onChange={(e) => setField("path", e.target.value)}
                placeholder="/tmp/plate-merger/xxx.3mf"
                autoComplete="off"
                spellCheck={false}
                aria-invalid={Boolean(errors.path)}
              />
              <p className="text-xs text-muted-foreground">
                服务端文件路径，通常为 /tmp/plate-merger/&lt;文件名&gt;。后端只接受服务端本地已存在的 .3mf
                文件，若部署时改过产物目录，请改成实际路径。
              </p>
              {errors.path ? <p className="text-xs text-destructive">{errors.path}</p> : null}
            </div>

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div className="grid gap-2">
                <Label htmlFor="dispatch-host">打印机 IP / 主机 *</Label>
                <Input
                  id="dispatch-host"
                  value={form.host}
                  onChange={(e) => setField("host", e.target.value)}
                  placeholder="192.168.1.20"
                  inputMode="url"
                  autoComplete="off"
                  spellCheck={false}
                  aria-invalid={Boolean(errors.host)}
                />
                {errors.host ? <p className="text-xs text-destructive">{errors.host}</p> : null}
              </div>

              <div className="grid gap-2">
                <Label htmlFor="dispatch-access-code">Access Code *</Label>
                <Input
                  id="dispatch-access-code"
                  type="password"
                  value={form.access_code}
                  onChange={(e) => setField("access_code", e.target.value)}
                  placeholder="打印机局域网访问码"
                  autoComplete="new-password"
                  aria-invalid={Boolean(errors.access_code)}
                />
                {errors.access_code ? <p className="text-xs text-destructive">{errors.access_code}</p> : null}
              </div>

              <div className="grid gap-2">
                <Label htmlFor="dispatch-serial">序列号 *</Label>
                <Input
                  id="dispatch-serial"
                  value={form.serial}
                  onChange={(e) => setField("serial", e.target.value)}
                  placeholder="打印机 SN"
                  autoComplete="off"
                  spellCheck={false}
                  aria-invalid={Boolean(errors.serial)}
                />
                {errors.serial ? <p className="text-xs text-destructive">{errors.serial}</p> : null}
              </div>

              <div className="grid gap-2">
                <Label htmlFor="dispatch-wait">等待确认秒数 *</Label>
                <Input
                  id="dispatch-wait"
                  type="number"
                  min="1"
                  max="120"
                  step="1"
                  inputMode="numeric"
                  value={form.wait_s}
                  onChange={(e) => setField("wait_s", e.target.value)}
                  aria-invalid={Boolean(errors.wait_s)}
                />
                {errors.wait_s ? (
                  <p className="text-xs text-destructive">{errors.wait_s}</p>
                ) : (
                  <p className="text-xs text-muted-foreground">1~120 秒，默认 15 秒。</p>
                )}
              </div>

              <div className="grid gap-2">
                <Label htmlFor="dispatch-use-ams">使用 AMS</Label>
                <NativeSelect
                  id="dispatch-use-ams"
                  value={form.use_ams ? "yes" : "no"}
                  onChange={(e) => {
                    const useAms = e.target.value === "yes";
                    setField("use_ams", useAms);
                    if (!useAms) setField("ams_mapping", "");
                  }}
                >
                  <option value="no">否</option>
                  <option value="yes">是</option>
                </NativeSelect>
              </div>

              <div className="grid gap-2">
                <Label htmlFor="dispatch-ams-mapping">AMS 映射</Label>
                <Input
                  id="dispatch-ams-mapping"
                  value={form.ams_mapping}
                  onChange={(e) => setField("ams_mapping", e.target.value)}
                  placeholder="如 0,1,2"
                  disabled={!form.use_ams}
                  autoComplete="off"
                  spellCheck={false}
                />
                <p className="text-xs text-muted-foreground">
                  {form.use_ams ? "按槽位顺序填写，逗号分隔。" : "仅在使用 AMS 时可填写。"}
                </p>
              </div>
            </div>

            {dispatchNote ? (
              <div
                className={
                  dispatchNote.tone === "error"
                    ? "rounded-xl border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
                    : "rounded-xl bg-[hsl(var(--tint-orange))] p-3 text-sm text-[hsl(var(--tint-orange-ink))]"
                }
                role="status"
              >
                {dispatchNote.text}
              </div>
            ) : null}

            <DialogFooter>
              <Button type="button" variant="outline" onClick={closeDispatch} disabled={submitting}>
                取消
              </Button>
              <Button type="submit" disabled={submitting}>
                {submitting ? "下发中…" : "下发打印"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
