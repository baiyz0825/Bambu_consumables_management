/**
 * 耗材标签图像主色调提取。
 *
 * 拓竹耗材标签通常是白底彩字，实际耗材颜色 = 标签上的色块或卷盘本体颜色。
 * 策略：
 * 1. 把图片缩放到 50x50 的小 canvas（性能）
 * 2. 遍历像素，过滤掉接近白色/黑色的背景像素
 * 3. 用简化的颜色量化（每通道压缩到 16 级 = 4bit）
 * 4. 统计频率，取 top-1 作为主色调
 * 5. 同时把 hex 映射到最近的标准颜色名
 *
 * 如果整张图都是白色/黑色（没有彩色信息），返回 null，由调用方降级到 OCR 文本颜色名。
 */

import { COLOR_NAME_TO_HEX } from "./filament-parser";

/**
 * 判断像素是否为背景（接近纯白或纯黑）。
 */
function isBackground(r, g, b, threshold = 30) {
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  // 接近纯白
  if (max > 235 && max - min < 20) return true;
  // 接近纯黑
  if (min < 25) return true;
  // 接近纯灰（无饱和度）
  if (max - min < threshold && max > 200) return true;
  return false;
}

/**
 * 计算两个 RGB 颜色的欧氏距离。
 */
function colorDistance(r1, g1, b1, r2, g2, b2) {
  const dr = r1 - r2;
  const dg = g1 - g2;
  const db = b1 - b2;
  return Math.sqrt(dr * dr + dg * dg + db * db);
}

/**
 * 把 hex 转 RGB。
 */
function hexToRgb(hex) {
  const h = hex.replace("#", "");
  return {
    r: parseInt(h.substring(0, 2), 16),
    g: parseInt(h.substring(2, 4), 16),
    b: parseInt(h.substring(4, 6), 16),
  };
}

/**
 * 从 Image/DataURL 提取主色调 hex。
 *
 * @param {HTMLImageElement|ImageBitmap} image - 已加载的图片对象
 * @returns {{hex: string, rgb: {r,g,b}, name: string|null}|null}
 */
export function extractDominantColor(image) {
  if (typeof document === "undefined") return null;

  const size = 50;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) return null;

  // 绘制缩放后的图
  try {
    ctx.drawImage(image, 0, 0, size, size);
  } catch {
    return null;
  }

  const imageData = ctx.getImageData(0, 0, size, size);
  const data = imageData.data;

  // 颜色量化：每通道压到 16 级 (0-15 * 17)
  const bucket = new Map();
  let totalPixels = 0;

  for (let i = 0; i < data.length; i += 4) {
    const r = data[i];
    const g = data[i + 1];
    const b = data[i + 2];
    const a = data[i + 3];
    if (a < 128) continue; // 透明像素跳过
    if (isBackground(r, g, b)) continue;

    // 量化：每 16 为一桶
    const qr = Math.floor(r / 16) * 16;
    const qg = Math.floor(g / 16) * 16;
    const qb = Math.floor(b / 16) * 16;
    const key = `${qr},${qg},${qb}`;
    bucket.set(key, (bucket.get(key) || 0) + 1);
    totalPixels++;
  }

  // 整张图都是背景色（白色标签纸），无法提取彩色
  if (totalPixels === 0 || bucket.size === 0) return null;

  // 取频率最高的桶
  let bestKey = null;
  let bestCount = 0;
  for (const [key, count] of bucket) {
    if (count > bestCount) {
      bestCount = count;
      bestKey = key;
    }
  }
  if (!bestKey) return null;

  const [r, g, b] = bestKey.split(",").map(Number);

  // 桶中心点的颜色转 hex
  const hex =
    "#" +
    [r, g, b]
      .map((v) => Math.min(255, v + 8).toString(16).padStart(2, "0"))
      .join("")
      .toUpperCase();

  // 映射到最近的标准颜色名
  let name = null;
  let minDist = Infinity;
  for (const [n, h] of Object.entries(COLOR_NAME_TO_HEX)) {
    const { r: sr, g: sg, b: sb } = hexToRgb(h);
    const d = colorDistance(r, g, b, sr, sg, sb);
    if (d < minDist) {
      minDist = d;
      name = n;
    }
  }
  // 距离太远（>120）说明颜色不在标准色板内，不强行映射
  if (minDist > 120) name = null;

  return { hex, rgb: { r, g, b }, name, coverage: bestCount / totalPixels };
}

/**
 * 从 File 对象加载为 HTMLImageElement。
 *
 * @param {File} file
 * @returns {Promise<HTMLImageElement>}
 */
export function loadImageFromFile(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve(img);
    };
    img.onerror = (e) => {
      URL.revokeObjectURL(url);
      reject(e);
    };
    img.src = url;
  });
}
