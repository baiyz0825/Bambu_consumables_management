import { fileURLToPath } from "node:url";

// PWA manifest（Next.js 15 App Router 支持 app/manifest.js 自动生成 /manifest.webmanifest）
export default function manifest() {
  return {
    name: "拓竹耗材管理系统",
    short_name: "耗材管理",
    description: "拓竹打印机耗材库存与打印任务管理（局域网 MQTT 实时同步）",
    start_url: "/",
    display: "standalone",
    orientation: "portrait",
    background_color: "#0a0e1a",
    theme_color: "#0a0e1a",
    categories: ["productivity", "utilities"],
    lang: "zh-CN",
    icons: [
      {
        src: "/icons/icon-192.png",
        sizes: "192x192",
        type: "image/png",
        purpose: "any"
      },
      {
        src: "/icons/icon-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "any"
      },
      {
        src: "/icons/icon-maskable-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable"
      }
    ]
  };
}

// 仅用于消除 node 警告（manifest 导出不引用 fileURLToPath，留空即可）
void fileURLToPath;
