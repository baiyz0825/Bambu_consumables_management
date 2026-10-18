# 拓竹耗材管理系统

局域网里管理拓竹打印机的耗材：读取打印状态和 AMS 槽位，按「材质 + 颜色 + 品牌」扣库存，并统计成本。

在此之上内置**生产模块**：把多个已切片的 3MF 合成一个可无人值守连续打印的文件（自动注入换盘码、重写耗材元数据），产物可直接下发到打印机；并带**数字孪生**视图（真实 CAD 模型，温度/层数/料卷/故障实时联动）与设备控制（暂停/速度/灯光/运动/AMS）。

一台打印机只有一条记录。能直连时走局域网；直连不上且已登录拓竹账号时，改读云端上的同一台。远程开打印仍用 Bambu Handy。单机用 SQLite，也可以换 PostgreSQL。手机、iPad 和桌面都能用，可安装到主屏。

## 文档

| 文档 | 内容 |
|---|---|
| [功能说明](docs/功能说明.md) | 打印机、库存、任务、消耗、界面 |
| [架构](docs/架构.md) | 两条通路、登录合并、扣库存。图：[system.html](docs/diagrams/system.html) |
| [界面](docs/界面.md) | 各页面做什么，以及桌面 / 手机 / iPad 截图 |
| [当前进度与已实现功能](docs/当前进度与已实现功能.md) | 生产模块 / 数字孪生各阶段落地状态 |
| [快速开始](docs/快速开始.md) | 本机启动、Docker、配置、接入打印机 |
| [GHCR 快速部署指南](docs/GHCR快速部署指南.md) | 预构建镜像 |
| [备份与恢复](docs/备份与恢复.md) | 数据备份 |
| [升级与回滚](docs/升级与回滚.md) | 版本切换 |
| [更新日志](docs/CHANGELOG.md) | 变更记录 |

接口说明在后端起来之后打开 `http://localhost:8000/docs`。

## 页面

| 页面 | 路径 | 说明 |
|---|---|---|
| 仪表盘 | `/` | 总览 |
| 打印机 | `/printers` | 列表、扫描、托盘绑定 |
| 打印机详情 | `/printers/[id]` | 实时数据、数字孪生、设备控制、HMS 故障 |
| 生产 | `/production` | 合盘 / 产物库 / 换盘码入口 |
| 合盘向导 | `/production/merge` | 上传 → 自动统计 → 配置 → 生成 → 下载 |
| 产物库 | `/production/gcodes` | 产物列表、下载、删除、下发打印 |
| 库存 | `/stocks` | 库存列表、新增、归档 |
| 任务 | `/jobs` | 任务历史与扣料 |
| 报告 | `/reports` | 按日 / 按月报告 |
| 设置 | `/settings` | 设置入口 |
| 换盘码管理 | `/settings/swap-codes` | 三档预设、G-code 渲染预览、测试文件生成 |

截图和每个页面的操作见 [界面](docs/界面.md)。

## 启动

```bash
uv venv .venv
uv pip install -r backend/requirements.txt -r collector/requirements.txt
cd frontend && npm install && cd ..
./run_local.sh start
```

界面在 `http://localhost:3000`。完整步骤见 [快速开始](docs/快速开始.md)。

## License

MIT
