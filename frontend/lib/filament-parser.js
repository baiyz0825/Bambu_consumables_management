/**
 * 耗材标签 OCR 文本解析器。
 *
 * 从 Tesseract.js 识别出的原始文本中，用正则提取结构化字段：
 * - material：材质（PLA / PETG / TPU / ABS / ASA / PC / PA-CF ...）
 * - weight_grams：单卷重量（克）
 * - color_name：颜色名称（中英文）
 * - brand：品牌
 * - confidence：整体置信度（0-100）
 *
 * 拓竹耗材标签常见格式（参考）：
 *   "PLA Basic Black 1.00kg"
 *   "PETG HF White 1kg Bambu Lab"
 *   "TPU 95A Red 1.0kg"
 *   "PLA Matte Cyan 1kg"
 *
 * 解析失败的字段返回 null，由调用方决定是否预填。
 */

// 材质关键词（按长度降序匹配，避免 PLA 匹配到 PLA-CF 的 PLA 部分）
const MATERIAL_PATTERNS = [
  // 复合材质（带后缀，优先匹配）
  /PETG[\s-]*(?:HF|CF|HF-Aero)/i,
  /PLA[\s-]*(?:Aero|Matte|Silk|Glitter|Marble|Wood|Metal|Rainbow|CF|Impact)/i,
  /PA[\s-]*(?:CF|HT|12-CF)/i,
  // 基础材质
  /\bPETG\b/i,
  /\bPLA\b/i,
  /\bTPU\b/i,
  /\bTPE\b/i,
  /\bABS\b/i,
  /\bASA\b/i,
  /\bPC\b/i,
  /\bPVA\b/i,
  /\bHIPS\b/i,
  /\bNylon\b/i,
  /\bPA\b/i, // 必须放最后，避免匹配 PA-CF
  /\bPP\b/i,
  /\bPEEK\b/i,
];

// 拓竹常见材质 → 标准化名
const MATERIAL_NORMALIZE = {
  "petg hf": "PETG-HF",
  "petg-cf": "PETG-CF",
  "petg hf-aero": "PETG-HF-Aero",
  "pla aero": "PLA-Aero",
  "pla matte": "PLA-Matte",
  "pla silk": "PLA-Silk",
  "pla glitter": "PLA-Glitter",
  "pla marble": "PLA-Marble",
  "pla wood": "PLA-Wood",
  "pla metal": "PLA-Metal",
  "pla rainbow": "PLA-Rainbow",
  "pla-cf": "PLA-CF",
  "pla impact": "PLA-Impact",
  "pa-cf": "PA-CF",
  "pa-ht": "PA-HT",
  "pa12-cf": "PA12-CF",
};

/**
 * 颜色名 → hex 映射（中英文）。
 * 用于从 OCR 文本中的颜色名推断 hex 色值。
 */
export const COLOR_NAME_TO_HEX = {
  // 英文
  black: "#000000",
  white: "#FFFFFF",
  red: "#E60012",
  orange: "#FF6600",
  yellow: "#FFE500",
  green: "#00C853",
  blue: "#0066FF",
  cyan: "#00BFFF",
  purple: "#8E24AA",
  violet: "#7C3AED",
  magenta: "#FF00FF",
  pink: "#FF69B4",
  gray: "#9E9E9E",
  grey: "#9E9E9E",
  brown: "#795548",
  gold: "#FFD700",
  silver: "#C0C0C0",
  beige: "#F5F5DC",
  ivory: "#FFFFF0",
  // 中文
  黑: "#000000",
  黑色: "#000000",
  白: "#FFFFFF",
  白色: "#FFFFFF",
  红: "#E60012",
  红色: "#E60012",
  橙: "#FF6600",
  橙色: "#FF6600",
  黄: "#FFE500",
  黄色: "#FFE500",
  绿: "#00C853",
  绿色: "#00C853",
  蓝: "#0066FF",
  蓝色: "#0066FF",
  青: "#00BFFF",
  青色: "#00BFFF",
  紫: "#8E24AA",
  紫色: "#8E24AA",
  灰: "#9E9E9E",
  灰色: "#9E9E9E",
  棕: "#795548",
  棕色: "#795548",
  咖: "#795548",
  咖啡: "#795548",
  粉: "#FF69B4",
  粉色: "#FF69B4",
  金: "#FFD700",
  金色: "#FFD700",
  银: "#C0C0C0",
  银色: "#C0C0C0",
  // 拓竹特定色名
  midnight: "#1A1A2E",
  "teal green": "#008080",
  beige grey: "#D4C5B9",
  "dark gray": "#4A4A4A",
  "light gray": "#D3D3D3",
  "dark blue": "#003366",
  "light blue": "#ADD8E6",
};

const COLOR_NAME_PATTERNS = Object.keys(COLOR_NAME_TO_HEX).sort(
  (a, b) => b.length - a.length
);

// 品牌关键词
const BRAND_PATTERNS = [
  /Bambu[\s-]?Lab/i,
  /Polymaker/i,
  /\beSun\b/i,
  /Sunlu/i,
  /3D[\s-]?GBrand/i,
  /拓竹/i,
  /极光/i,
  /eRefill/i,
  /Verbatim/i,
  /Prusament/i,
];

/**
 * 从 OCR 文本中提取结构化耗材信息。
 *
 * @param {string} text - Tesseract 识别的原始文本
 * @param {number} confidence - Tesseract 平均置信度（0-100）
 * @returns {{material: string|null, weight_grams: number|null, color_name: string|null, color_hex: string|null, brand: string|null, confidence: number, raw_text: string}}
 */
export function parseFilamentLabel(text, confidence = 0) {
  const raw = text || "";
  const lower = raw.toLowerCase();

  // 1. 材质
  let material = null;
  for (const pat of MATERIAL_PATTERNS) {
    const m = raw.match(pat);
    if (m) {
      const key = m[0].toLowerCase().replace(/\s+/g, " ").trim();
      material = MATERIAL_NORMALIZE[key] || m[0].toUpperCase().replace(/\s+/g, "-");
      break;
    }
  }

  // 2. 重量（支持 1.00kg / 1kg / 1000g / 1千克 / 1000克）
  let weight_grams = null;
  const weightMatch = raw.match(/(\d+(?:\.\d+)?)\s*(kg|千克|g|克)\b/i);
  if (weightMatch) {
    const num = parseFloat(weightMatch[1]);
    const unit = weightMatch[2].toLowerCase();
    if (unit === "kg" || unit === "千克") {
      weight_grams = Math.round(num * 1000);
    } else {
      weight_grams = Math.round(num);
    }
  }

  // 3. 颜色名（按长度降序匹配，避免 red 抢先匹配到 dark red）
  let color_name = null;
  let color_hex = null;
  for (const name of COLOR_NAME_PATTERNS) {
    // 用 word boundary 匹配英文，中文直接 includes
    if (/^[a-z\s]+$/i.test(name)) {
      const re = new RegExp(`\\b${name.replace(/\s+/g, "\\s+")}\\b`, "i");
      if (re.test(lower)) {
        color_name = name;
        color_hex = COLOR_NAME_TO_HEX[name];
        break;
      }
    } else if (raw.includes(name)) {
      color_name = name;
      color_hex = COLOR_NAME_TO_HEX[name];
      break;
    }
  }

  // 4. 品牌
  let brand = null;
  for (const pat of BRAND_PATTERNS) {
    const m = raw.match(pat);
    if (m) {
      const b = m[0];
      // 标准化常见品牌名
      if (/bambu/i.test(b)) brand = "拓竹";
      else if (/polymaker/i.test(b)) brand = "Polymaker";
      else if (/esun/i.test(b)) brand = "eSun";
      else if (/sunlu/i.test(b)) brand = "Sunlu";
      else if (/拓竹/.test(b)) brand = "拓竹";
      else if (/极光/.test(b)) brand = "极光";
      else brand = b;
      break;
    }
  }

  return {
    material,
    weight_grams,
    color_name,
    color_hex,
    brand,
    confidence: Math.round(confidence || 0),
    raw_text: raw,
  };
}
