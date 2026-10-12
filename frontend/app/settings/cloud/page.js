"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";

import { apiBaseUrl, fetchJson } from "../../../lib/api";
import { Badge } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../../components/ui/card";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { NativeSelect } from "../../../components/ui/native-select";

export default function Page() {
  const [region, setRegion] = useState("cn");
  const [session, setSession] = useState(null);
  const [devices, setDevices] = useState([]);
  const [ticket, setTicket] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    const current = await fetchJson("/cloud/session");
    setSession(current);
    if (current?.logged_in) {
      const listed = await fetchJson("/cloud/devices");
      setDevices(listed.devices || []);
    } else {
      setDevices([]);
    }
  }

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("cloud") === "ok") toast.success("拓竹账号已登录");
    if (params.get("cloud") === "error") toast.error(params.get("message") || "登录失败");
    load().catch((e) => toast.error(String(e?.message || e)));
  }, []);

  async function startLogin() {
    setBusy(true);
    try {
      const res = await fetchJson("/cloud/login/start", {
        method: "POST",
        body: JSON.stringify({
          region,
          return_path: "/settings/cloud",
          front_origin: window.location.origin
        })
      });
      window.location.assign(res.login_url);
    } catch (e) {
      toast.error(String(e?.message || e));
      setBusy(false);
    }
  }

  async function submitTicket() {
    setBusy(true);
    try {
      await fetchJson("/cloud/ticket", {
        method: "POST",
        body: JSON.stringify({ region, ticket })
      });
      setTicket("");
      toast.success("拓竹账号已登录");
      await load();
    } catch (e) {
      toast.error(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  }

  async function logout() {
    try {
      await fetchJson("/cloud/session", { method: "DELETE" });
      toast.success("已退出拓竹账号");
      await load();
    } catch (e) {
      toast.error(String(e?.message || e));
    }
  }

  async function adopt(serial) {
    try {
      const res = await fetchJson("/cloud/printers/adopt", {
        method: "POST",
        body: JSON.stringify({ serial })
      });
      toast.success(res.created ? "已加入打印机列表" : "这台机器已经在列表里");
      await load();
    } catch (e) {
      toast.error(String(e?.message || e));
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">拓竹云账号</h1>
        <p className="text-sm text-muted-foreground">
          登录后采集端多一条云端通路。序列号和已添加的打印机相同，就还是那一台，能直连局域网时优先走局域网。
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>登录</CardTitle>
          <CardDescription>
            会打开拓竹官方登录页。登录成功后浏览器回到这一页。打印机屏幕上的绑定二维码不用再扫。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {session?.logged_in ? (
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="text-sm">
                已登录 {session.display_name || session.mqtt_username || "拓竹账号"}
                <div className="text-muted-foreground">{session.region === "cn" ? "中国区" : "国际区"}</div>
              </div>
              <Button variant="outline" onClick={logout}>
                退出
              </Button>
            </div>
          ) : (
            <div className="grid gap-4 sm:max-w-md">
              <div className="grid gap-2">
                <Label>账号区域</Label>
                <NativeSelect value={region} onChange={(e) => setRegion(e.target.value)} aria-label="账号区域">
                  <option value="cn">中国区</option>
                  <option value="global">国际区</option>
                </NativeSelect>
              </div>
              <Button className="w-full sm:w-auto" onClick={startLogin} disabled={busy}>
                打开拓竹登录页
              </Button>
              <div className="grid gap-2">
                <Label>如果没有自动回来，粘贴地址栏里的 ticket</Label>
                <Input value={ticket} onChange={(e) => setTicket(e.target.value)} placeholder="ticket" />
              </div>
              <Button variant="outline" className="w-full sm:w-auto" onClick={submitTicket} disabled={busy || !ticket.trim()}>
                用 ticket 完成登录
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      {session?.logged_in ? (
        <Card>
          <CardHeader>
            <CardTitle>账号下的打印机</CardTitle>
            <CardDescription>和本地序列号一致的，显示为同一台，不会新建第二条。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {devices.map((device) => (
              <div key={device.serial} className="flex flex-col gap-2 rounded-md border p-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <div className="font-medium">{device.name || device.serial}</div>
                  <div className="break-all text-sm text-muted-foreground">
                    {device.model || "未知型号"} · {device.serial}
                  </div>
                </div>
                {device.same_printer ? (
                  <Badge variant="outline">已是 {device.printer_alias}</Badge>
                ) : (
                  <Button size="sm" onClick={() => adopt(device.serial)}>
                    加入列表
                  </Button>
                )}
              </div>
            ))}
            {devices.length === 0 ? <div className="text-sm text-muted-foreground">这个账号下没有打印机。</div> : null}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
