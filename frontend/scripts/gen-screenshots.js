#!/usr/bin/env node
/**
 * 截取新功能截图脚本。
 *
 * 用 Chrome headless 截取：
 * 1. 移动端视图（375x812，展示底部 Tab Bar）
 * 2. 暗色主题视图（通过 CDP 注入 localStorage）
 *
 * 依赖：Google Chrome（macOS）
 */

import { execSync } from "node:child_process";
import { existsSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const imgDir = join(__dirname, "..", "..", "docs", "images");

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const BASE = "http://localhost:3000";

if (!existsSync(imgDir)) mkdirSync(imgDir, { recursive: true });

function shot(url, out, { width = 1280, height = 800, mobile = false, dark = false } = {}) {
  // 通过 --virtual-time-budget 等待页面渲染，--force-color-profile 强制颜色
  const args = [
    `--headless=new`,
    `--disable-gpu`,
    `--no-sandbox`,
    `--hide-scrollbars`,
    `--force-color-profile=srgb`,
    `--window-size=${width},${height}`,
    `--virtual-time-budget=8000`, // 等 8s 让 Next.js 完成渲染
  ];

  if (dark) {
    // 通过 force-dark-color 并注入 prefers-color-scheme
    args.push(`--force-dark-color`);
  }

  // 用 user-agent 模拟移动端，触发移动端布局（但 Tailwind 是按窗口宽度响应式，
  // 所以 window-size=375 已经足够触发 md: 断点以下的移动端布局）
  if (mobile) {
    args.push(
      `--user-agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"`
    );
  }

  args.push(`--screenshot=${out}`);
  args.push(url);

  console.log(`  shooting ${out} (${width}x${height}${mobile ? " mobile" : ""}${dark ? " dark" : ""})...`);
  try {
    execSync(`"${CHROME}" ${args.join(" ")}`, { stdio: "pipe", timeout: 60000 });
    if (existsSync(out)) {
      const size = execSync(`stat -f%z "${out}"`).toString().trim();
      console.log(`    ✓ ${out} (${size} bytes)`);
    } else {
      console.log(`    ✗ not generated`);
    }
  } catch (e) {
    console.log(`    ✗ failed: ${e.message?.slice(0, 100)}`);
  }
}

// 暗色主题注入脚本：通过 Chrome 的 --data-path 预设 localStorage 不方便，
// 改用 URL 访问 + 短暂等待的方式。但 next-themes 首次访问走 system，
// 无法直接截暗色。我们改用一个 trick：先截移动端（亮色）展示 Tab Bar。

console.log("截取新功能截图：");

// 1. 移动端仪表盘（375x812，展示底部 Tab Bar + 响应式布局）
shot(`${BASE}/`, join(imgDir, "mobile-dashboard.png"), {
  width: 375,
  height: 812,
  mobile: true
});

// 2. 移动端打印机页（展示扫描按钮 + 移动端布局）
shot(`${BASE}/printers`, join(imgDir, "mobile-printers.png"), {
  width: 375,
  height: 812,
  mobile: true
});

// 3. 移动端库存页（展示 OCR 按钮 + 移动端布局）
shot(`${BASE}/stocks`, join(imgDir, "mobile-stocks.png"), {
  width: 375,
  height: 812,
  mobile: true
});

// 4. 桌面端打印机页（展示新增的「扫描局域网」按钮）
shot(`${BASE}/printers`, join(imgDir, "printers-v2.png"), {
  width: 1280,
  height: 800
});

// 5. 桌面端库存页（展示新增的「拍照识别」按钮）
shot(`${BASE}/stocks`, join(imgDir, "stocks-v2.png"), {
  width: 1280,
  height: 800
});

console.log("\n截图完成。");
console.log("注：暗色主题和 OCR/mDNS 交互式截图需手动截取后放入 docs/images/");
