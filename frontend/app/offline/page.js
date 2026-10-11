import Link from "next/link";

import { Button } from "../../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";

export const metadata = {
  title: "离线 · 耗材管理系统"
};

/**
 * 离线兜底页：Service Worker 在网络不可用时展示。
 *
 * 页面本身会被预缓存，因此不依赖任何网络请求（不使用客户端数据获取）。
 */
export default function OfflinePage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">当前离线</h1>
        <p className="text-sm text-muted-foreground">
          未能连接到服务，可能是后端未启动或网络不可达。
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">可以这样做</CardTitle>
          <CardDescription>已缓存的页面仍可打开；实时数据需要恢复连接后查看。</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2 sm:flex-row">
          <Button asChild variant="outline" className="w-full sm:w-auto">
            <Link href="/">返回仪表盘</Link>
          </Button>
          <Button asChild variant="outline" className="w-full sm:w-auto">
            <Link href="/printers">查看打印机</Link>
          </Button>
          <Button asChild variant="outline" className="w-full sm:w-auto">
            <Link href="/settings">前往设置</Link>
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
