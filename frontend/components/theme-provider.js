"use client";

import { ThemeProvider as NextThemesProvider } from "next-themes";

/**
 * 主题 Provider。
 *
 * - attribute="class"：在 <html> 上切换 .dark 类（与 tailwind.config 的 darkMode: ["class"] 配合）
 * - defaultTheme="system"：默认跟随系统 prefers-color-scheme
 * - enableSystem：允许 system 主题
 * - disableTransitionOnChange：切换主题瞬间禁用过渡，避免背景色 fade 抖动
 * - storageKey="bbs-theme"：localStorage 键名，持久化用户选择
 */
export function ThemeProvider({ children }) {
  return (
    <NextThemesProvider
      attribute="class"
      defaultTheme="system"
      enableSystem
      disableTransitionOnChange
      storageKey="bbs-theme"
    >
      {children}
    </NextThemesProvider>
  );
}
