/* eslint-disable no-restricted-globals */
/**
 * 耗材管理系统 Service Worker（PWA 离线支持）。
 *
 * 策略：
 * - App Shell 预缓存：安装时缓存首页/主要路由/图标，离线也能打开界面骨架；
 * - 导航请求：network-first，网络不可用时回落到 /offline 页面；
 * - 静态资源（/_next/static 等）：stale-while-revalidate，先取缓存再后台更新；
 * - 非 GET、跨域（后端 API :8000）请求不拦截，交给浏览器默认处理。
 *
 * 注意：仅在 production 注册（见 components/pwa-register.js），避免影响开发热更新。
 */

const VERSION = "v1";
const SHELL_CACHE = `app-shell-${VERSION}`;
const RUNTIME_CACHE = `runtime-${VERSION}`;
const OFFLINE_URL = "/offline";

// 预缓存的 App Shell：页面路由 + manifest + 图标
const APP_SHELL = [
  "/",
  OFFLINE_URL,
  "/printers",
  "/stocks",
  "/jobs",
  "/reports",
  "/settings",
  "/manifest.webmanifest",
  "/icons/icon-192.png",
  "/icons/icon-512.png"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      // 单个资源 404 不应导致整体安装失败
      .then((cache) => Promise.allSettled(APP_SHELL.map((url) => cache.add(url))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((k) => k !== SHELL_CACHE && k !== RUNTIME_CACHE)
            .map((k) => caches.delete(k))
        )
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);
  // 跨域（后端 API 在独立端口）不拦截
  if (url.origin !== self.location.origin) return;
  // Next.js 数据/构建请求不缓存，避免脏数据
  if (url.pathname.startsWith("/_next/") && !url.pathname.startsWith("/_next/static")) return;

  // 页面导航：网络优先，离线回落 /offline
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req)
        .then((res) => {
          if (res && res.ok) {
            const copy = res.clone();
            caches.open(RUNTIME_CACHE).then((cache) => cache.put(req, copy));
          }
          return res;
        })
        .catch(async () => {
          const cached = await caches.match(req);
          if (cached) return cached;
          const offline = await caches.match(OFFLINE_URL);
          return offline || new Response("离线且无缓存", { status: 503 });
        })
    );
    return;
  }

  // 静态资源：stale-while-revalidate
  event.respondWith(
    caches.match(req).then((cached) => {
      const network = fetch(req)
        .then((res) => {
          if (res && res.ok) {
            const copy = res.clone();
            caches.open(RUNTIME_CACHE).then((cache) => cache.put(req, copy));
          }
          return res;
        })
        .catch(() => cached);
      return cached || network;
    })
  );
});
