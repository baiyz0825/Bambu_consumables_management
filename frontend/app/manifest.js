// PWA manifest（Next.js 15 App Router 支持 app/manifest.js 自动生成 /manifest.webmanifest）
export default function manifest() {
  return {
    id: "/",
    name: "拓竹耗材管理系统",
    short_name: "耗材管理",
    description: "拓竹打印机耗材库存与打印任务管理（局域网 MQTT 实时同步）",
    start_url: "/",
    scope: "/",
    display: "standalone",
    // 优先独立窗口，其次最小 UI（部分浏览器不支持 standalone 时回落）
    display_override: ["standalone", "minimal-ui"],
    background_color: "#0a0e1a",
    theme_color: "#0a0e1a",
    categories: ["productivity", "utilities"],
    lang: "zh-CN",
    dir: "ltr",
    icons: [
      {
        src: "/icons/icon-192.png",
        sizes: "192x192",
        type: "image/png",
        purpose: "any"
      },
      {
        src: "/icons/icon-256.png",
        sizes: "256x256",
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
    ],
    shortcuts: [
      { name: "打印机", short_name: "打印机", url: "/printers" },
      { name: "库存", short_name: "库存", url: "/stocks" },
      { name: "任务历史", short_name: "任务", url: "/jobs" }
    ]
  };
}
