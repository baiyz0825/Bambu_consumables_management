"""打印机控制 API（暂停/恢复/停止、速度、灯光、G-code、运动、AMS、校准）。

分层说明：

- **协议层** 在 ``app.services.bambu_protocol``：只有载荷构造、MQTT 发布与
  安全校验，零数据库依赖；
- **本文件** 只做「取打印机 → 解密凭证 → 安全检查 → 发布 → 错误映射」，
  不重复实现任何协议细节。

错误码约定（为什么这么分）：

- ``404`` 打印机不存在；``400`` 凭证解不开 / G-code 未通过白名单或温度校验
  （都属于**请求方可以自己修正**的问题）；
- ``409`` 打印机正在打印，运动类命令被状态锁拒绝（冲突，不是参数错）；
- ``502`` 打印机 MQTT 不可达 / 发布超时：服务端自身没错，错在**上游设备**，
  语义上就是 Bad Gateway；此时响应体仍是 ``{"accepted": false, "detail": ...}``，
  便于前端统一处理（不塞进 HTTPException 的 ``detail`` 里套一层）。

三条安全红线全部在这里落地（不只写注释）：红线 1 见
:func:`_ensure_motion_allowed`，红线 2/3 见 ``bambu_protocol.validate_gcode``
（由 :func:`send_gcode` 端点调用）。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Final, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.config import settings
from app.core.crypto import decrypt_str
from app.db.models.normalized_event import NormalizedEvent
from app.db.models.printer import Printer
from app.services.bambu_protocol import (
    DEFAULT_COMMAND_TIMEOUT_S,
    DEFAULT_MOVE_SPEED_MM_MIN,
    BambuCommands,
    BambuTarget,
    ControlError,
    InvalidCommandError,
    publish_command,
    validate_gcode,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/printers", tags=["controls"])

#: 打印中状态：处于这些状态时一律拒绝运动控制（撞件风险）。
#: ``PREPARE`` 也算「忙」——预热/调平阶段喷头随时会动。
MOTION_BLOCKING_STATES: Final[frozenset[str]] = frozenset({"RUNNING", "PREPARE"})


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class SpeedIn(BaseModel):
    """速度档位。"""

    level: int = Field(ge=1, le=4, description="1=静音 2=标准 3=运动 4=狂暴")


class LedIn(BaseModel):
    """灯光控制。"""

    node: Literal["chamber_light", "work_light"] = Field(default="chamber_light", description="腔灯 / 工作灯")
    mode: Literal["on", "off", "flashing"] = Field(default="on", description="常亮 / 关闭 / 闪烁")


class GcodeIn(BaseModel):
    """单行 G-code（走后端白名单）。"""

    line: str = Field(min_length=1, max_length=200, description="单行指令，如 M104 S200")


class MoveIn(BaseModel):
    """单轴相对移动。"""

    axis: Literal["X", "Y", "Z"] = Field(description="运动轴")
    distance: float = Field(description="相对位移（mm），正负表示方向")
    speed: float | None = Field(default=None, description="进给速度 mm/min，缺省 3000")


class HomeIn(BaseModel):
    """回零。"""

    axes: str = Field(default="XYZ", pattern=r"^[XYZxyz]{1,3}$", description="需要回零的轴，缺省 XYZ")


class ExtrudeIn(BaseModel):
    """挤出 / 回抽。"""

    distance: float = Field(description="正数进料、负数退料（mm）")


class CalibrateIn(BaseModel):
    """校准位掩码。"""

    bitmask: int = Field(ge=1, le=15, description="1=调平 2=震动 4=流量 8=电机噪音，按位或")


class AmsChangeIn(BaseModel):
    """AMS 换料。"""

    target: int = Field(ge=0, le=255, description="槽位号，0-3 为 AMS，254/255 为外挂料盘")


class AmsControlIn(BaseModel):
    """AMS 进料/退料确认。"""

    action: Literal["resume", "done"] = Field(description="resume=继续 / done=完成")


class OptionIn(BaseModel):
    """打印机选项位掩码（A1 专属，如提示音）。"""

    bitmask: int = Field(ge=0, le=255)


# ---------------------------------------------------------------------------
# 公共辅助
# ---------------------------------------------------------------------------


async def _load_printer(printer_id: UUID, db: AsyncSession) -> Printer:
    """按主键取打印机行，不存在则 404。"""
    printer = await db.get(Printer, printer_id)
    if printer is None:
        raise HTTPException(status_code=404, detail="打印机不存在，请先在设备列表中添加")
    return printer


def _resolve_access_code(printer: Printer) -> str:
    """解密 LAN Access Code。

    密文与当前 ``app_secret_key`` 不匹配时（换过密钥 / 手改过库）
    ``decrypt_str`` 会抛 ``ValueError``；这里转成 400 并提示重新录入，
    而不是抛 500 让人以为是服务端 bug。
    """
    try:
        return decrypt_str(settings.app_secret_key, printer.lan_access_code_enc)
    except ValueError as exc:
        logger.warning("打印机凭证解密失败 printer_id=%s serial=%s", printer.id, printer.serial)
        raise HTTPException(
            status_code=400,
            detail="LAN Access Code 解密失败，请在打印机屏幕上重新查看并录入",
        ) from exc


def _build_target(printer: Printer) -> BambuTarget:
    """组装协议层连接参数（端口 / 超时都用协议层的默认值）。"""
    return BambuTarget(
        host=printer.ip,
        serial=printer.serial,
        access_code=_resolve_access_code(printer),
    )


def _state_of(data: Any) -> str:
    """从事件 ``data_json`` 中取出 ``gcode_state``（大写）。

    兼容两种落库形态：扁平（``gcode_state`` 在顶层，与
    ``/printers/{id}/latest-report`` 的返回一致）与嵌套（``print.gcode_state``）。
    """
    if not isinstance(data, dict):
        return ""
    nested = data.get("print")
    raw = data.get("gcode_state") or (nested.get("gcode_state") if isinstance(nested, dict) else None)
    return str(raw or "").upper()


async def _ensure_motion_allowed(printer_id: UUID, db: AsyncSession) -> None:
    """**红线 1：运动类状态锁。**

    读取该打印机最新一条 ``normalized_events``，若 ``data_json.gcode_state``
    为 ``RUNNING`` / ``PREPARE`` 则 409 拒绝。没有历史事件时放行（新装的机器
    还没有上报，不该被永久锁死），真正的安全性由固件兜底。
    """
    event = (
        await db.execute(
            select(NormalizedEvent)
            .where(NormalizedEvent.printer_id == printer_id)
            .order_by(NormalizedEvent.occurred_at.desc(), NormalizedEvent.id.desc())
            .limit(1)
        )
    ).scalars().first()

    if event is None:
        return

    state = _state_of(event.data_json)
    if state in MOTION_BLOCKING_STATES:
        raise HTTPException(
            status_code=409,
            detail=f"打印中禁止运动控制，避免撞件（当前状态：{state}）",
        )


async def _send(
    target: BambuTarget,
    payload: dict[str, Any],
    *,
    action: str,
    timeout: float = DEFAULT_COMMAND_TIMEOUT_S,
) -> dict[str, Any] | JSONResponse:
    """把载荷发到打印机，成功返回 ``accepted``，传输失败返回 502。

    paho 的连接/发布是阻塞调用，放到线程池执行，避免卡住事件循环。
    """
    try:
        result = await asyncio.to_thread(publish_command, target, payload, timeout=timeout)
    except ControlError as exc:
        logger.warning(
            "控制命令下发失败 printer=%s action=%s code=%s err=%s",
            target.serial,
            action,
            exc.code,
            exc,
        )
        return JSONResponse(
            status_code=502,
            content={"accepted": False, "detail": f"{action}失败：{exc}"},
        )

    return {
        "accepted": True,
        "detail": f"{action}命令已下发：{result.command}（{result.topic}，耗时 {result.elapsed_ms} ms）",
    }


def _guard(call: Any) -> dict[str, Any]:
    """把协议层的参数校验异常转成 400（参数类错误不该冒到 502）。"""
    try:
        return call()
    except InvalidCommandError as exc:
        raise HTTPException(status_code=400, detail=f"命令参数不合法：{exc}") from exc


# ---------------------------------------------------------------------------
# 打印流程控制
# ---------------------------------------------------------------------------


@router.post("/{printer_id}/pause", response_model=None)
async def pause(printer_id: UUID, db: AsyncSession = Depends(get_db)) -> Any:
    """暂停打印：下发 ``print.pause``，已暂停时固件会忽略。"""
    printer = await _load_printer(printer_id, db)
    return await _send(_build_target(printer), BambuCommands.pause(), action="暂停")


@router.post("/{printer_id}/resume", response_model=None)
async def resume(printer_id: UUID, db: AsyncSession = Depends(get_db)) -> Any:
    """恢复打印：下发 ``print.resume``。"""
    printer = await _load_printer(printer_id, db)
    return await _send(_build_target(printer), BambuCommands.resume(), action="恢复")


@router.post("/{printer_id}/stop", response_model=None)
async def stop(printer_id: UUID, db: AsyncSession = Depends(get_db)) -> Any:
    """停止打印：下发 ``print.stop``，**不可恢复**，前端需二次确认。"""
    printer = await _load_printer(printer_id, db)
    return await _send(_build_target(printer), BambuCommands.stop(), action="停止")


@router.post("/{printer_id}/speed", response_model=None)
async def set_speed(printer_id: UUID, body: SpeedIn, db: AsyncSession = Depends(get_db)) -> Any:
    """设置打印速度档位：``print.print_speed``，``param`` 取 1-4。"""
    printer = await _load_printer(printer_id, db)
    payload = _guard(lambda: BambuCommands.set_speed(body.level))
    return await _send(_build_target(printer), payload, action=f"切换到 {body.level} 档速度")


# ---------------------------------------------------------------------------
# 灯光
# ---------------------------------------------------------------------------


@router.post("/{printer_id}/led", response_model=None)
async def set_led(printer_id: UUID, body: LedIn, db: AsyncSession = Depends(get_db)) -> Any:
    """控制机身 LED：``system.ledctrl``（含闪烁节奏字段，固件要求字段齐全）。"""
    printer = await _load_printer(printer_id, db)
    payload = _guard(lambda: BambuCommands.set_led(body.node, body.mode))
    return await _send(_build_target(printer), payload, action=f"灯光 {body.node}={body.mode}")


# ---------------------------------------------------------------------------
# G-code 透传（红线 2 + 红线 3）
# ---------------------------------------------------------------------------


@router.post("/{printer_id}/gcode", response_model=None)
async def send_gcode(printer_id: UUID, body: GcodeIn, db: AsyncSession = Depends(get_db)) -> Any:
    """透传单行 G-code，**必须过白名单与温度上限**。

    拒绝情形（均 400，且不回显可疑内容）：不在
    ``bambu_protocol.ALLOWED_GCODE`` 白名单内、含换行（一次多条）、
    喷嘴 > 300 ℃ 或热床 > 120 ℃。
    """
    printer = await _load_printer(printer_id, db)

    # 红线 2 / 红线 3：白名单 + 温度上限（判定逻辑在协议层，便于单测复用）
    try:
        line = validate_gcode(body.line)
    except InvalidCommandError as exc:
        raise HTTPException(status_code=400, detail=f"G-code 被拒绝：{exc}") from exc

    action = f"G-code {line.split()[0].upper()}"
    return await _send(_build_target(printer), BambuCommands.send_gcode(line), action=action)


# ---------------------------------------------------------------------------
# 运动控制（红线 1：打印中一律拒绝）
# ---------------------------------------------------------------------------


@router.post("/{printer_id}/move", response_model=None)
async def move(printer_id: UUID, body: MoveIn, db: AsyncSession = Depends(get_db)) -> Any:
    """单轴相对移动（HA 轴移动模板，经 ``gcode_line`` 下发）。

    拒绝情形：打印中 409（红线 1）；轴/距离/速度越界 400；
    打印机不可达 502。
    """
    printer = await _load_printer(printer_id, db)
    await _ensure_motion_allowed(printer_id, db)

    speed = body.speed if body.speed is not None else DEFAULT_MOVE_SPEED_MM_MIN
    payload = _guard(lambda: BambuCommands.move(body.axis, body.distance, speed=speed))
    return await _send(
        _build_target(printer),
        payload,
        action=f"移动 {body.axis}{body.distance:g}mm",
    )


@router.post("/{printer_id}/home", response_model=None)
async def home(
    printer_id: UUID,
    body: HomeIn | None = None,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """回零（``G28``）；全轴发 ``G28``，单/双轴发 ``G28 X Z`` 形式。

    ``body`` 可省略（等价于 ``{"axes": "XYZ"}``，省掉前端拼空 body 的麻烦）。
    拒绝情形：打印中 409（红线 1）；轴字母非法 400。
    """
    printer = await _load_printer(printer_id, db)
    await _ensure_motion_allowed(printer_id, db)

    axes = body.axes if body is not None else "XYZ"
    payload = _guard(lambda: BambuCommands.home(axes))
    return await _send(_build_target(printer), payload, action=f"回零 {axes.upper()}")


@router.post("/{printer_id}/extrude", response_model=None)
async def extrude(printer_id: UUID, body: ExtrudeIn, db: AsyncSession = Depends(get_db)) -> Any:
    """挤出 / 回抽（``M83 G0 E{d} F900``）。正数进料、负数退料。

    注意：**需喷嘴已加热**，否则固件会冷挤出保护而拒绝；
    拒绝情形：打印中 409（红线 1）；长度越界 400。
    """
    printer = await _load_printer(printer_id, db)
    await _ensure_motion_allowed(printer_id, db)

    payload = _guard(lambda: BambuCommands.extrude(body.distance))
    return await _send(_build_target(printer), payload, action=f"挤出 {body.distance:g}mm")


# ---------------------------------------------------------------------------
# 校准 / 打印机选项
# ---------------------------------------------------------------------------


@router.post("/{printer_id}/calibrate", response_model=None)
async def calibrate(printer_id: UUID, body: CalibrateIn, db: AsyncSession = Depends(get_db)) -> Any:
    """执行校准（``print.calibration``，位掩码 1-15）。

    校准会带动机器动作，但本端点不加状态锁：打印中固件本身会拒绝执行，
    锁在这里只会让错误码变模糊。位掩码越界 400。
    """
    printer = await _load_printer(printer_id, db)
    payload = _guard(lambda: BambuCommands.calibrate(body.bitmask))
    return await _send(_build_target(printer), payload, action=f"校准（bitmask={body.bitmask}）")


@router.post("/{printer_id}/option", response_model=None)
async def set_option(printer_id: UUID, body: OptionIn, db: AsyncSession = Depends(get_db)) -> Any:
    """打印机选项位掩码（``print.print_option``，A1 系列专属，如提示音开关）。"""
    printer = await _load_printer(printer_id, db)
    payload = _guard(lambda: BambuCommands.print_option(body.bitmask))
    return await _send(_build_target(printer), payload, action=f"打印机选项（bitmask={body.bitmask}）")


# ---------------------------------------------------------------------------
# AMS
# ---------------------------------------------------------------------------


@router.post("/{printer_id}/ams/change", response_model=None)
async def ams_change(printer_id: UUID, body: AmsChangeIn, db: AsyncSession = Depends(get_db)) -> Any:
    """切换 / 加载 AMS 槽位（``print.ams_change_filament``）。

    ``target`` 0-3 为 AMS 四槽，254/255 为外挂料盘；越界 400。
    """
    printer = await _load_printer(printer_id, db)
    payload = _guard(lambda: BambuCommands.ams_change(body.target))
    return await _send(_build_target(printer), payload, action=f"AMS 切换到 {body.target}")


@router.post("/{printer_id}/ams/control", response_model=None)
async def ams_control(printer_id: UUID, body: AmsControlIn, db: AsyncSession = Depends(get_db)) -> Any:
    """AMS 进料 / 退料确认（``print.ams_control``：``resume`` / ``done``）。"""
    printer = await _load_printer(printer_id, db)
    payload = _guard(lambda: BambuCommands.ams_control(body.action))
    return await _send(_build_target(printer), payload, action=f"AMS {body.action}")


def _manual_verification_steps() -> None:
    """手工验证步骤（占位函数，不参与运行，仅作可检索的文档）。

    1. 导入自检（不需要打印机 / 数据库）::

        python3 -c "from app.api.routers import controls; print(len(controls.router.routes))"

    2. 用 ``httpx.ASGITransport`` 直接打路由（无需真机，MQTT 一定会失败，
       正好验证 502 分支与错误体形态）::

        python3 - <<'PY'
        import asyncio, httpx
        from app.main import app
        async def main():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
                r = await c.post("/printers/00000000-0000-0000-0000-000000000000/pause")
                print(r.status_code, r.text)   # 期望 404 + 中文提示
        asyncio.run(main())
        PY

    3. 真机联调（**必须先暂停打印**）::

        curl -X POST localhost:8000/printers/<uuid>/led \\
             -H 'content-type: application/json' -d '{"node":"chamber_light","mode":"on"}'

    4. 红线回归：
       a) 打印中调 ``/move`` 期望 409「打印中禁止运动控制，避免撞件」；
       b) ``/gcode`` 传 ``M500`` 期望 400「指令不在白名单内」；
       c) ``/gcode`` 传 ``M104 S320`` 期望 400「喷嘴目标温度 320 ℃ 超过安全上限 300 ℃」；
       d) 停掉打印机电源后调 ``/pause`` 期望 502 + ``{"accepted": false}``。
    """
