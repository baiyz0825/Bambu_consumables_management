"use client";

import { useEffect, useState } from "react";

import { ConsumptionChart } from "../../components/consumption-chart";
import { Button } from "../../components/ui/button";
import { Card } from "../../components/ui/card";
import { fetchJson } from "../../lib/api";

const RANGES = [
  { id: "day", label: "日", span: 14 },
  { id: "week", label: "周", span: 8 },
  { id: "month", label: "月", span: 6 }
];

function fmtGrams(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "-";
  return n.toLocaleString("zh-CN", { maximumFractionDigits: 1 });
}

function fmtCost(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "-";
  return n.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export default function Page() {
  const [granularity, setGranularity] = useState("day");
  const [report, setReport] = useState(null);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const range = RANGES.find((item) => item.id === granularity) || RANGES[0];
    let cancelled = false;
    setLoading(true);
    setErr("");
    fetchJson(`/reports/breakdown?granularity=${range.id}&span=${range.span}`)
      .then((body) => {
        if (!cancelled) setReport(body);
      })
      .catch((e) => {
        if (!cancelled) {
          setReport(null);
          setErr(String(e?.message || e));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [granularity]);

  const totals = report?.totals || {};
  const buckets = Array.isArray(report?.buckets) ? report.buckets : [];

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">报告</h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground">
          按日、周、月查看消耗。每根柱是这一段时间里不同颜色耗材的克数。成本按品牌单价估算。
        </p>
      </div>

      <div className="flex flex-wrap gap-2" role="group" aria-label="统计粒度">
        {RANGES.map((item) => (
          <Button
            key={item.id}
            type="button"
            variant={granularity === item.id ? "default" : "outline"}
            aria-pressed={granularity === item.id}
            onClick={() => setGranularity(item.id)}
          >
            {item.label}
          </Button>
        ))}
      </div>

      {loading ? <p className="text-sm text-muted-foreground">加载中…</p> : null}
      {err ? <p className="text-sm text-destructive">{err}</p> : null}

      {!loading && !err ? (
        <Card className="space-y-8 p-6 sm:p-8">
          <ConsumptionChart buckets={buckets} />
          <p className="flex flex-wrap gap-x-6 gap-y-2 text-sm text-muted-foreground">
            <span>
              消耗克数 <span className="font-medium text-foreground">{fmtGrams(totals.grams)}</span>
            </span>
            <span>
              估算成本 <span className="font-medium text-foreground">{fmtCost(totals.cost_est)}</span>
            </span>
            <span>
              未设单价的克数 <span className="font-medium text-foreground">{fmtGrams(totals.unpriced_grams)}</span>
            </span>
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">各时段消耗克数与估算成本</caption>
              <thead>
                <tr className="text-muted-foreground">
                  <th scope="col" className="py-2 pr-4 font-medium">
                    时段
                  </th>
                  <th scope="col" className="py-2 pr-4 font-medium">
                    克数
                  </th>
                  <th scope="col" className="py-2 font-medium">
                    估算成本
                  </th>
                </tr>
              </thead>
              <tbody>
                {buckets.map((bucket) => (
                  <tr key={bucket.key || bucket.label} className="border-t border-black/[0.06] dark:border-white/10">
                    <th scope="row" className="py-2 pr-4 font-normal text-foreground">
                      {bucket.label}
                    </th>
                    <td className="py-2 pr-4 tabular-nums">{fmtGrams(bucket.grams)}</td>
                    <td className="py-2 tabular-nums">{fmtCost(bucket.cost_est)}</td>
                  </tr>
                ))}
                {buckets.length === 0 ? (
                  <tr>
                    <td colSpan={3} className="py-6 text-muted-foreground">
                      暂无数据
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </Card>
      ) : null}
    </div>
  );
}
