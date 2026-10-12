# frontend（Next.js 15）

界面是 App Router + Tailwind。页面、按钮和自适应说明见仓库根目录 [README](../README.md) 的「界面一览」。

## 页面

| 路径 | 说明 |
|---|---|
| `/` | 仪表盘 |
| `/printers` | 打印机、扫描、托盘绑定 |
| `/stocks` | 库存列表、新增、归档 |
| `/stocks/[id]` | 库存详情与流水 |
| `/jobs` | 任务历史 |
| `/jobs/[id]` | 任务详情与扣料 |
| `/reports` | 按日 / 按月报告 |
| `/settings` | 设置入口 |
| `/settings/color-mappings` | AMS 颜色映射 |
| `/settings/material-debug` | 材料匹配调试 |
| `/offline` | 离线兜底 |

手机和 iPad 竖屏（宽度 &lt; 1024px）使用底部标签；更宽的屏幕使用顶部导航。

## 本地运行

```bash
npm install
export NEXT_PUBLIC_API_BASE_URL="http://localhost:8000"
npm run dev -- --port 3000
```

PWA 图标：

```bash
node scripts/gen-icons.js
```
