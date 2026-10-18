# backend（FastAPI）

耗材管理与生产模块的后端：REST API、扣料、合盘算法、设备控制、HMS 码表。

## 本地运行（不使用 Docker）

1) 创建虚拟环境并安装依赖：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2) 设置环境变量（示例）：

```bash
export DATABASE_URL="postgresql+asyncpg://consumables:consumables@localhost:5432/consumables"
export APP_SECRET_KEY="dev-secret-change-me"
export ALLOW_INSECURE_MQTT_TLS="true"
```

3) 运行迁移并启动：

```bash
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

访问：`http://localhost:8000/docs`

## 模块结构

```
app/
├── api/routers/           REST 路由
│   ├── printers.py        打印机 CRUD、扫描
│   ├── realtime.py        SSE 实时推送（/realtime/printers/{id}）
│   ├── plate_merger.py    合盘：upload/analyze/merge/artifacts/dispatch 等 13 个端点
│   ├── controls.py        设备控制：暂停/速度/灯光/运动/AMS（含运动状态锁、G-code 白名单、温度上限）
│   ├── hms.py             HMS 故障码表查询（/hms/meta · /codes · /lookup）
│   └── …                 库存 / 任务 / 报告 / 映射等
├── plate_merger/          合盘纯算法库（零第三方依赖，详见其内 README.md）
│   └── layers.py          G-code 层索引：layer_num → Z/XY，供数字孪生反推喷嘴位置
├── services/
│   ├── event_processor.py MQTT 事件 → 任务 / 扣料 / 产物关联
│   └── bambu_protocol.py  打印机 MQTT 控制协议薄层
├── resources/
│   └── hms_codes.json     HMS 中文码表（593 条，scripts/export_hms_codes.py 导出）
└── db/models/             SQLAlchemy 模型（含 merged_artifacts 合盘产物登记）
```

## 测试

```bash
python3 -m pytest        # 168 项（合盘算法 / 层索引 / 接口）
```

## 安全约定（设备控制）

- 运动类命令（移动 / 回零 / 挤出）在打印机 `RUNNING` / `PREPARE` 时返回 409
- `/gcode` 只放行白名单指令前缀；`M104/M140` 温度超限（喷嘴 300℃ / 热床 120℃）直接拒绝
- API 只接受上传目录内的 3MF 路径，杜绝任意文件读取
