#!/usr/bin/env node
/**
 * 生成 PWA 图标脚本（无需任何外部 npm 依赖）。
 *
 * 策略：用 Canvas API 需要 node-canvas，避免重依赖。
 * 这里改用「手工 PNG 编码」——直接绘制一个深色背景 + 中央白色「耗」字样
 * 的 PNG（仅用 Node 内置 zlib 压缩）。
 *
 * 生成的 PNG 是 RGBA 8bit，尺寸通过 --size 参数指定。
 * maskable 版本：背景填满整张图（图标内容留出安全区，这里用更大的圆角方块）。
 *
 * 用法：
 *   node scripts/gen-icons.js
 * 输出：
 *   public/icons/icon-192.png
 *   public/icons/icon-512.png
 *   public/icons/icon-maskable-512.png
 *   public/icons/apple-touch-icon.png  (180x180)
 */

import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { deflateSync } from "node:zlib";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const publicDir = join(__dirname, "..", "public", "icons");

// ---------- 最小 PNG 编码器（RGBA）----------

function crc32(buf) {
  let c = ~0;
  for (let i = 0; i < buf.length; i++) {
    c ^= buf[i];
    for (let k = 0; k < 8; k++) {
      c = c & 1 ? (c >>> 1) ^ 0xedb88320 : c >>> 1;
    }
  }
  return ~c >>> 0;
}

function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length, 0);
  const typeBuf = Buffer.from(type, "ascii");
  const crcBuf = Buffer.alloc(4);
  crcBuf.writeUInt32BE(crc32(Buffer.concat([typeBuf, data])), 0);
  return Buffer.concat([len, typeBuf, data, crcBuf]);
}

/**
 * 在 (size x size) 画布上绘制：
 * - 深色圆角矩形背景
 * - 中央白色圆角矩形（"墨卷"造型）
 * - 简化的两个白色方块（代表库存/打印）
 * maskable=true 时背景填满全图，内容缩到 80% 安全区内
 */
function renderIcon(size, { maskable = false } = {}) {
  const rgba = Buffer.alloc(size * size * 4);

  const bgR = 10;
  const bgG = 14;
  const bgB = 26;
  const fgR = 240;
  const fgG = 244;
  const fgB = 250;

  const inset = maskable ? size * 0.1 : 0; // maskable 留出 10% 安全边距
  const radius = size * (maskable ? 0.16 : 0.22);

  function inRoundedRect(x, y, x0, y0, x1, y1, r) {
    if (x < x0 || x > x1 || y < y0 || y > y1) return false;
    const dx = x < x0 + r ? x0 + r - x : x > x1 - r ? x - (x1 - r) : 0;
    const dy = y < y0 + r ? y0 + r - y : y > y1 - r ? y - (y1 - r) : 0;
    if (dx === 0 || dy === 0) return true;
    return dx * dx + dy * dy <= r * r;
  }

  const bgX0 = inset;
  const bgY0 = inset;
  const bgX1 = size - inset;
  const bgY1 = size - inset;

  // 中央白色方块区域（代表"卷"）
  const padX = size * 0.24;
  const padY = size * 0.24;
  const sqX0 = padX;
  const sqY0 = padY;
  const sqX1 = size - padX;
  const sqY1 = size - padY;
  const sqR = size * 0.06;

  // 中间分隔线（两个方块感）
  const midX = size * 0.5;

  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const i = (y * size + x) * 4;
      const inBg = inRoundedRect(x, y, bgX0, bgY0, bgX1, bgY1, radius);
      const inFg = inRoundedRect(x, y, sqX0, sqY0, sqX1, sqY1, sqR) && x >= midX - 1 && x <= midX + 1 === false
        ? inRoundedRect(x, y, sqX0, sqY0, sqX1, sqY1, sqR)
        : false;

      // 画两个方块（左小右大），中间留缝
      const gapW = size * 0.04;
      const inLeft = inRoundedRect(x, y, sqX0, sqY0, midX - gapW, sqY1, sqR);
      const inRight = inRoundedRect(x, y, midX + gapW, sqY0, sqX1, sqY1, sqR);

      let r, g, b, a;
      if (inLeft || inRight) {
        r = fgR; g = fgG; b = fgB; a = 255;
      } else if (inBg) {
        r = bgR; g = bgG; b = bgB; a = 255;
      } else {
        // maskable 模式下圆角外区域也要填满背景色（避免透明被裁剪）
        r = maskable ? bgR : 0;
        g = maskable ? bgG : 0;
        b = maskable ? bgB : 0;
        a = maskable ? 255 : 0;
      }
      rgba[i] = r;
      rgba[i + 1] = g;
      rgba[i + 2] = b;
      rgba[i + 3] = a;
    }
  }

  // PNG 编码
  const sig = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 6; // color type RGBA
  ihdr[10] = 0; // compression
  ihdr[11] = 0; // filter
  ihdr[12] = 0; // interlace

  // 每行前加 filter byte (0)
  const stride = size * 4;
  const raw = Buffer.alloc((stride + 1) * size);
  for (let y = 0; y < size; y++) {
    raw[y * (stride + 1)] = 0;
    rgba.copy(raw, y * (stride + 1) + 1, y * stride, (y + 1) * stride);
  }
  const idat = deflateSync(raw, { level: 9 });

  return Buffer.concat([
    sig,
    chunk("IHDR", ihdr),
    chunk("IDAT", idat),
    chunk("IEND", Buffer.alloc(0))
  ]);
}

mkdirSync(publicDir, { recursive: true });

const targets = [
  { name: "icon-192.png", size: 192, opts: {} },
  { name: "icon-512.png", size: 512, opts: {} },
  { name: "icon-maskable-512.png", size: 512, opts: { maskable: true } },
  { name: "apple-touch-icon.png", size: 180, opts: {} }
];

for (const t of targets) {
  const png = renderIcon(t.size, t.opts);
  const out = join(publicDir, t.name);
  writeFileSync(out, png);
  console.log(`  ✓ ${out} (${png.length} bytes, ${t.size}x${t.size}${t.opts.maskable ? " maskable" : ""})`);
}

console.log("\n图标生成完成。");
