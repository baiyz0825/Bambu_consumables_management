"""换盘码渲染：把参数转换成驱动机械动作的 G-code。

设计原则：

1. **动作顺序固定，只开放数值**。顺序本身就是机械语义（先降热床到托盘高度、
   再越位卸盘、最后拉新盘），开放编辑没有收益，只有撞机风险。
2. **单一数据源**：先构建动作列表 :class:`_Action`，渲染与时长估算都消费同一份列表，
   避免「渲染改了、估算忘改」的漂移。
3. **纯函数**：相同参数必然得到相同文本，便于快照测试与回归比对。
4. **硬约束前置**：渲染前必须通过 :func:`validate_params`。

基准文件：``hardware/换板套件资料第二代/换盘代码/0623 code.gcode``（A1 第二代套件）。
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import SwapCodeError
from .models import ApproachMode, SwapParams

#: 推盘前的 Y 轴预抖位置与进给（来自基准文件实测，三处进给并不相同）
_Y_APPROACH_PRE = ((15.0, 2000), (150.0, 1200), (40.0, 1200))
#: 卸盘前的中位停靠点
_Y_PARK = 120.0
#: 第二次推盘前的 Y 轴预备位置与进给
_Y_PULL_PRE = ((235.0, 1200), (110.0, 5000), (200.0, 1200))
#: 拉新盘前的起始位置
_Y_PULL_START = 40.0
#: 换盘结束时的停靠位置
_Y_FINAL = 120.0

#: 慢速进给（mm/min）
_FEED_SLOW = 1200
#: 中速进给
_FEED_MEDIUM = 2000
#: 快速进给
_FEED_FAST = 4000
#: 力控推盘使用的进给
_FEED_FORCE = 2000
#: 估算 G28 归零耗时（秒）
_HOME_SECONDS = 3.0


def _fmt(value: float) -> str:
    """格式化数值：整数不带小数点，小数保留有效位（``1.5`` 而非 ``1.50``）。"""
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:g}"


@dataclass(frozen=True)
class _Action:
    """一条待输出动作。

    ``text`` 为最终写入 G-code 的整行；运动与停留元数据用于时长估算，
    与 ``text`` 同源，杜绝两处逻辑不一致。
    """

    text: str
    axis: str | None = None
    target: float = 0.0
    feedrate: int = 0
    dwell_ms: int = 0
    homing: bool = False


def _build_actions(params: SwapParams) -> list[_Action]:
    """按机械动作顺序构建动作列表。"""
    actions: list[_Action] = []

    def line(text: str) -> None:
        actions.append(_Action(text=text))

    def move(axis: str, target: float, feedrate: int) -> None:
        actions.append(
            _Action(
                text=f"G1 {axis}{_fmt(target)} F{feedrate}",
                axis=axis,
                target=target,
                feedrate=feedrate,
            )
        )

    def force(level: str, axis: str, target: float, feedrate: int) -> None:
        """力控移动：G380 在遇到阻力时提前停止，无法预知实际位移。"""
        actions.append(
            _Action(
                text=f"G380 {level} {axis}{_fmt(target)} F{feedrate}",
                axis=axis,
                target=target,
                feedrate=feedrate,
            )
        )

    def dwell(milliseconds: int) -> None:
        actions.append(_Action(text=f"G4 P{milliseconds}", dwell_ms=milliseconds))

    def comment(text: str) -> None:
        actions.append(_Action(text=f";{text}"))

    # ---------------------------------------------------------------- 起始
    line(";start change plate")
    line("")

    # 归零与推到后限位（快速档跳过归零，改为开环快速移动）
    if params.home_y_before:
        actions.append(_Action(text="G28 Y", homing=True))
        move("Y", params.y_limit - 2.0, _FEED_SLOW)
    else:
        move("Y", params.y_limit - 2.0, params.approach_feedrate)

    # ---------------------------------------------------------------- Z 力控升降
    line("G91")
    force(params.force_level_probe, "Z", params.z_probe_down, _FEED_SLOW)
    for index in range(params.z_probe_cycles):
        force(params.force_level_push, "Z", params.z_probe_up, _FEED_SLOW)
        if index < params.z_probe_cycles - 1:
            force(params.force_level_probe, "Z", params.z_probe_mid_down, _FEED_SLOW)
    move("Z", params.z_settle, _FEED_SLOW)
    line("G90;")

    dwell(params.dwell_after_z_ms)

    # ---------------------------------------------------------------- 推盘
    for position, feedrate in _Y_APPROACH_PRE:
        move("Y", position, feedrate)
    if params.approach_mode is ApproachMode.FORCE:
        force(params.force_level_push, "Y", params.approach_target, _FEED_FORCE)
    else:
        move("Y", params.approach_target, params.approach_feedrate)

    # 抬升热床到卸盘高度
    line("G91;")
    move("Z", params.z_lift_before_eject, _FEED_SLOW)
    line("G90;")

    move("Y", _Y_PARK, _FEED_FAST)

    # ---------------------------------------------------------------- 卸旧盘
    actions.append(_Action(text="G28 Y", homing=True))
    # 刻意不使用 G380：力控可能在错误位置提前停止，导致旧盘未能脱落
    move("Y", params.eject_offset, _FEED_SLOW)
    dwell(params.shake_dwell_ms)

    actions.extend(_build_shake(params))

    # ---------------------------------------------------------------- 拉新盘
    for position, feedrate in _Y_PULL_PRE:
        move("Y", position, feedrate)
    if params.approach_mode is ApproachMode.FORCE:
        force(params.force_level_push, "Y", params.approach_target, _FEED_FORCE)
    else:
        move("Y", params.approach_target, params.approach_feedrate)

    dwell(params.dwell_before_pull_ms)

    move("Y", _Y_PULL_START, _FEED_FAST)
    move("Y", params.pull_offset, 5000)

    actions.extend(_build_shake(params))

    move("Y", _Y_FINAL, _FEED_MEDIUM)

    # ---------------------------------------------------------------- 结束
    line(";end change plate")
    return actions


def _build_shake(params: SwapParams) -> list[_Action]:
    """构建「抖动脱盘」序列。

    物理含义：低速小幅越位把盘推到临界，再高速回拉，用惯性让盘脱开限位落到位。
    越位由轻到重、回拉由快到慢，是一套自适应的力度递增策略。
    """
    actions: list[_Action] = [_Action(text=";start  Shake-triggered plate replacement")]

    total = len(params.shake_offsets)
    for index, (offset, retract_feed) in enumerate(zip(params.shake_offsets, params.retract_feedrates)):
        actions.append(
            _Action(
                text=f"G1 Y{_fmt(offset)} F{params.shake_feedrate}",
                axis="Y",
                target=offset,
                feedrate=params.shake_feedrate,
            )
        )
        actions.append(
            _Action(
                text=f"G1 Y0 F{retract_feed}",
                axis="Y",
                target=0.0,
                feedrate=retract_feed,
            )
        )
        # 最后一组不额外停留：紧接着就是下一段动作，停留反而拖慢节奏
        if index < total - 1:
            actions.append(_Action(text=f"G4 P{params.shake_dwell_ms}", dwell_ms=params.shake_dwell_ms))

    actions.append(_Action(text=";end   Shake-triggered plate replacement"))
    return actions


def render_swap_code(params: SwapParams, *, newline: str = "\n") -> str:
    """渲染完整换盘 G-code。

    :param params: 已通过 :func:`validate_params` 的参数。
    :param newline: 换行符，应与目标文件保持一致。
    """
    issues = validate_params(params)
    if issues:
        raise SwapCodeError("换盘码参数非法", detail={"issues": "; ".join(issues)})

    actions = _build_actions(params)
    return newline.join(action.text for action in actions) + newline


def validate_params(params: SwapParams) -> list[str]:
    """校验参数，返回问题描述列表（空列表表示通过）。

    集中在此处校验的原因：同一套约束要被 CLI、Web 表单与流水线复用。
    """
    issues: list[str] = []

    if params.eject_offset > -1:
        issues.append(f"卸盘越位量必须 <= -1，当前 {params.eject_offset}")
    if params.pull_offset > -1:
        issues.append(f"拉盘越位量必须 <= -1，当前 {params.pull_offset}")
    if params.approach_target > params.y_limit:
        issues.append(f"推盘目标 {params.approach_target} 超出 Y 行程上限 {params.y_limit}")
    if params.y_limit <= 0:
        issues.append("Y 行程上限必须为正数")
    if params.shake_feedrate <= 0:
        issues.append("抖动进给必须为正数")
    if params.approach_feedrate <= 0:
        issues.append("开环推盘进给必须为正数")
    if len(params.shake_offsets) != len(params.retract_feedrates):
        issues.append(
            f"抖动越位与回位进给数量不一致：{len(params.shake_offsets)} vs {len(params.retract_feedrates)}"
        )
    if not params.shake_offsets:
        issues.append("抖动越位序列不能为空")
    if params.z_probe_cycles < 1:
        issues.append("Z 力控循环次数必须 >= 1")
    if params.z_probe_up <= 0:
        issues.append("Z 抬升量必须为正数")

    return issues


def estimate_duration_s(params: SwapParams) -> float:
    """估算一次换盘的动作耗时（秒）。

    说明：``G380`` 是力控移动，实际位移取决于阻力，这里按**名义位移**计算，
    作为档位间横向比较与排产预估的近似值，不是精确墙钟时间。
    """
    clock_y = _Y_FINAL  # 换盘开始时热床通常停在靠前位置
    clock_z = 0.0
    seconds = 0.0

    for action in _build_actions(params):
        if action.homing:
            seconds += _HOME_SECONDS
            clock_y = 0.0
            continue
        if action.dwell_ms:
            seconds += action.dwell_ms / 1000.0
        if action.axis and action.feedrate > 0:
            current = clock_y if action.axis == "Y" else clock_z
            distance = abs(action.target - current)
            seconds += distance / (action.feedrate / 60.0)
            if action.axis == "Y":
                clock_y = action.target
            else:
                clock_z = action.target

    return round(seconds, 1)
