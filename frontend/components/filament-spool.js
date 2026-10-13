"use client";

import { cn } from "../lib/utils";

function normalizeHex(value) {
  const raw = String(value || "").trim();
  if (!raw) return null;
  const hex = raw.startsWith("#") ? raw : `#${raw}`;
  return /^#[0-9A-Fa-f]{6}$/.test(hex) ? hex.toUpperCase() : null;
}

/**
 * 侧面看的耗材卷：法兰是浅灰塑料，绕线用耗材本色，轴心是黑的。
 * colors 为一段或多段 { hex, portion }。portion 只决定色带比例，余量由 percent 决定绕线厚度。
 */
export function FilamentSpool({ colors, percent = 0, title, className, size = 168 }) {
  const list = (Array.isArray(colors) ? colors : [{ hex: colors, portion: 1 }])
    .map((item) => ({
      hex: normalizeHex(typeof item === "string" ? item : item?.hex) || "#C7C7CC",
      portion: Math.max(0, Number(typeof item === "string" ? 1 : item?.portion) || 0)
    }))
    .filter((item) => item.portion > 0);
  const bands = list.length > 0 ? list : [{ hex: "#C7C7CC", portion: 1 }];
  const portionSum = bands.reduce((sum, item) => sum + item.portion, 0) || 1;
  const fill = Math.max(0, Math.min(100, Number(percent) || 0));
  const shown = Math.round(fill);

  const cx = 96;
  const cy = 88;
  const outer = 58;
  const core = 18;
  const depth = 28;
  const thickness = 6 + ((outer - core - 8) * fill) / 100;
  const ring = core + thickness / 2 + 2;

  let cursor = 0;
  const sideBands = bands.map((band) => {
    const height = (outer * 2 * band.portion) / portionSum;
    const y = cy - outer + cursor;
    cursor += height;
    return { ...band, y, height };
  });

  const label = title || `剩余 ${shown}%`;

  return (
    <svg
      width={size}
      height={size * 0.86}
      viewBox="0 0 200 172"
      role="img"
      aria-label={label}
      className={cn("shrink-0", className)}
    >
      <ellipse cx={cx + depth} cy={cy} rx={outer + 6} ry={outer + 6} fill="#D1D1D6" />
      <ellipse cx={cx + depth} cy={cy} rx={core} ry={core} fill="#1D1D1F" />
      {sideBands.map((band) => (
        <rect key={`${band.hex}-${band.y}`} x={cx} y={band.y} width={depth} height={band.height} fill={band.hex} />
      ))}
      <circle cx={cx} cy={cy} r={outer + 8} fill="#F5F5F7" stroke="#D2D2D7" strokeWidth="1" />
      <circle cx={cx} cy={cy} r={outer + 2} fill="none" stroke="#E5E5EA" strokeWidth="6" />
      <circle
        cx={cx}
        cy={cy}
        r={ring}
        fill="none"
        stroke={bands.length === 1 ? bands[0].hex : "none"}
        strokeWidth={thickness}
      />
      {bands.length > 1
        ? bands.map((band, index) => {
            const start = bands.slice(0, index).reduce((sum, item) => sum + item.portion, 0) / portionSum;
            const span = band.portion / portionSum;
            const c = 2 * Math.PI * ring;
            return (
              <circle
                key={`${band.hex}-${index}`}
                cx={cx}
                cy={cy}
                r={ring}
                fill="none"
                stroke={band.hex}
                strokeWidth={thickness}
                strokeDasharray={`${c * span} ${c * (1 - span)}`}
                strokeDashoffset={-c * start}
                transform={`rotate(-90 ${cx} ${cy})`}
              />
            );
          })
        : null}
      {bands.map((band) =>
        normalizeHex(band.hex) === "#FFFFFF" ? (
          <circle
            key={`edge-${band.hex}`}
            cx={cx}
            cy={cy}
            r={ring + thickness / 2}
            fill="none"
            stroke="#D2D2D7"
            strokeWidth="1"
          />
        ) : null
      )}
      <circle cx={cx} cy={cy} r={core + 1} fill="#1D1D1F" />
      <circle cx={cx} cy={cy} r={core - 7} fill="#000000" />
      <text
        x={cx}
        y={cy + 5}
        textAnchor="middle"
        fill="#F5F5F7"
        fontSize="15"
        fontFamily="-apple-system, BlinkMacSystemFont, PingFang SC, sans-serif"
        fontWeight="600"
      >
        {shown}%
      </text>
    </svg>
  );
}

export function spoolPercent(remainingGrams, rollWeightGrams) {
  const roll = Number(rollWeightGrams) || 0;
  const remaining = Number(remainingGrams) || 0;
  if (roll <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round((remaining / roll) * 100)));
}
