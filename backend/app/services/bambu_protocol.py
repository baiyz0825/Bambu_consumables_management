"""拓竹打印机 MQTT 控制命令的协议薄层。

职责边界（只做三件事）：

1. 把「人类意图」翻译成固件认识的 JSON 载荷（:class:`BambuCommands`）；
2. 用与 collector / ``app.plate_merger.dispatch`` 一致的 TLS 参数把载荷发到
   ``device/{serial}/request``（:class:`BambuSession` / :func:`publish_command`）；
3. 失败时抛明确异常（:class:`ControlError` 体系），**绝不静默吞掉**。

本模块**不碰数据库、不碰 FastAPI**：路由层负责取打印机行、解密 access code、
运动状态锁与 HTTP 错误映射，这里保持纯协议视角，便于单测、CLI 与将来复用
（数字孪生 / 定时维护任务都可以直接调）。

载荷组织方式照 Home Assistant ``ha-bambulab`` 的 ``commands.py``：每条命令都是
单键字典 ``{"print": {...}}`` 或 ``{"system": {...}}``，内层统一带
``sequence_id`` + ``command``。命令名全部来自实机验证过的固件协议（技术方案
扩展篇 §6），不是猜的。

需在**真机**确认的字段（本地无法验证，已汇总在文件末尾 ``_manual_verification_steps``）：
- ``print_speed`` 的 ``param`` 是数字还是字符串；
- ``calibration`` / ``print_option`` 的位掩码字段名（``param`` 还是 ``option``）；
- ``ams_change_filament`` 是否还需要 ``curr_temp`` / ``tar_temp``；
- ``ams_control`` 除 ``resume`` / ``done`` 外是否还有其他 ``param`` 取值。
"""

from __future__ import annotations

import itertools
import json
import logging
import re
import ssl
import threading
import time
from dataclasses import dataclass
from typing import Any, Final

logger = logging.getLogger(__name__)

__all__ = [
    "BAMBU_MQTT_PORT",
    "BAMBU_MQTT_USERNAME",
    "BambuCommands",
    "BambuSession",
    "BambuTarget",
    "ControlError",
    "DEFAULT_COMMAND_TIMEOUT_S",
    "DEFAULT_MOVE_SPEED_MM_MIN",
    "InvalidCommandError",
    "MAX_BED_TEMP_C",
    "MAX_NOZZLE_TEMP_C",
    "MqttConnectionError",
    "MqttPublishError",
    "PublishResult",
    "publish_command",
    "validate_gcode",
]

# ---------------------------------------------------------------------------
# 连接参数（与 collector / dispatch.py 保持一致，不要另起一套）
# ---------------------------------------------------------------------------

#: 拓竹局域网 MQTT（TLS）端口
BAMBU_MQTT_PORT: Final[int] = 8883

#: 局域网固定用户名，密码为打印机屏幕上显示的 LAN Access Code
BAMBU_MQTT_USERNAME: Final[str] = "bblp"

#: 单条命令默认超时（秒）：连接确认与发布确认共用这个预算
DEFAULT_COMMAND_TIMEOUT_S: Final[float] = 5.0

# ---------------------------------------------------------------------------
# 运动与安全上限
# ---------------------------------------------------------------------------

#: 轴移动默认速度（mm/min），与 Studio 手动移动的中档一致
DEFAULT_MOVE_SPEED_MM_MIN: Final[float] = 3000.0

#: 单次轴移动最大位移（mm）；防止误输入 9999 把喷头怼到边框
MAX_SINGLE_MOVE_MM: Final[float] = 200.0

#: 单次挤出 / 回抽最大长度（mm）
MAX_EXTRUDE_MM: Final[float] = 100.0

#: 喷嘴目标温度硬上限（℃）
MAX_NOZZLE_TEMP_C: Final[int] = 300

#: 热床目标温度硬上限（℃）
MAX_BED_TEMP_C: Final[int] = 120

#: 允许的运动轴
MOTION_AXES: Final[frozenset[str]] = frozenset({"X", "Y", "Z"})

#: 允许的 LED 节点（腔灯 / 工作灯）
LED_NODES: Final[frozenset[str]] = frozenset({"chamber_light", "work_light"})

#: 允许的 LED 模式
LED_MODES: Final[frozenset[str]] = frozenset({"on", "off", "flashing"})

#: 允许的 AMS 控制动作
AMS_CONTROL_ACTIONS: Final[frozenset[str]] = frozenset({"resume", "done"})

#: 轴移动模板（HA ``ha-bambulab`` 现成实现，与 Studio 转盘同款机制）。
#: 顺序不可调换：先解除软限位 → 进入相对模式 → 移动 → 还原参考系 → 恢复限位。
MOTION_TEMPLATE: Final[str] = (
    "M211 X1 Y1 Z1\n"
    "M1002 push_ref_mode\n"
    "G91\n"
    "G1 {axis}{distance} F{speed}\n"
    "M1002 pop_ref_mode\n"
    "M211 R"
)

#: 挤出 / 回抽模板：相对挤出模式 + 定速 900 mm/min
EXTRUDE_TEMPLATE: Final[str] = "M83 G0 E{distance} F900"

#: ``system.ledctrl`` 的闪烁节奏字段（HA 默认值，固件要求字段齐全才识别）
_LED_BLINK_FIELDS: Final[dict[str, int]] = {
    "led_on_time": 500,
    "led_off_time": 500,
    "loop_times": 0,
    "interval_time": 0,
}

# ---------------------------------------------------------------------------
# G-code 白名单与温度上限（红线 2 / 红线 3 的判定依据）
# ---------------------------------------------------------------------------

#: 白名单指令前缀（整词匹配，不做前缀包含，避免 ``G280`` 冒充 ``G28``）
ALLOWED_GCODE: Final[frozenset[str]] = frozenset(
    {
        "G28",  # Home
        "M104",  # 喷嘴定温
        "M140",  # 热床定温
        "M106",  # 风扇开
        "M107",  # 风扇关
        "M117",  # LCD 文本
        "M900",  # 线性推进
        "M220",  # 速度倍率
        "M221",  # 流量倍率
        "G1",  # 直线移动
        "G0",  # 快速移动
        "G92",  # 坐标重置
        "M83",  # 相对挤出
        "M82",  # 绝对挤出
        "G90",  # 绝对定位
        "G91",  # 相对定位
    }
)

#: 会设定喷嘴温度的命令
_NOZZLE_TEMP_COMMANDS: Final[frozenset[str]] = frozenset({"M104", "M109"})

#: 会设定热床温度的命令
_BED_TEMP_COMMANDS: Final[frozenset[str]] = frozenset({"M140", "M190"})

#: 温度参数（``S`` 目标温度，``R`` 用于 M109/M190 的等待温差写法）
_TEMP_PARAM_RE: Final[re.Pattern[str]] = re.compile(r"[SR](-?\d+(?:\.\d+)?)")

#: 单调递增的 sequence_id 生成器（固件按它去重回显，重复值会被忽略）
_SEQUENCE: Final[itertools.count] = itertools.count(1)


def _next_sequence_id() -> str:
    """生成一个新的 ``sequence_id``（进程内单调递增，字符串形态）。"""
    return str(next(_SEQUENCE))


# ---------------------------------------------------------------------------
# 异常体系
# ---------------------------------------------------------------------------


class ControlError(Exception):
    """控制命令所有可预期失败的基类。

    :param message: 面向人的中文描述，省略时用类级默认值。
    :param detail: 结构化上下文（host / topic / 超时值等），用于日志排查，
        ``__str__`` 会把它们拼在消息后面，方便直接塞进 HTTP ``detail``。
    """

    code: str = "control_error"
    message: str = "打印机控制失败"

    def __init__(self, message: str | None = None, *, detail: dict[str, Any] | None = None) -> None:
        self.message = message or self.message
        self.detail: dict[str, Any] = detail or {}
        super().__init__(self.message)

    def __str__(self) -> str:
        if not self.detail:
            return self.message
        pairs = ", ".join(f"{key}={value}" for key, value in self.detail.items())
        return f"{self.message} ({pairs})"


class InvalidCommandError(ControlError):
    """命令参数不安全或不受支持（白名单之外、超温、超行程…）。"""

    code = "invalid_command"
    message = "命令未通过安全校验"


class MqttConnectionError(ControlError):
    """无法与打印机建立 MQTT 会话（网络不可达、鉴权失败、缺少依赖）。"""

    code = "mqtt_unavailable"
    message = "打印机 MQTT 连接不可用"


class MqttPublishError(ControlError):
    """已连上但命令没有成功发出去（发布失败或确认超时）。"""

    code = "mqtt_publish_failed"
    message = "命令发布失败"


# ---------------------------------------------------------------------------
# 命令载荷构造（纯函数，无 I/O）
# ---------------------------------------------------------------------------


class BambuCommands:
    """所有控制命令的载荷构造器（照 HA ``commands.py`` 的组织方式）。

    每个静态方法都返回可直接 ``json.dumps`` 的字典；参数不合法时抛
    :class:`InvalidCommandError`，**调用方不需要再校验一遍**。
    """

    @staticmethod
    def _print(command: str, **fields: Any) -> dict[str, Any]:
        """构造 ``{"print": {sequence_id, command, ...}}`` 载荷。"""
        block: dict[str, Any] = {"sequence_id": _next_sequence_id(), "command": command}
        block.update(fields)
        return {"print": block}

    @staticmethod
    def _system(command: str, **fields: Any) -> dict[str, Any]:
        """构造 ``{"system": {sequence_id, command, ...}}`` 载荷。"""
        block: dict[str, Any] = {"sequence_id": _next_sequence_id(), "command": command}
        block.update(fields)
        return {"system": block}

    # -- 打印流程 --------------------------------------------------------

    @staticmethod
    def pause() -> dict[str, Any]:
        """暂停当前打印（``print.pause``）。"""
        return BambuCommands._print("pause", param="")

    @staticmethod
    def resume() -> dict[str, Any]:
        """恢复被暂停的打印（``print.resume``）。"""
        return BambuCommands._print("resume", param="")

    @staticmethod
    def stop() -> dict[str, Any]:
        """停止当前打印（``print.stop``，不可恢复）。"""
        return BambuCommands._print("stop", param="")

    @staticmethod
    def set_speed(level: int) -> dict[str, Any]:
        """设置打印速度档位（``print.print_speed``，``param`` 取 1-4）。

        :param level: 1=静音 2=标准 3=运动 4=狂暴（Studio 的四档）。
        """
        if not 1 <= int(level) <= 4:
            raise InvalidCommandError(f"速度档位只能是 1-4，收到 {level}")
        return BambuCommands._print("print_speed", param=int(level))

    # -- 灯光 ------------------------------------------------------------

    @staticmethod
    def set_led(node: str, mode: str) -> dict[str, Any]:
        """控制机身 LED（``system.ledctrl``）。

        :param node: ``chamber_light``（腔灯）或 ``work_light``（工作灯）。
        :param mode: ``on`` / ``off`` / ``flashing``。
        """
        node = (node or "").strip().lower()
        mode = (mode or "").strip().lower()
        if node not in LED_NODES:
            raise InvalidCommandError(f"未知的 LED 节点，仅支持 {'/'.join(sorted(LED_NODES))}")
        if mode not in LED_MODES:
            raise InvalidCommandError(f"未知的 LED 模式，仅支持 {'/'.join(sorted(LED_MODES))}")
        return BambuCommands._system("ledctrl", led_node=node, led_mode=mode, **_LED_BLINK_FIELDS)

    # -- G-code ----------------------------------------------------------

    @staticmethod
    def send_gcode(line: str) -> dict[str, Any]:
        """下发一段 G-code（``print.gcode_line``）。

        固件按行解析，末尾必须带 ``\\n``；多行文本视为一组连续指令
        （运动模板就依赖这一点）。用户输入的单行指令请先过
        :func:`validate_gcode`。
        """
        text = (line or "").strip()
        if not text:
            raise InvalidCommandError("G-code 不能为空")
        return BambuCommands._print("gcode_line", param=f"{text}\n")

    # -- AMS -------------------------------------------------------------

    @staticmethod
    def ams_change(target: int) -> dict[str, Any]:
        """切换/加载 AMS 槽位（``print.ams_change_filament``）。

        :param target: 槽位号。0-3 对应 AMS 四个料槽，254/255 为外挂料盘
            （与 report 中 ``ams.tray[].id`` / ``vt_tray`` 的口径一致）。
        """
        slot = int(target)
        if not 0 <= slot <= 255:
            raise InvalidCommandError(f"AMS 槽位号超出范围 0-255，收到 {target}")
        return BambuCommands._print("ams_change_filament", target=slot)

    @staticmethod
    def ams_control(action: str) -> dict[str, Any]:
        """AMS 进料/退料确认（``print.ams_control``）。

        :param action: ``resume``（继续）或 ``done``（完成/结束）。
        """
        normalized = (action or "").strip().lower()
        if normalized not in AMS_CONTROL_ACTIONS:
            raise InvalidCommandError(f"AMS 动作只能是 {'/'.join(sorted(AMS_CONTROL_ACTIONS))}")
        return BambuCommands._print("ams_control", param=normalized)

    # -- 校准 / 打印机选项 -------------------------------------------------

    @staticmethod
    def calibrate(bitmask: int) -> dict[str, Any]:
        """执行校准（``print.calibration``，位掩码）。

        :param bitmask: 1=调平 2=震动补偿 4=流量 8=电机噪音，按位或组合。
        """
        mask = int(bitmask)
        if not 1 <= mask <= 15:
            raise InvalidCommandError(f"校准位掩码只能是 1-15，收到 {bitmask}")
        return BambuCommands._print("calibration", param=mask)

    @staticmethod
    def print_option(bitmask: int) -> dict[str, Any]:
        """打印机选项位掩码（``print.print_option``，**A1 系列专属**，如提示音开关）。"""
        mask = int(bitmask)
        if not 0 <= mask <= 255:
            raise InvalidCommandError(f"选项位掩码只能是 0-255，收到 {bitmask}")
        return BambuCommands._print("print_option", param=mask)

    # -- 运动控制（危险操作，路由层须先过状态锁） --------------------------

    @staticmethod
    def move(axis: str, distance: float, *, speed: float = DEFAULT_MOVE_SPEED_MM_MIN) -> dict[str, Any]:
        """单轴相对移动（``print.gcode_line`` + 轴移动模板）。

        :param axis: ``X`` / ``Y`` / ``Z``。
        :param distance: 相对位移（mm），正负表示方向；绝对值上限
            :data:`MAX_SINGLE_MOVE_MM`。
        :param speed: 进给速度（mm/min）。
        """
        axis_key = (axis or "").strip().upper()
        if axis_key not in MOTION_AXES:
            raise InvalidCommandError(f"未知的运动轴，仅支持 {'/'.join(sorted(MOTION_AXES))}")

        offset = float(distance)
        if offset == 0:
            raise InvalidCommandError("移动距离不能为 0")
        if abs(offset) > MAX_SINGLE_MOVE_MM:
            raise InvalidCommandError(f"单次移动不能超过 {MAX_SINGLE_MOVE_MM:g} mm，收到 {offset:g} mm")

        feed = float(speed)
        if not 60 <= feed <= 12000:
            raise InvalidCommandError(f"移动速度需在 60-12000 mm/min 之间，收到 {feed:g}")

        line = MOTION_TEMPLATE.format(axis=axis_key, distance=f"{offset:g}", speed=int(feed))
        return BambuCommands.send_gcode(line)

    @staticmethod
    def home(axes: str = "XYZ") -> dict[str, Any]:
        """回零（``G28``）。

        :param axes: 需要回零的轴，缺省 ``XYZ``；传 ``Z`` 则只回 Z。
            全轴回零发 ``G28``，单轴/双轴发 ``G28 Z`` / ``G28 X Y`` 形式
            （与项目内已在实机跑通的换盘码 ``G28 Y`` 同一语法）。
        """
        raw = "".join((axes or "").strip().upper().replace(" ", ""))
        if not raw:
            raw = "XYZ"
        # 去重但保序，避免 "XXYZ" 之类的输入
        unique = "".join(dict.fromkeys(raw))
        illegal = set(unique) - MOTION_AXES
        if illegal:
            raise InvalidCommandError(f"回零轴只能包含 X/Y/Z，收到非法字符 {'/'.join(sorted(illegal))}")

        line = "G28" if unique == "XYZ" else "G28 " + " ".join(unique)
        return BambuCommands.send_gcode(line)

    @staticmethod
    def extrude(distance: float) -> dict[str, Any]:
        """挤出 / 回抽（``M83 G0 E{d} F900``，需喷嘴已加热）。

        :param distance: 正数进料、负数退料；绝对值上限 :data:`MAX_EXTRUDE_MM`。
        """
        offset = float(distance)
        if offset == 0:
            raise InvalidCommandError("挤出长度不能为 0")
        if abs(offset) > MAX_EXTRUDE_MM:
            raise InvalidCommandError(f"单次挤出不能超过 {MAX_EXTRUDE_MM:g} mm，收到 {offset:g} mm")
        return BambuCommands.send_gcode(EXTRUDE_TEMPLATE.format(distance=f"{offset:g}"))


# ---------------------------------------------------------------------------
# G-code 安全校验（路由层 /gcode 端点直接调用）
# ---------------------------------------------------------------------------


def validate_gcode(line: str) -> str:
    """校验用户提交的单行 G-code：白名单（红线 2）+ 温度上限（红线 3）。

    判定顺序：非空 → 单行 → 白名单整词匹配 → 温度参数上限。
    拒绝时抛 :class:`InvalidCommandError`，**错误信息不回显原始输入**
    （只有白名单列表与被解析出的数值），避免把可疑内容写进日志或响应。

    :return: 裁剪首尾空白后的原始指令行（可用于回显指令名）。
    """
    text = (line or "").strip()
    if not text:
        raise InvalidCommandError("G-code 不能为空")
    if "\n" in text or "\r" in text:
        raise InvalidCommandError("只允许单行 G-code，禁止一次提交多条指令")

    tokens = text.split()
    code = tokens[0].upper()
    if code not in ALLOWED_GCODE:
        raise InvalidCommandError(
            "指令不在白名单内",
            detail={"allowed": "/".join(sorted(ALLOWED_GCODE))},
        )

    temperature_commands = _NOZZLE_TEMP_COMMANDS | _BED_TEMP_COMMANDS
    if code in temperature_commands:
        limit = MAX_NOZZLE_TEMP_C if code in _NOZZLE_TEMP_COMMANDS else MAX_BED_TEMP_C
        label = "喷嘴" if code in _NOZZLE_TEMP_COMMANDS else "热床"
        for raw_value in _TEMP_PARAM_RE.findall(text):
            value = float(raw_value)
            if value > limit:
                raise InvalidCommandError(
                    f"{label}目标温度 {value:g} ℃ 超过安全上限 {limit} ℃",
                    detail={"command": code, "limit_c": limit},
                )

    return text


# ---------------------------------------------------------------------------
# MQTT 会话
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BambuTarget:
    """打印机连接参数（局域网 P1S/A1 一类的直连口径）。"""

    host: str
    serial: str
    access_code: str
    port: int = BAMBU_MQTT_PORT
    timeout_s: float = DEFAULT_COMMAND_TIMEOUT_S

    @property
    def request_topic(self) -> str:
        """命令下行 topic。"""
        return f"device/{self.serial}/request"

    @property
    def report_topic(self) -> str:
        """状态上报 topic（本模块只发不收，留给采集侧）。"""
        return f"device/{self.serial}/report"


@dataclass(frozen=True)
class PublishResult:
    """一次成功下发的记录，供路由层拼响应。"""

    topic: str
    command: str
    sequence_id: str
    elapsed_ms: int


class BambuSession:
    """一次性的局域网 MQTT 会话：连接 → 发布 → 断开。

    连接参数完全复刻 collector 与 ``app.plate_merger.dispatch._publish_and_wait``：
    ``bblp`` / 解密后的 access code / ``tls_set(CERT_NONE)`` +
    ``tls_insecure_set(True)``（打印机用自签证书，跳过校验才连得上）。
    **不要在这里另起一套 TLS 配置**，否则会出现「采集能连、控制连不上」的怪现象。

    用法::

        with BambuSession(target) as session:
            session.publish(BambuCommands.pause())

    超时与失败一律抛 :class:`ControlError` 子类，不做「假装成功」。
    """

    def __init__(self, target: BambuTarget, *, timeout: float | None = None) -> None:
        self._target = target
        self._timeout = float(timeout) if timeout is not None else target.timeout_s
        self._client: Any = None
        self._connected = threading.Event()
        self._published = threading.Event()
        self._connect_rc: int | None = None
        self._publish_rc: int | None = None

    # -- 上下文管理 -------------------------------------------------------

    def __enter__(self) -> BambuSession:
        self._open()
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self._close()

    # -- paho 回调 -------------------------------------------------------

    def _on_connect(self, _client: Any, _userdata: Any, _flags: Any, reason_code: Any, _properties: Any = None) -> None:
        self._connect_rc = int(getattr(reason_code, "value", reason_code) or 0)
        self._connected.set()

    def _on_publish(self, _client: Any, _userdata: Any, _mid: int, reason_code: Any = None, _properties: Any = None) -> None:
        self._publish_rc = int(getattr(reason_code, "value", reason_code) or 0) if reason_code is not None else 0
        self._published.set()

    # -- 连接 / 断开 ------------------------------------------------------

    def _open(self) -> None:
        try:
            import paho.mqtt.client as mqtt
        except ImportError as exc:  # pragma: no cover - 依赖缺失属于部署问题
            raise MqttConnectionError(
                "缺少 MQTT 客户端库，请安装 paho-mqtt==2.1.0",
                detail={"hint": "pip install paho-mqtt==2.1.0"},
            ) from exc

        target = self._target
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311)
        self._client = client
        client.on_connect = self._on_connect
        client.on_publish = self._on_publish
        client.username_pw_set(BAMBU_MQTT_USERNAME, target.access_code)
        client.tls_set(cert_reqs=ssl.CERT_NONE)
        # 拓竹局域网用自签证书，必须跳过主机名校验（与 collector 一致）
        client.tls_insecure_set(True)

        try:
            client.connect(target.host, target.port, keepalive=30)
        except OSError as exc:
            self._close()
            raise MqttConnectionError(
                "无法连接打印机 MQTT 服务",
                detail={"host": target.host, "port": target.port, "reason": exc},
            ) from exc

        client.loop_start()
        if not self._connected.wait(self._timeout):
            self._close()
            raise MqttConnectionError(
                "等待 MQTT 连接确认超时",
                detail={"host": target.host, "timeout_s": self._timeout},
            )

        if self._connect_rc:
            self._close()
            raise MqttConnectionError(
                "MQTT 鉴权被拒绝，LAN Access Code 可能已变更",
                detail={"host": target.host, "reason_code": self._connect_rc},
            )

    def _close(self) -> None:
        client, self._client = self._client, None
        if client is None:
            return
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:  # noqa: BLE001 - 关闭失败不影响已得到的结果
            logger.debug("关闭 MQTT 会话时出错", exc_info=True)

    # -- 发布 -------------------------------------------------------------

    def publish(self, payload: dict[str, Any], *, timeout: float | None = None) -> PublishResult:
        """发布一条命令并等待套接字写出确认（QoS 0）。

        :raises MqttPublishError: 会话已断开、发布被拒或确认超时。
        """
        if self._client is None:
            raise MqttPublishError("MQTT 会话未建立，请重新创建 BambuSession")

        wait_s = float(timeout) if timeout is not None else self._timeout
        topic = self._target.request_topic
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

        self._published.clear()
        self._publish_rc = None
        started = time.monotonic()
        info = self._client.publish(topic, body, qos=0, retain=False)
        if info.rc != 0:
            raise MqttPublishError(
                "MQTT 发布失败（paho 返回非 0）",
                detail={"topic": topic, "reason_code": info.rc},
            )
        if not self._published.wait(wait_s):
            raise MqttPublishError(
                "MQTT 发布确认超时，命令可能未送达",
                detail={"topic": topic, "timeout_s": wait_s},
            )
        if self._publish_rc:
            raise MqttPublishError(
                "MQTT 发布被拒绝",
                detail={"topic": topic, "reason_code": self._publish_rc},
            )

        elapsed_ms = int((time.monotonic() - started) * 1000)
        command, sequence_id = _payload_identity(payload)
        logger.info(
            "控制命令已下发 printer=%s command=%s seq=%s elapsed_ms=%s",
            self._target.serial,
            command,
            sequence_id,
            elapsed_ms,
        )
        return PublishResult(topic=topic, command=command, sequence_id=sequence_id, elapsed_ms=elapsed_ms)


def _payload_identity(payload: dict[str, Any]) -> tuple[str, str]:
    """从载荷里取出 ``(command, sequence_id)``，用于日志与响应摘要。"""
    for scope in ("print", "system"):
        block = payload.get(scope)
        if isinstance(block, dict):
            return str(block.get("command") or ""), str(block.get("sequence_id") or "")
    return "", ""


def publish_command(
    target: BambuTarget,
    payload: dict[str, Any],
    *,
    timeout: float | None = None,
) -> PublishResult:
    """连接 → 发布一条命令 → 断开（同步阻塞）。

    路由层请用 ``await asyncio.to_thread(publish_command, ...)`` 调用，
    避免 paho 的阻塞连接卡住事件循环。

    :raises MqttConnectionError: 连接/鉴权失败。
    :raises MqttPublishError: 发布失败或确认超时。
    """
    with BambuSession(target, timeout=timeout) as session:
        return session.publish(payload)


# ---------------------------------------------------------------------------
# 手工验证（本任务不建测试文件，按下面步骤在开发机上跑一遍即可）
# ---------------------------------------------------------------------------


def _manual_verification_steps() -> None:
    """手工验证步骤（占位函数，不参与运行，仅作可检索的文档）。

    0. 前置：``pip install paho-mqtt==2.1.0``，打印机与开发机同网段、
       已开启局域网模式（屏幕可看到 IP / Serial / Access Code）。

    1. 纯逻辑验证（不连打印机，随时可跑，验证三条红线）::

        python3 - <<'PY'
        from app.services.bambu_protocol import validate_gcode, InvalidCommandError
        print(validate_gcode("M104 S200"))          # 通过
        for bad in ("M500", "M104 S320", "M140 S130", "G28\\nM500"):
            try:
                validate_gcode(bad)
            except InvalidCommandError as exc:
                print("rejected:", exc)
        PY

    2. 载荷形态验证（不发包，只看 JSON）::

        python3 - <<'PY'
        import json
        from app.services.bambu_protocol import BambuCommands
        print(json.dumps(BambuCommands.set_led("chamber_light", "on")))
        print(json.dumps(BambuCommands.move("X", 10)))
        print(json.dumps(BambuCommands.home("Z")))
        print(json.dumps(BambuCommands.extrude(-5)))
        PY

    3. 连真机（**打印中不要做**，先手动按暂停）::

        python3 - <<'PY'
        from app.services.bambu_protocol import BambuTarget, BambuCommands, publish_command
        t = BambuTarget(host="192.168.1.50", serial="01P00A000000000", access_code="12345678")
        print(publish_command(t, BambuCommands.set_led("chamber_light", "on")))
        PY

       预期：打印机腔灯亮、函数返回 topic/command/elapsed_ms；
       凭证错误时抛 ``MqttConnectionError``（含 ``reason_code``），
       IP 写错时抛 ``MqttConnectionError``（含 ``reason``）。

    4. REST 层验证（服务已注册 controls 路由后）::

        curl -X POST localhost:8000/printers/<uuid>/pause
        curl -X POST localhost:8000/printers/<uuid>/gcode -H 'content-type: application/json' \\
             -d '{"line":"M104 S200"}'
        curl -X POST localhost:8000/printers/<uuid>/gcode -H 'content-type: application/json' \\
             -d '{"line":"M500"}'
             # 期望 400：指令不在白名单内
        curl -X POST localhost:8000/printers/<uuid>/move -H 'content-type: application/json' \\
             -d '{"axis":"X","distance":10}'
             # 打印中期望 409：打印中禁止运动控制，避免撞件

    5. 真机需重点确认的载荷字段（若固件忽略命令，多半是这里对不上）：
       ``print_speed.param`` 类型、``calibration``/``print_option`` 的字段名、
       ``ams_change_filament`` 是否额外需要 ``curr_temp``/``tar_temp``、
       ``ledctrl`` 是否必须带 ``led_on_time``/``loop_times`` 等节奏字段。
    """
