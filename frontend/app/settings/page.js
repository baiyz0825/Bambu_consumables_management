import Link from "next/link";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";

const ENTRIES = [
  {
    href: "/settings/cloud",
    title: "拓竹云账号",
    description: "登录后，人离开局域网时仍能收到同一台打印机的状态。序列号相同不会再出现第二条记录。",
    action: "登录或查看已绑定的打印机",
    tint: "bg-[hsl(var(--tint-blue))] text-[hsl(var(--tint-blue-ink))]"
  },
  {
    href: "/settings/color-mappings",
    title: "颜色映射",
    description: "把 AMS 颜色码（如 FFFFFF / FFFFFFFF）映射成“白色 / 灰色”，用于库存匹配与自动扣减。",
    action: "去管理颜色映射",
    tint: "bg-[hsl(var(--tint-purple))] text-[hsl(var(--tint-purple-ink))]"
  },
  {
    href: "/settings/material-debug",
    title: "材料调试",
    description: "按颜色码或材质查询匹配库存，排查识别和扣减问题。",
    action: "打开调试工具",
    tint: "bg-[hsl(var(--tint-orange))] text-[hsl(var(--tint-orange-ink))]"
  },
  {
    href: "/settings/prices",
    title: "品牌单价",
    description: "成本报告按品牌的元/千克估算。",
    action: "去设置品牌单价",
    tint: "bg-secondary text-secondary-foreground"
  }
];

export default function Page() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">设置</h1>
        <p className="text-sm text-muted-foreground">拓竹云账号、颜色映射与材料调试。</p>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {ENTRIES.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className="block rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Card className="h-full transition-[transform,box-shadow] duration-200 hover:-translate-y-0.5 hover:shadow-[var(--shadow-card)]">
              <CardHeader>
                <div className={`mb-3 flex h-10 w-10 items-center justify-center rounded-2xl text-sm font-semibold ${item.tint}`}>
                  {item.title.slice(0, 1)}
                </div>
                <CardTitle>{item.title}</CardTitle>
                <CardDescription>{item.description}</CardDescription>
              </CardHeader>
              <CardContent>
                <span className="text-sm font-medium text-primary">{item.action}</span>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
