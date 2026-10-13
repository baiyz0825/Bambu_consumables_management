"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Button } from "../../../components/ui/button";
import { Card } from "../../../components/ui/card";
import { Input } from "../../../components/ui/input";
import { fetchJson } from "../../../lib/api";

function priceInputValue(price) {
  if (price === null || price === undefined || price === "") return "";
  const n = Number(price);
  if (!Number.isFinite(n)) return "";
  return String(n);
}

function collectBrands(stocks, prices) {
  const priceByBrand = new Map();
  for (const row of Array.isArray(prices) ? prices : []) {
    const brand = String(row?.brand || "").trim();
    if (brand) priceByBrand.set(brand, row.price_per_kg);
  }
  const names = new Set(priceByBrand.keys());
  for (const stock of Array.isArray(stocks) ? stocks : []) {
    const brand = String(stock?.brand || "").trim();
    if (brand) names.add(brand);
  }
  return [...names]
    .sort((a, b) => a.localeCompare(b, "zh-CN"))
    .map((brand) => ({
      brand,
      value: priceInputValue(priceByBrand.has(brand) ? priceByBrand.get(brand) : ""),
      saved: priceByBrand.has(brand)
    }));
}

export default function Page() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [saving, setSaving] = useState({});
  const [messages, setMessages] = useState({});

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr("");
    Promise.all([fetchJson("/stocks"), fetchJson("/brand-prices")])
      .then(([stocks, prices]) => {
        if (!cancelled) setRows(collectBrands(stocks, prices));
      })
      .catch((e) => {
        if (!cancelled) setErr(String(e?.message || e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function updateValue(brand, value) {
    setRows((current) => current.map((row) => (row.brand === brand ? { ...row, value } : row)));
    setMessages((current) => ({ ...current, [brand]: null }));
  }

  async function save(brand) {
    const row = rows.find((item) => item.brand === brand);
    const raw = String(row?.value ?? "").trim();
    if (raw === "") {
      if (!row?.saved) {
        setMessages((current) => ({ ...current, [brand]: { ok: true, text: "未设置" } }));
        return;
      }
      setSaving((current) => ({ ...current, [brand]: true }));
      setMessages((current) => ({ ...current, [brand]: null }));
      try {
        await fetchJson(`/brand-prices/${encodeURIComponent(brand)}`, { method: "DELETE" });
        setRows((current) => current.map((item) => (item.brand === brand ? { ...item, value: "", saved: false } : item)));
        setMessages((current) => ({ ...current, [brand]: { ok: true, text: "已清除" } }));
      } catch (e) {
        setMessages((current) => ({ ...current, [brand]: { ok: false, text: String(e?.message || e) } }));
      } finally {
        setSaving((current) => ({ ...current, [brand]: false }));
      }
      return;
    }
    const price = Number(raw);
    if (!Number.isFinite(price) || price < 0) {
      setMessages((current) => ({ ...current, [brand]: { ok: false, text: "单价需要是大于等于 0 的数字" } }));
      return;
    }
    setSaving((current) => ({ ...current, [brand]: true }));
    setMessages((current) => ({ ...current, [brand]: null }));
    try {
      const saved = await fetchJson(`/brand-prices/${encodeURIComponent(brand)}`, {
        method: "PUT",
        body: JSON.stringify({ price_per_kg: price })
      });
      setRows((current) =>
        current.map((item) =>
          item.brand === brand ? { ...item, value: priceInputValue(saved?.price_per_kg ?? price), saved: true } : item
        )
      );
      setMessages((current) => ({ ...current, [brand]: { ok: true, text: "已保存" } }));
    } catch (e) {
      setMessages((current) => ({ ...current, [brand]: { ok: false, text: String(e?.message || e) } }));
    } finally {
      setSaving((current) => ({ ...current, [brand]: false }));
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <div className="text-sm text-muted-foreground">
          <Link className="hover:underline" href="/settings">
            设置
          </Link>{" "}
          / 品牌单价
        </div>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">品牌单价</h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground">
          成本报告按品牌的元/千克估算。留空表示未设置。
        </p>
      </div>

      {loading ? <p className="text-sm text-muted-foreground">加载中…</p> : null}
      {err ? <p className="text-sm text-destructive">{err}</p> : null}

      {!loading && !err && rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">还没有品牌。先在库存里添加耗材后，可以在这里填单价。</p>
      ) : null}

      {!loading && !err && rows.length > 0 ? (
        <Card className="px-6 sm:px-8">
          <ul className="divide-y divide-black/[0.06] dark:divide-white/10">
            {rows.map((row, index) => {
              const message = messages[row.brand];
              const inputId = `brand-price-${index}`;
              return (
                <li key={row.brand} className="flex flex-col gap-3 py-5 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0 font-medium text-foreground">{row.brand}</div>
                  <form
                    className="flex flex-col gap-2 sm:items-end"
                    onSubmit={(event) => {
                      event.preventDefault();
                      save(row.brand);
                    }}
                  >
                    <div className="flex flex-wrap items-center gap-3">
                      <label className="sr-only" htmlFor={inputId}>
                        {row.brand} 元/千克
                      </label>
                      <Input
                        id={inputId}
                        type="number"
                        inputMode="decimal"
                        min="0"
                        step="0.01"
                        placeholder="未设置"
                        value={row.value}
                        onChange={(event) => updateValue(row.brand, event.target.value)}
                        className="w-36"
                      />
                      <span className="text-sm text-muted-foreground">元/千克</span>
                      <Button type="submit" disabled={Boolean(saving[row.brand])}>
                        {saving[row.brand] ? "保存中…" : "保存"}
                      </Button>
                    </div>
                    {message?.text ? (
                      <p className={`text-sm ${message.ok ? "text-muted-foreground" : "text-destructive"}`}>{message.text}</p>
                    ) : null}
                  </form>
                </li>
              );
            })}
          </ul>
        </Card>
      ) : null}
    </div>
  );
}
