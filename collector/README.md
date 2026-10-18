# collector（MQTT 采集器）

采集器会从数据库 `printers` 表读取已配置的打印机，逐台连接其 LAN MQTT（TLS 8883），订阅 `device/<serial>/report`，并将：

- 原始消息写入 `raw_events`
- 标准化事件写入 `normalized_events`

## 采集字段

除基础状态（`gcode_state` / `progress` / AMS 槽位 / 耗材）外，还为数字孪生扩充了 30 个字段：

| 类别 | 字段 |
|---|---|
| 温度 | `nozzle_temper` / `nozzle_target_temper` / `bed_temper` / `bed_target_temper` / `chamber_temper` |
| 层 / 阶段 | `layer_num` / `total_layer_num` / `mc_print_stage` / `mc_print_sub_stage` |
| 风扇 / 灯 / 速度 | `cooling_fan_speed` / `big_fan1_speed` / `big_fan2_speed` / `heatbreak_fan_speed` / `lights` / `spd_lvl` / `spd_mag` |
| 故障 | `hms`（含 ecode 归一 + 模块号）/ `print_error` / `fail_reason` |
| 换料动画 | `tray_now` / `tray_pre` / `tray_tar` |
| 其他 | `home_flag` |

事件类型推导：`HmsError` / `HmsCleared` **优先于** `gcode_state` 状态翻转——故障出现时状态可能仍是 RUNNING，只靠状态机发现不了。

## 本地运行（不使用 Docker）

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL="postgresql+asyncpg://consumables:consumables@localhost:5432/consumables"
export APP_SECRET_KEY="dev-secret-change-me"
python -m collector.main
```

## 历史回补

`normalized_events` 里已有的事件可以按新字段规则回补（默认 `enrich` 模式只补缺失键，不改 `type` 与已有值）：

```bash
# 先试跑看比例
DATABASE_URL=... python3 scripts/backfill_normalized.py --dry-run --limit 1000
# 实际执行
DATABASE_URL=... python3 scripts/backfill_normalized.py
```

## 测试

```bash
python3 -m pytest        # 10 项（字段归一 / HMS 事件优先级 / 排序稳定性）
```
