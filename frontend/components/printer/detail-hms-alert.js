"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { hmsLookup, hmsMeta } from "../../lib/printer-control-api";
import { Badge } from "../ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../ui/card";

/**
 * HMS 故障告警卡。
 *
 * 数据流（与后端约定一致）：
 *
 *     MQTT print.hms[].{attr, code} → collector 归一化出 `ecode`/`module`
 *     → 本组件用 `/hms/lookup?ecodes=...` 批量换中文 `intro`
 *     → `/hms/meta` 的 `modules` 把 `module`（ecode 前两位）映射成模块名（07→AMS）
 *
 * 请求时机（刻意控制请求量）：
 *
 * 1. 只在 **hms 的 ecode 集合发生变化** 时发请求（依赖 `ecodeKey`）；
 * 2. 已查到的文案存在 `cacheRef`，故障小幅增删时只查新增的码；
 * 3. 模块映射是全局常量，用模块级 `modulesPromise` 保证整页只拉一次。
 *
 * 降级策略：查询失败**不弹窗**，只显示 ecode 与「文案暂不可用」提示——
 * 故障码本身已经足够让用户去查手册，不能因为文案接口挂了就遮住告警。
 */
function createModulesPromise() {
  return hmsMeta()
    .then((meta) => (meta && typeof meta.modules === "object" && meta.modules ? meta.modules : {}))
    .catch(() => ({}));
}

let modulesPromise = null;

function loadModules() {
  if (!modulesPromise) modulesPromise = createModulesPromise();
  return modulesPromise;
}

export function DetailHmsAlert({ hms }) {
  // 去重 + 只保留有 ecode 的条目（固件偶发脏数据不应打断列表渲染）
  const items = useMemo(() => {
    const list = Array.isArray(hms) ? hms : [];
    const seen = new Map();
    for (const raw of list) {
      if (!raw || typeof raw !== "object") continue;
      const ecode = String(raw.ecode || "").trim().toUpperCase();
      if (!ecode || seen.has(ecode)) continue;
      seen.set(ecode, { ...raw, ecode });
    }
    return Array.from(seen.values()).sort((a, b) => a.ecode.localeCompare(b.ecode));
  }, [hms]);

  // 稳定的依赖键：只有 ecode 集合真的变了才触发请求
  const ecodeKey = useMemo(() => items.map((it) => it.ecode).join(","), [items]);

  const cacheRef = useRef({}); // ecode → { intro, actions }
  const [intros, setIntros] = useState({});
  const [modules, setModules] = useState({});
  const [lookupFailed, setLookupFailed] = useState(false);

  // 模块名映射：整页一次
  useEffect(() => {
    let cancelled = false;
    loadModules().then((m) => {
      if (!cancelled) setModules(m);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // 故障文案：仅在 ecode 集合变化时补查
  useEffect(() => {
    if (!ecodeKey) {
      setIntros({});
      setLookupFailed(false);
      return undefined;
    }

    const codes = ecodeKey.split(",");
    const missing = codes.filter((code) => !(code in cacheRef.current));
    if (missing.length === 0) {
      setIntros({ ...cacheRef.current });
      setLookupFailed(false);
      return undefined;
    }

    let cancelled = false;
    hmsLookup(missing)
      .then((res) => {
        if (cancelled) return;
        const found = res && typeof res.codes === "object" && res.codes ? res.codes : {};
        for (const [code, info] of Object.entries(found)) {
          cacheRef.current[String(code).toUpperCase()] = info || {};
        }
        setIntros({ ...cacheRef.current });
        setLookupFailed(false);
      })
      .catch(() => {
        if (cancelled) return;
        // 降级：不打断页面，仅标注文案缺失
        setLookupFailed(true);
        setIntros({ ...cacheRef.current });
      });

    return () => {
      cancelled = true;
    };
  }, [ecodeKey]);

  if (items.length === 0) return null;

  return (
    <Card
      className="border-2 border-destructive/60 bg-destructive/[0.04] dark:bg-destructive/[0.12]"
      role="alert"
      aria-live="polite"
      aria-label={`设备故障 ${items.length} 条`}
    >
      <CardHeader>
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-destructive/15 text-destructive">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M12 9v4" />
              <path d="M12 17h.01" />
              <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z" />
            </svg>
          </span>
          <CardTitle className="text-destructive">设备故障（{items.length}）</CardTitle>
        </div>
        <CardDescription>
          故障码来自打印机 HMS 上报；中文说明由 <code className="text-[11px]">/hms/lookup</code> 补齐。
          {lookupFailed ? "（当前未能取到故障说明，仅显示码值）" : null}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2">
          {items.map((item) => {
            const code = item.ecode;
            const moduleKey = String(item.module || code.slice(0, 2)).toUpperCase();
            const moduleName = modules?.[moduleKey] || null;
            const info = intros[code];
            const intro = info && typeof info.intro === "string" ? info.intro.trim() : "";
            return (
              <li
                key={code}
                className="rounded-xl bg-white/80 p-3 shadow-[0_1px_2px_rgba(0,0,0,0.06)] dark:bg-black/30"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="destructive" className="font-mono tracking-wider">
                    {code}
                  </Badge>
                  <Badge variant="outline">{moduleName ? `${moduleKey} · ${moduleName}` : `模块 ${moduleKey}`}</Badge>
                </div>
                <p className="mt-2 text-sm leading-relaxed text-foreground">
                  {intro || (lookupFailed && !info ? "故障说明暂时取不到（仅显示码值）" : "码表中暂无该故障的中文说明")}
                </p>
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}
