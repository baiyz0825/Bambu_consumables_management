import Link from "next/link";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";

const ENTRIES = [
  {
    href: "/settings/color-mappings",
    title: "颜色映射",
    description: "把 AMS 颜色码（如 FFFFFF / FFFFFFFF）映射成“白色 / 灰色”，用于库存匹配与自动扣减。",
    action: "去管理颜色映射"
  },
  {
    href: "/settings/material-debug",
    title: "材料调试",
    description: "按颜色码或材质查询匹配库存，排查识别和扣减问题。",
    action: "打开调试工具"
  }
];

export default function Page() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">设置</h1>
        <p className="text-sm text-muted-foreground">颜色映射与材料调试入口。</p>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {ENTRIES.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className="block rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Card className="h-full transition-colors hover:bg-accent/40">
              <CardHeader>
                <CardTitle>{item.title}</CardTitle>
                <CardDescription>{item.description}</CardDescription>
              </CardHeader>
              <CardContent>
                <span className="text-sm font-medium">{item.action}</span>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
