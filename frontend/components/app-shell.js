"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "../lib/utils";
import { ThemeToggle } from "./theme-toggle";

/**
 * 导航项配置：同时供桌面顶部 nav 和移动端底部 Tab Bar 复用。
 * 每项带 SVG 图标，方便移动端 Tab Bar 视觉区分。
 */
const NAV = [
  {
    href: "/",
    label: "仪表盘",
    icon: (
      <svg
        xmlns="http://www.w3.org/2000/svg"
        width="20"
        height="20"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <rect x="3" y="3" width="7" height="9" />
        <rect x="14" y="3" width="7" height="5" />
        <rect x="14" y="12" width="7" height="9" />
        <rect x="3" y="16" width="7" height="5" />
      </svg>
    )
  },
  {
    href: "/printers",
    label: "打印机",
    icon: (
      <svg
        xmlns="http://www.w3.org/2000/svg"
        width="20"
        height="20"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M6 9V2h12v7" />
        <path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2" />
        <rect x="6" y="14" width="12" height="8" />
      </svg>
    )
  },
  {
    href: "/stocks",
    label: "库存",
    icon: (
      <svg
        xmlns="http://www.w3.org/2000/svg"
        width="20"
        height="20"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M21 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v3" />
        <path d="M3 8a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v0a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" />
        <path d="M5 10v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V10" />
        <path d="M9 14h6" />
      </svg>
    )
  },
  {
    href: "/jobs",
    label: "任务",
    icon: (
      <svg
        xmlns="http://www.w3.org/2000/svg"
        width="20"
        height="20"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" />
        <path d="M14 2v6h6" />
        <path d="M9 13h6M9 17h4" />
      </svg>
    )
  },
  {
    href: "/reports",
    label: "报告",
    icon: (
      <svg
        xmlns="http://www.w3.org/2000/svg"
        width="20"
        height="20"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M3 3v18h18" />
        <path d="M7 16l4-6 3 4 5-8" />
      </svg>
    )
  },
  {
    href: "/settings",
    label: "设置",
    icon: (
      <svg
        xmlns="http://www.w3.org/2000/svg"
        width="20"
        height="20"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2Z" />
        <circle cx="12" cy="12" r="3" />
      </svg>
    )
  }
];

function isNavActive(pathname, href) {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

function NavLink({ href, label, active }) {
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "shrink-0 rounded-full px-3 py-2 text-sm transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0071e3] dark:focus-visible:ring-[#0a84ff]",
        active
          ? "bg-[#0071e3]/10 font-medium text-[#0071e3] dark:bg-[#0a84ff]/10 dark:text-[#0a84ff]"
          : "text-muted-foreground hover:bg-[#f5f5f7] hover:text-foreground dark:hover:bg-white/10 dark:hover:text-white"
      )}
    >
      {label}
    </Link>
  );
}

function MobileTabItem({ href, label, icon, active }) {
  return (
    <Link
      href={href}
      className={cn(
        "flex min-h-11 min-w-0 flex-1 flex-col items-center justify-center gap-0.5 px-0.5 py-1.5 text-[11px] transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#0071e3] dark:focus-visible:ring-[#0a84ff] sm:text-xs",
        active
          ? "font-medium text-[#0071e3] dark:text-[#0a84ff]"
          : "text-muted-foreground hover:text-foreground"
      )}
      aria-current={active ? "page" : undefined}
    >
      <span
        className={cn(
          "flex h-7 w-9 items-center justify-center rounded-full",
          active && "bg-[#0071e3]/10 text-[#0071e3] dark:bg-[#0a84ff]/10 dark:text-[#0a84ff]"
        )}
      >
        {icon}
      </span>
      <span className="w-full truncate text-center leading-none">{label}</span>
    </Link>
  );
}

export function AppShell({ children }) {
  const pathname = usePathname() || "/";

  return (
    <div className="min-h-safe">
      {/* 桌面顶部导航（md+ 显示）；pt-safe 为 iOS 刘海/PWA 状态栏留白 */}
      <header className="sticky top-0 z-40 border-b border-black/[0.06] bg-white pt-safe dark:border-white/10 dark:bg-black">
        <div className="container mx-auto flex min-h-14 flex-wrap items-center justify-between gap-x-3 gap-y-1 px-6 py-2 md:px-8">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex shrink-0 items-center gap-2 font-semibold tracking-tight">
              <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-[#0071e3] text-white dark:bg-[#0a84ff]">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path d="M7 7h10v4a5 5 0 0 1-10 0V7Z" stroke="currentColor" strokeWidth="2" />
                  <path d="M12 16v4M8 20h8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                </svg>
              </span>
              耗材管理
            </div>
            <nav className="hidden min-w-0 items-center gap-0.5 lg:flex" aria-label="主导航">
              {NAV.map((n) => (
                <NavLink key={n.href} href={n.href} label={n.label} active={isNavActive(pathname, n.href)} />
              ))}
            </nav>
          </div>
          <div className="ml-auto flex shrink-0 items-center gap-2">
            <span className="hidden text-xs text-muted-foreground xl:inline">Docker / 局域网 MQTT</span>
            <ThemeToggle />
          </div>
        </div>
      </header>

      {/* 主内容区：lg 以下为底部 Tab Bar 留出高度与安全区 */}
      <main className="container mx-auto min-w-0 px-6 pb-24 pt-6 md:px-8 lg:pb-8">{children}</main>

      {/* 手机与 iPad 竖屏底部 Tab；iPad 横屏 / 桌面（lg+）改用顶部导航 */}
      <nav
        className="fixed inset-x-0 bottom-0 z-40 border-t border-black/[0.06] bg-white dark:border-white/10 dark:bg-black lg:hidden"
        style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
        aria-label="主导航"
      >
        <div className="flex items-stretch">
          {NAV.map((n) => (
            <MobileTabItem
              key={n.href}
              href={n.href}
              label={n.label}
              icon={n.icon}
              active={isNavActive(pathname, n.href)}
            />
          ))}
        </div>
      </nav>
    </div>
  );
}
