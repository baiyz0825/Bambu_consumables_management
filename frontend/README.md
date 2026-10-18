# frontend（Next.js 15）

界面是 App Router + Tailwind。页面、按钮和自适应说明见 [界面](../docs/界面.md)。

## 页面

| 路径 | 说明 |
|---|---|
| `/` | 仪表盘 |
| `/printers` | 打印机、扫描、托盘绑定 |
| `/printers/[id]` | 设备详情：实时数据（SSE）、数字孪生、设备控制、HMS 故障 |
| `/production` | 生产模块入口 |
| `/production/merge` | 合盘向导：上传 → 自动统计 → 配置 → 生成 → 下载 |
| `/production/gcodes` | 产物库：列表、下载、删除、下发打印 |
| `/stocks` | 库存列表、新增、归档 |
| `/stocks/[id]` | 库存详情与流水 |
| `/jobs` | 任务历史 |
| `/jobs/[id]` | 任务详情与扣料 |
| `/reports` | 按日 / 按月报告 |
| `/settings` | 设置入口 |
| `/settings/color-mappings` | AMS 颜色映射 |
| `/settings/swap-codes` | 换盘码管理：三档预设、G-code 渲染预览、测试文件生成 |
| `/settings/material-debug` | 材料匹配调试 |
| `/offline` | 离线兜底 |

手机和 iPad 竖屏（宽度 &lt; 1024px）使用底部标签；更宽的屏幕使用顶部导航。

## 关键目录

```
lib/
├── api.js                  fetchJson / ApiError 基础封装
├── plate-merger-api.js     合盘 / 产物库 / 换盘码 API
└── printer-control-api.js  设备控制与 HMS 查询
components/printer/twin/    数字孪生
├── twin-view.js            容器：GLB 优先，参数化兜底；IBL 布光
├── a1-glb-model.js         真实 CAD 模型驱动（位移 / 温度 / 打印件生长）
├── a1-model.js             参数化兜底模型（含完整联动参考实现）
└── ams-lite-model.js       AMS Lite（GLB 模式下叠加，料盘颜色 / 换料 / HMS 联动）
```

模型文件放置与部件命名规则见 [public/models/README.md](public/models/README.md)。

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
