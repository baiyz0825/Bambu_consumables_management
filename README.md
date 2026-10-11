# 拓竹耗材管理系统 (Bambu Consumables Management)

一个专为拓竹（Bambu Lab）打印机设计的局域网耗材管理系统。通过 **LAN MQTT** 直连打印机，实时监控打印状态与 AMS 托盘信息，自动结算耗材消耗并生成成本统计。支持 **SQLite 单机模式**（零依赖部署）和 **PostgreSQL** 双数据库后端，提供 **PWA 移动端可安装**、**暗色/亮色主题**、**拍照 OCR 识别耗材**、**局域网 mDNS 自动扫描打印机** 等现代化能力。

---

## ✨ 核心功能

### 🖨️ 打印机管理与实时监控

- **局域网自动扫描添加**：一键 mDNS 扫描局域网内的拓竹打印机，自动发现 IP/序列号/型号/固件版本，选中后只需手输 LAN 访问码即可完成添加
- **打印机接入管理**：支持添加/删除/编辑打印机，IP/序列号/访问码加密存储
- **实时状态监控**：MQTT 直连打印机，实时显示在线状态、打印进度、当前任务、温度
- **AMS 托盘信息**：展示当前活动托盘及所有托盘的颜色、材质、剩余量、RFID 标签
- **托盘手动绑定库存**：每个 AMS 托盘可一键绑定耗材库中的库存项（支持搜索/更改/解绑），绑定后优先于颜色自动匹配作为归因依据
- **多机管理**：支持多台打印机同时接入，独立线程监控互不干扰

> 📸 打印机管理界面（含新增的「扫描局域网」按钮）：
> ![打印机管理界面](docs/images/printers.png)

### 📷 拍照 OCR 识别耗材（新增）

- **拍照自动识别**：拍摄耗材标签照片，自动识别材质（PLA/PETG/TPU/ABS...）、单卷重量、颜色名、品牌
- **图像取色**：Canvas 提取图片主色调 RGB，自动填充 `color_hex`，比 OCR 文本颜色名更精确
- **智能解析**：正则从 OCR 文本提取结构化字段，覆盖拓竹 + 主流品牌（Polymaker/eSun/Sunlu...）
- **预填表单**：识别结果自动填入新增库存表单，识别不准的字段可手动修改
- **颜色自动绑定**：OCR 识别的色值入库时自动创建 AMS 颜色映射，省去二次手动绑定
- **降级方案**：OCR 识别失败时支持完全手动添加

> 技术栈：Tesseract.js（纯前端 OCR，中英文双语）+ Canvas 取色 + 正则解析
>
> 📸 桌面端库存页（新增「拍照识别」入口，右上角为三态主题切换按钮）：
> ![库存页-桌面端](docs/images/stocks-v2.png)

### 🧵 耗材库存管理

- **耗材库录入**：按「材质 + 颜色 + 品牌」唯一键录入，支持同键合并入库（自动累加剩余量）
- **库存状态跟踪**：自动维护剩余克数、卷数、单价、总价
- **库存调整记录**：支持手动盘点调整（增减克数），完整账本流水可追溯
- **颜色绑定**：库存项可绑定 AMS 颜色码，方便打印时按颜色匹配扣减
- **归档管理**：删除库存只归档不丢历史，支持恢复

![耗材库存界面](docs/images/stocks.png)

### 📊 自动消耗记录与成本统计

- **三重消耗计算策略**（打印结束时依次尝试）：
  1. 切片文件元数据估算（实际首选，gcode.3mf 解析每色克数）
  2. AMS 剩余量差值（备选，RFID 精度有限默认关闭）
  3. 人工录入/纠错（兜底）
- **两阶段扣减**：打印开始时按 gcode 预估预扣（reservation），打印结束时按实际结算确认
- **多色打印分摊**：支持多托盘打印的消耗按托盘分摊计算
- **自动成本核算**：根据耗材价格自动计算单次打印成本
- **消耗记录幂等**：`(job_id, tray_id, segment_idx)` 部分唯一索引，防重复扣减
- **账本冲正**：支持 void/reversal，数据可恢复

![打印任务历史界面](docs/images/jobs.png)

### 📈 历史查询与报表

- **打印任务历史**：记录所有任务详情（状态、时长、起止时间、耗材消耗、gcode 文件）
- **耗材卷账本**：每个库存项的完整使用流水（采购/调整/消耗/废弃）
- **消耗统计报表**：按时间、材质、打印机等维度统计耗材使用情况
- **数据导出**：支持 CSV 导出

![报表界面](docs/images/reports.png)

### 📱 PWA 移动端 + 主题切换（新增）

- **可安装到桌面**：支持 PWA 安装到手机主屏 / 桌面，独立窗口运行（standalone 模式）
- **移动端自适应**：桌面顶部导航 + 移动端底部固定 Tab Bar，自动切换
- **暗色/亮色/跟随系统**：三态主题切换，next-themes 持久化用户选择，无 FOUC 闪动
- **安全区适配**：iOS 刘海/Home indicator、Android 状态栏自动避让（`viewport-fit=cover` + `env(safe-area-inset-*)`）
- **移动端布局适配**：页头按钮组换行、宽表横向滚动、按钮/输入框 40px+ 触控高度、Dialog 最大高度可滚动
- **离线可用**：Service Worker 预缓存 App Shell，网络不可用时回落 `/offline` 页

> 📸 移动端视图（375px，展示底部 Tab Bar + 暗色主题）：
> ![移动端库存页](docs/images/mobile-stocks.png)
>
> 📸 桌面端仪表板：
> ![仪表板](docs/images/dashboard.png)

---

## 🚀 快速开始

### 方式一：本地源码启动（推荐，单机零依赖）

> 适合个人工作室 / 单机部署，无需 Docker，SQLite 内置存储

**前置依赖**：
- Python 3.12+
- Node.js 18+
- uv（Python 包管理器，`brew install uv`）

**启动步骤**：

```bash
# 1. 克隆仓库
git clone https://github.com/yangtao121/Bambu_consumables_management.git
cd Bambu_consumables_management

# 2. 创建 Python 虚拟环境并安装依赖
uv venv .venv
uv pip install -r backend/requirements.txt
uv pip install -r collector/requirements.txt

# 3. 安装前端依赖
cd frontend && npm install && cd ..

# 4. 一键启动（自动生成 .env.local + 建库 + 启动三服务）
./run_local.sh start
```

**访问地址**：
- 前端界面：`http://localhost:3000`
- 后端 API 文档：`http://localhost:8000/docs`
- 健康检查：`http://localhost:8000/health`

**常用命令**：

```bash
./run_local.sh start     # 启动 backend + collector + frontend
./run_local.sh stop      # 停止所有服务
./run_local.sh restart   # 重启
./run_local.sh status    # 查看运行状态
./run_local.sh logs      # 查看实时日志
```

**数据存储位置**：`data/consumables.db`（SQLite，WAL 模式，支持并发读写）

### 方式二：Docker Compose 部署（PostgreSQL）

> 适合多用户 / 服务器部署，PostgreSQL 后端

**前置依赖**：Docker 20.10+ / Docker Compose v2.0+

```bash
# 1. 准备环境配置
cp env.example .env
# 编辑 .env，修改 APP_SECRET_KEY 和 NEXT_PUBLIC_API_BASE_URL

# 2. 启动全部服务（db + api + collector + frontend）
docker compose up -d --build

# 3. 验证
docker compose ps
curl http://localhost:8000/health
```

**镜像信息**：
- API 服务：`ghcr.io/yangtao121/3d-consumables-api:latest`
- 采集器：`ghcr.io/yangtao121/3d-consumables-collector:latest`
- 前端：`ghcr.io/yangtao121/3d-consumables-frontend:latest`

> ⚠️ 注意：GHCR 预构建镜像仅发布 `linux/amd64` 架构，Apple Silicon (arm64) Mac 请用方式一本地源码启动。

---

## ⚙️ 配置说明

### 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/consumables.db` | 数据库连接串。PostgreSQL 部署时设为 `postgresql+asyncpg://user:pass@host:5432/db` |
| `APP_SECRET_KEY` | `dev-secret-change-me` | Fernet 对称加密密钥，用于加密打印机 LAN 访问码。**生产环境务必更换** |
| `APP_ENV` | `dev` | 运行环境（dev/prod），影响日志级别 |
| `ALLOW_INSECURE_MQTT_TLS` | `True` | 是否跳过 MQTT TLS 证书校验（拓竹自签证书需开启） |
| `MATERIAL_AMS_CALIBRATION_ENABLED` | `False` | 是否启用 AMS 剩余量差值校准（RFID 精度有限，默认关闭） |
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | 前端访问后端 API 的基础地址（浏览器侧） |

### 数据库切换

默认 SQLite 单机模式，切换到 PostgreSQL 只需设置环境变量：

```bash
# SQLite（默认）
export DATABASE_URL="sqlite+aiosqlite:///./data/consumables.db"

# PostgreSQL
export DATABASE_URL="postgresql+asyncpg://consumables:consumables@localhost:5432/consumables"
```

代码层面已做跨方言适配（`Uuid` / `JSON` / 部分唯一索引 `sqlite_where` + `postgresql_where`），两种数据库自动建表。

---

## 📡 打印机接入流程

### 方式一：局域网扫描（推荐）

「打印机」页 → 「扫描局域网」→ 弹窗内提供两种发现方式：

1. **mDNS 扫描（默认）**：监听拓竹服务类型（8 秒窗口），可拿到 IP/序列号/型号/固件版本
2. **网段扫描（兜底）**：mDNS 扫不到时（AP 隔离 / 跨 VLAN / 组播被禁 / 打印机未广播）改用此方式，
   输入网段（如 `192.168.9`）后并发探测 8883 端口，1~2 秒即可列出在线设备（无序列号，需手输）

选中设备后 IP/型号自动填入表单，再补 LAN 访问码即可添加。

### 方式二：手动添加

在「打印机」页的「添加打印机」表单中手动填写：
- **IP 地址**：打印机局域网 IP（如 `192.168.1.100`）
- **序列号**：打印机底部标签或屏幕「关于」中查看（如 `A1Pxxxxx`）
- **LAN 访问码**：打印机屏幕「设置 → 网络」中查看（8 位数字）
- **别名**（可选）：自定义显示名
- **型号**（可选）：如 `P1S` / `X1C` / `A1`

---

## 📷 耗材录入流程

### 方式一：拍照 OCR 识别（推荐）

1. 打开「库存」页 → 点「新增库存」
2. 在弹窗顶部点「拍照识别」
3. 拍摄耗材标签（或上传图片）
4. 系统自动识别：
   - **材质**：PLA / PETG / TPU / ABS / ASA / PC / PA-CF 等主流材质
   - **单卷重量**：自动识别 `1.00kg` / `1000g` 等格式并换算为克
   - **颜色**：图像取色 hex + OCR 文本颜色名双保险
   - **品牌**：拓竹 / Polymaker / eSun / Sunlu 等
5. 识别结果展示置信度，点「填入表单」预填
6. 核对/修改后点「添加」完成录入

### 方式二：手动添加

在「新增库存」表单中手动填写材质、颜色、品牌、单卷克数、卷数、价格等。

---

## 🏗️ 技术架构

### 三服务架构（数据库当消息队列，零中间件依赖）

```
拓竹打印机 ──MQTT(TLS 8883, bblp/访问码)──► collector ──写事件──► 数据库
     └─FTPS(990) 下载.gcode.3mf→解析耗量──┘                      ▲
                                                                  │每2s轮询事件
                                              backend(EventProcessor)
                                              结算消耗→扣库存→写账本
                                                                  ▲
                                              frontend ◄──REST + SSE┘
```

| 服务 | 目录 | 技术栈 | 职责 |
|---|---|---|---|
| **backend** | `backend/` | Python 3.12 + FastAPI + SQLAlchemy 2.0 (async) + Pydantic | REST API、事件结算、SSE 实时推送、报表 |
| **collector** | `collector/` | Python + paho-mqtt + orjson + zeroconf | 连接拓竹 LAN MQTT、采集报文、mDNS 扫描 |
| **frontend** | `frontend/` | Next.js 15 (App Router) + React 19 + Tailwind + shadcn/ui + Tesseract.js | 仪表盘、PWA、OCR、主题切换 |

### 关键设计

- **DB 事件表 + 轮询（Outbox 模式）**：collector 写 `normalized_events`，backend 的 `EventProcessor` 每 2 秒按 `id > last_id` 增量消费，零 MQ 依赖
- **托盘快照 + 部分唯一索引**：`spool_binding_snapshot_json` 存打印开始时的托盘快照，`(job_id, tray_id, segment_idx)` 部分唯一索引保证结算幂等
- **账本 + 冲正**：`MaterialLedger` 支持 void/reversal，数据可恢复
- **跨方言双数据库**：`Uuid` / `JSON` / `sqlite_where` + `postgresql_where` 适配，SQLite 单机 + PostgreSQL 多用户
- **Fernet 加密**：打印机 LAN 访问码加密存储，密钥通过 `APP_SECRET_KEY` 配置

### 数据库 ER 概览

核心实体（11 个）：
- `Printer` / `PrintJob` / `ConsumptionRecord` / `MaterialStock` / `MaterialLedger`
- `raw_event` / `normalized_event`（事件管道）
- `TrayMapping` / `Spool` / `AmsColorMapping` / `InventoryAdjustment`

---

## 📚 API 文档

启动后端后访问 Swagger UI：`http://localhost:8000/docs`

主要路由模块：

| 路由前缀 | 模块 | 说明 |
|---|---|---|
| `/printers` | 打印机管理 | CRUD + `GET /printers/scan` mDNS 扫描 + `POST /printers/scan-subnet` 网段探测 + `GET /printers/network-info` |
| `/printers/{id}/latest-report` | 实时报告 | 最新 MQTT 上报数据 |
| `/realtime/printers` | SSE 流 | 实时推送打印机状态变化 |
| `/stocks` | 耗材库存 | CRUD + 合并入库 + `color_hex` 自动绑定 |
| `/stocks/{id}/bind-color` | 颜色绑定 | 绑定 AMS 颜色码 |
| `/jobs` | 打印任务 | 任务历史 + 人工录入消耗 + 纠错 |
| `/tray-mappings` | 托盘映射 | 打印机托盘 ↔ 库存项绑定/解绑（`stock_id`，兼容 legacy `spool_id`） |
| `/trays` | 料盘管理 | 料盘总数 + 丢弃 |
| `/color-mappings` | 颜色映射 | AMS 颜色码 ↔ 颜色名 CRUD |
| `/reports` | 报表 | summary / monthly / daily |
| `/material-ledger` | 账本 | 冲正流水 |

---

## 🎨 前端页面导航

### 桌面端（顶部导航）

| 菜单 | 路径 | 功能 |
|---|---|---|
| 仪表盘 | `/` | 关键统计、快速入口 |
| 打印机 | `/printers` | 打印机管理、扫描添加、AMS 托盘实时状态、托盘绑定库存 |
| 库存 | `/stocks` | 耗材库 CRUD、拍照 OCR、颜色绑定、账本 |
| 任务历史 | `/jobs` | 打印任务、消耗记录、人工纠错 |
| 报告 | `/reports` | 按时间/材质/打印机维度统计 |
| 设置 | `/settings` | AMS 颜色映射管理 |

### 移动端（底部 Tab Bar）

6 个 Tab 带图标，固定底部，带安全区 padding，自动避让 iOS 刘海/Home indicator。

### 主题切换

右上角太阳/月亮/笔记本图标，三态循环：
- ☀️ 浅色
- 🌙 深色
- 💻 跟随系统（默认）

主题选择持久化到 localStorage（`bbs-theme`），切换无 FOUC 闪动。

---

## 🛠️ 开发指南

### 项目结构

```
Bambu_consumables_management/
├── backend/                 # FastAPI 后端
│   ├── app/
│   │   ├── api/routers/     # 路由（printers/stocks/jobs/...）
│   │   ├── db/models/       # ORM 模型（11 个实体）
│   │   ├── schemas/         # Pydantic schema
│   │   ├── services/        # 业务服务（event_processor/bambu_discovery/...）
│   │   └── core/            # 配置、加密
│   └── requirements.txt
├── collector/               # MQTT 采集器
│   ├── collector/
│   │   ├── main.py          # MQTT watcher 主循环
│   │   ├── gcode_estimator.py  # .gcode.3mf 切片耗量解析
│   │   └── db/              # 共享模型副本
│   └── requirements.txt
├── frontend/                # Next.js 15 前端
│   ├── app/                 # App Router 页面
│   ├── components/          # 组件（app-shell/ocr-scanner/printer-scan-dialog/...）
│   ├── lib/                 # 工具（api/filament-parser/color-extractor/...）
│   └── package.json
├── docs/                    # 文档 + 截图
├── run_local.sh             # 本地一键启动脚本
├── docker-compose.yml       # 源码构建部署
└── docker-compose.ghcr.yml  # GHCR 预构建镜像部署
```

### 本地开发

```bash
# 启动后端（热重载）
cd backend && ../.venv/bin/uvicorn app.main:app --reload --port 8000

# 启动采集器
cd collector && ../.venv/bin/python -m collector.main

# 启动前端（热重载）
cd frontend && npm run dev
```

### 生成 PWA 图标

```bash
cd frontend && node scripts/gen-icons.js
# 输出到 public/icons/（192/512/maskable-512/apple-touch-180）
```

---

## 📖 更多文档

- [GHCR 快速部署指南](docs/GHCR快速部署指南.md)
- [局域网读取方法](docs/局域网读取方法.md)
- [备份与恢复](docs/备份与恢复.md)
- [升级与回滚](docs/升级与回滚.md)
- [当前进度与已实现功能](docs/当前进度与已实现功能.md)
- [实现路径](docs/实现路径.md)

---

## 📝 更新日志

### v2.0（单机版改造）

- ✅ SQLite 单机模式支持（跨方言双支持 SQLite/PostgreSQL）
- ✅ PWA 可安装到桌面 + 移动端自适应布局（底部 Tab Bar）
- ✅ 暗色/亮色/跟随系统主题切换
- ✅ 拍照 OCR 识别耗材（材质/颜色/重量/品牌 + 图像取色）
- ✅ 局域网 mDNS 自动扫描拓竹打印机
- ✅ 一键本地启动脚本 `run_local.sh`
- ✅ 代码规范化（PEP 257 docstring + 标准 logging + agent-log 噪音清理）

### v1.0（原版）

- 三服务架构（backend/collector/frontend）
- MQTT 实时监控 + AMS 托盘状态
- 三重消耗计算策略
- 账本冲正 + 幂等扣减
- 报表 + CSV 导出

---

## 📄 License

MIT

