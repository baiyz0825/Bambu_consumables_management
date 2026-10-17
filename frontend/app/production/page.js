import Link from "next/link";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";

const ENTRIES = [
  {
    href: "/production/merge",
    title: "合盘向导",
    description: "把多盘不同颜色的切片合成一个可连续打印的文件，自动注入换盘码、重写耗材元数据。",
    badge: "核心"
  },
  {
    href: "/production/gcodes",
    title: "产物库",
    description: "查看已生成的 G-code 文件，下载或删除，并直接发起下发打印。",
    badge: "文件"
  },
  {
    href: "/settings/swap-codes",
    title: "换盘码管理",
    description: "查看与调整换盘 G-code 预设参数，实时渲染预览与耗时估算。",
    badge: "配置"
  }
];

export default function Page() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">生产</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          合盘、下发与换盘码配置。合盘产物可直接在「产物库」中下发到打印机。
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {ENTRIES.map((item) => (
          <Link key={item.href} href={item.href} className="group">
            <Card className="h-full transition-colors group-hover:border-[#0071e3]/50 dark:group-hover:border-[#0a84ff]/50">
              <CardHeader>
                <div className="flex items-center justify-between gap-2">
                  <CardTitle className="text-base">{item.title}</CardTitle>
                  <span className="rounded-full bg-[#0071e3]/10 px-2 py-0.5 text-[11px] text-[#0071e3] dark:bg-[#0a84ff]/10 dark:text-[#0a84ff]">
                    {item.badge}
                  </span>
                </div>
                <CardDescription>{item.description}</CardDescription>
              </CardHeader>
              <CardContent>
                <span className="text-sm font-medium text-[#0071e3] dark:text-[#0a84ff]">进入 →</span>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
