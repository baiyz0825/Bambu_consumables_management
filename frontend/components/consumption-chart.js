"use client";

function segmentHex(segment) {
  const raw = String(segment?.color_hex || "").trim();
  const hex = raw.startsWith("#") ? raw : raw ? `#${raw}` : "";
  return /^#[0-9A-Fa-f]{6}$/.test(hex) ? hex.toUpperCase() : "#8E8E93";
}

function labelWidth(text) {
  return String(text || "").length * 6.2;
}

/** 完整日期在窄柱距下会叠在一起，能放下才保留原文，否则收成月-日。 */
function axisLabel(label, slot) {
  const full = String(label || "");
  const limit = slot * 0.9;
  if (labelWidth(full) <= limit) return full;
  const day = full.match(/^\d{4}-(\d{2}-\d{2})$/);
  if (day && labelWidth(day[1]) <= limit) return day[1];
  const month = full.match(/^\d{4}-(\d{2})$/);
  if (month && labelWidth(month[1]) <= limit) return month[1];
  return full;
}

/**
 * 每个周期一根柱。柱里按耗材本色叠放，不使用装饰色。
 */
export function ConsumptionChart({ buckets = [] }) {
  const width = 640;
  const height = 220;
  const padL = 36;
  const padB = 36;
  const padT = 12;
  const innerH = height - padT - padB;
  const max = Math.max(1, ...buckets.map((bucket) => Number(bucket.grams) || 0));
  const slot = buckets.length > 0 ? (width - padL - 16) / buckets.length : 0;
  const barW = Math.max(8, Math.min(28, slot * 0.62));
  const displayLabels = buckets.map((bucket) => axisLabel(bucket.label, slot));
  const widest = displayLabels.reduce((max, text) => Math.max(max, labelWidth(text)), 0);
  const labelStep = slot > 0 && widest > slot * 0.9 ? Math.ceil(widest / (slot * 0.9)) : 1;

  const legend = [];
  const seen = new Set();
  for (const bucket of buckets) {
    for (const segment of bucket.segments || []) {
      const key = `${segment.color || ""}|${segmentHex(segment)}`;
      if (seen.has(key)) continue;
      seen.add(key);
      legend.push({ key, name: segment.color || "未命名", hex: segmentHex(segment) });
    }
  }

  return (
    <div className="space-y-4">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="按颜色堆叠的消耗柱状图" className="w-full">
        {[0.25, 0.5, 0.75, 1].map((mark) => {
          const y = padT + innerH * (1 - mark);
          return (
            <g key={mark}>
              <line x1={padL} x2={width - 8} y1={y} y2={y} stroke="#E5E5EA" strokeWidth="1" />
              <text x={padL - 6} y={y + 4} textAnchor="end" fill="#86868B" fontSize="11">
                {Math.round(max * mark)}
              </text>
            </g>
          );
        })}
        {buckets.map((bucket, index) => {
          const x = padL + index * slot + (slot - barW) / 2;
          let y = padT + innerH;
          const grams = Number(bucket.grams) || 0;
          const segments = grams > 0 ? bucket.segments || [] : [];
          return (
            <g key={bucket.key || index}>
              <title>{bucket.label}</title>
              {segments.map((segment, segIndex) => {
                const segGrams = Number(segment.grams) || 0;
                const h = (segGrams / max) * innerH;
                y -= h;
                const hex = segmentHex(segment);
                return (
                  <rect
                    key={`${bucket.key}-${segIndex}`}
                    x={x}
                    y={y}
                    width={barW}
                    height={Math.max(h, 0)}
                    fill={hex}
                    stroke={hex === "#FFFFFF" ? "#D2D2D7" : "none"}
                  >
                    <title>{`${bucket.label} ${segment.color || ""} ${segment.brand || ""} ${segGrams}g`}</title>
                  </rect>
                );
              })}
              {(buckets.length - 1 - index) % labelStep === 0 ? (
                <text x={x + barW / 2} y={height - 14} textAnchor="middle" fill="#86868B" fontSize="11">
                  {displayLabels[index]}
                  <title>{bucket.label}</title>
                </text>
              ) : null}
            </g>
          );
        })}
      </svg>
      {legend.length > 0 ? (
        <ul className="flex flex-wrap gap-x-4 gap-y-2 text-sm text-gray-600">
          {legend.map((item) => (
            <li key={item.key} className="flex items-center gap-2">
              <span className="inline-block h-3 w-3 rounded-full" style={{ backgroundColor: item.hex }} />
              {item.name}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-gray-500">这个范围内还没有消耗。</p>
      )}
    </div>
  );
}
