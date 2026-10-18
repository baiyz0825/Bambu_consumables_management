"use client";

/**
 * 换盘码高级参数面板。
 *
 * 只暴露后端 `EDITABLE_FIELDS` 白名单内的「数值与开关」——换盘动作顺序由渲染器
 * 固定，不开放编辑（顺序本身即机械语义，改错会撞机）。
 */

import { useEffect, useState } from "react";

import { getPresetParams } from "../../lib/plate-merger-api";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { NativeSelect } from "../ui/native-select";

export function MergeAdvancedParams({ presetId, overrides, onChange }) {
  const [params, setParams] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!presetId) return undefined;
    let cancelled = false;
    setLoading(true);
    setError("");

    getPresetParams(presetId)
      .then((data) => {
        if (!cancelled) setParams(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err?.message || "参数加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [presetId]);

  if (loading) {
    return <p className="text-xs text-muted-foreground">参数加载中…</p>;
  }

  if (error) {
    return <p className="text-xs text-[#ff3b30]">{error}</p>;
  }

  if (!params) return null;

  const setValue = (key, value) => {
    onChange({ ...overrides, [key]: value });
  };

  const isOverridden = (key) => overrides[key] !== undefined;
  const changedCount = Object.keys(overrides).length;

  return (
    <div className="space-y-3 rounded-lg border border-black/[0.08] bg-[#f5f5f7]/60 p-3 dark:border-white/10 dark:bg-white/5">
      <p className="text-xs text-muted-foreground">{params.note}</p>

      <div className="grid gap-3 sm:grid-cols-2">
        {params.editable.map((item) => (
          <div key={item.key} className="grid gap-1">
            <Label htmlFor={`param-${item.key}`} className="text-xs">
              {item.label}
              {isOverridden(item.key) ? (
                <span className="ml-1 text-[#0071e3] dark:text-[#0a84ff]">（已改）</span>
              ) : null}
            </Label>

            {item.type === "bool" ? (
              <NativeSelect
                id={`param-${item.key}`}
                value={String(overrides[item.key] ?? item.value)}
                onChange={(e) => setValue(item.key, e.target.value === "true")}
              >
                <option value="true">是</option>
                <option value="false">否</option>
              </NativeSelect>
            ) : (
              <Input
                id={`param-${item.key}`}
                type="number"
                step={item.type === "float" ? "0.1" : "1"}
                value={overrides[item.key] ?? item.value}
                onChange={(e) => {
                  const raw = e.target.value;
                  if (raw === "") {
                    const next = { ...overrides };
                    delete next[item.key];
                    onChange(next);
                    return;
                  }
                  const n = Number(raw);
                  setValue(item.key, item.type === "float" ? n : Math.round(n));
                }}
              />
            )}
          </div>
        ))}
      </div>

      {changedCount > 0 ? (
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs text-muted-foreground">已修改 {changedCount} 项</span>
          <Button type="button" size="sm" variant="outline" onClick={() => onChange({})}>
            恢复预设默认
          </Button>
        </div>
      ) : null}

      <p className="text-[11px] text-muted-foreground">
        提示：<code>Y 轴行程</code> 与 <code>推盘目标位置</code> 需同时调整——推盘目标不能超过行程上限，否则合盘时会被校验拦下。
      </p>
    </div>
  );
}
