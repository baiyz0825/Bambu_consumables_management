"use client";

import { useEffect } from "react";

/**
 * 注册 Service Worker（仅 production）。
 *
 * 开发环境不注册，避免缓存干扰热更新与调试。
 * 注册失败静默处理：PWA 属于增强能力，不应影响主功能。
 */
export function PwaRegister() {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production") return;
    if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) return;

    const onLoad = () => {
      navigator.serviceWorker
        .register("/sw.js")
        .catch((err) => {
          console.warn("service worker register failed", err);
        });
    };

    if (document.readyState === "complete") {
      onLoad();
    } else {
      window.addEventListener("load", onLoad);
      return () => window.removeEventListener("load", onLoad);
    }
  }, []);

  return null;
}
