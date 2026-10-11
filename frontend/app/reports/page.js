"use client";

import { useCallback, useEffect, useState } from "react";

import { Button } from "../../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { fetchJson } from "../../lib/api";

/** 数字格式化：非有限值显示 "-"，否则按指定小数位输出。 */
function fmtNum(v, digits = 1) {
  const n = Number(v);
  if (!Number.isFinite(n)) return "-";
  return n.toFixed(digits);
}

export default function Page() {
  const [monthly, setMonthly] = useState([]);
  const [daily, setDaily] = useState([]);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);

  const reload = useCallback(async () => {
    setErr("");
    setLoading(true);
    try {
      const [d, m] = await Promise.all([
        fetchJson("/reports/daily?days=30"),
        fetchJson("/reports/monthly")
      ]);
      setDaily(Array.isArray(d?.daily) ? d.daily : []);
      setMonthly(Array.isArray(m) ? m : []);
    } catch (e) {
      setErr(String(e?.message || e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  return (
    <div className="space-y-6">
      {/* 页头：窄屏竖排，避免按钮挤压溢出 */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">报告</h1>
          <p className="text-sm text-muted-foreground">
            按日/按月消耗统计（成本仅统计“已计价覆盖”的部分；未计价部分不计入成本）。
          </p>
        </div>
        <Button variant="outline" onClick={reload} disabled={loading} className="w-full sm:w-auto">
          {loading ? "加载中…" : "刷新"}
        </Button>
      </div>

      {err ? (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          {err}
        </div>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">近 30 天（按日）</CardTitle>
          <CardDescription>按日聚合的消耗克数与折合成本</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto rounded-md border">
            <table className="w-full min-w-[420px] text-sm">
              <thead className="bg-muted/50">
                <tr className="text-left">
                  <th className="px-3 py-2">日期</th>
                  <th className="px-3 py-2">消耗(克)</th>
                  <th className="px-3 py-2">折合成本(元)</th>
                  <th className="px-3 py-2">不可计价(克)</th>
                </tr>
              </thead>
              <tbody>
                {daily.map((r) => (
                  <tr key={r.day} className="border-t">
                    <td className="px-3 py-2">{r.day}</td>
                    <td className="px-3 py-2">{fmtNum(r.grams_total)}</td>
                    <td className="px-3 py-2">{fmtNum(r.cost_total, 2)}</td>
                    <td className="px-3 py-2">{fmtNum(r.unpriced_grams)}</td>
                  </tr>
                ))}
                {daily.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-3 py-6 text-center text-sm text-muted-foreground">
                      暂无数据
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">按月</CardTitle>
          <CardDescription>按月聚合的消耗克数与成本估算</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto rounded-md border">
            <table className="w-full min-w-[360px] text-sm">
              <thead className="bg-muted/50">
                <tr className="text-left">
                  <th className="px-3 py-2">月份</th>
                  <th className="px-3 py-2">克数</th>
                  <th className="px-3 py-2">成本估算</th>
                </tr>
              </thead>
              <tbody>
                {monthly.map((r) => (
                  <tr key={r.month} className="border-t">
                    <td className="px-3 py-2">{r.month}</td>
                    <td className="px-3 py-2">{fmtNum(r.grams)}</td>
                    <td className="px-3 py-2">{fmtNum(r.cost_est, 2)}</td>
                  </tr>
                ))}
                {monthly.length === 0 ? (
                  <tr>
                    <td colSpan={3} className="px-3 py-6 text-center text-sm text-muted-foreground">
                      暂无数据
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
