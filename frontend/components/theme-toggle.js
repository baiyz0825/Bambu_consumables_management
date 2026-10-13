"use client";

import { useEffect, useState } from "react";
import { useTheme } from "next-themes";

import { cn } from "../lib/utils";

/**
 * 主题切换按钮。
 *
 * - 三态：light / dark / system，循环切换
 * - 内联 SVG 图标，避免引入额外图标库
 * - mounted 防止 SSR/CSR 不一致导致的 hydration mismatch
 */
export function ThemeToggle({ className }) {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  // 在客户端挂载前显示占位，避免 hydration mismatch
  if (!mounted) {
    return (
      <button
        type="button"
        aria-label="切换主题"
        className={cn(
          "inline-flex h-11 w-11 items-center justify-center rounded-full bg-[#f5f5f7] text-foreground opacity-50 lg:h-9 lg:w-9 dark:bg-[#2c2c2e] dark:text-white",
          className
        )}
      >
        <span className="h-4 w-4" />
      </button>
    );
  }

  const isDark = theme === "dark";

  const toggle = () => {
    // light -> dark -> system -> light
    const next = isDark ? "system" : theme === "system" ? "light" : "dark";
    setTheme(next);
  };

  const label = theme === "system" ? "跟随系统" : isDark ? "深色" : "浅色";

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={`切换主题（当前：${label}）`}
      title={`主题：${label}`}
      className={cn(
        "inline-flex h-11 w-11 cursor-pointer items-center justify-center rounded-full bg-[#f5f5f7] text-foreground transition-colors duration-200 hover:bg-[#e8e8ed] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0071e3] active:scale-[0.98] lg:h-9 lg:w-9 dark:bg-[#2c2c2e] dark:text-white dark:hover:bg-[#3a3a3c] dark:focus-visible:ring-[#0a84ff]",
        className
      )}
    >
      {theme === "system" ? (
        // 系统：笔记本图标
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <rect x="2" y="4" width="20" height="14" rx="2" />
          <path d="M2 20h20" />
        </svg>
      ) : isDark ? (
        // 深色：月亮
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />
        </svg>
      ) : (
        // 浅色：太阳
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
        </svg>
      )}
    </button>
  );
}
