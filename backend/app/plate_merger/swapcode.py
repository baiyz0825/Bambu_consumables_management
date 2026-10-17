"""换盘码渲染：把参数转换成驱动机械动作的 G-code。

设计原则：

1. **动作顺序固定，只开放数值**。顺序本身就是机械语义（先降热床到托盘高度、
   再越位卸盘、最后拉新盘），开放编辑没有收益，只有撞机风险。
2. **单一数据源**：先构建动作列表 :class:`_Action`，渲染与时长估算都消费同一份列表。
   动作自带「坐标系模式」标记，估算器据此区分绝对坐标与相对增量，避免两套算法漂移。
3. **纯函数**：相同参数必然得到相同文本，便于快照测试与回归比对。
4. **硬约束前置**：渲染前必须通过 :func:`validate_params`；估算入口同样先校验。

基准文件：``hardware/换板套件资料第二代/换盘代码/0623 code.gcode``（A1 第二代套件）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import SwapCodeError
from .models import ApproachMode, SwapParams

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
#: 力控档位必须是 ``S<数字>``，防止把任意字符串注入 G-code
_FORCE_LEVEL_PATTERN = re.compile(r"^S\d+$")


def _fmt(value: float) -> str:
    """格式化数值：整数不带小数点，小数去掉尾随零。

    不使用 ``:g``，因为它在极小值时会输出 ``1e-07`` 这类非法的 G-code 数值。
    """
    number = float(value)
    if number.is_integer():
        return str(int(number))
    text = f"{number:.6f}".rstrip("0").rstrip(".")
    return text or "0"


@dataclass(frozen=True)
class _Action:
    """一条待输出动作。

    ``text`` 为最终写入 G-code 的整行；运动元数据用于时长估算，与 ``text`` 同源。

    ``relative`` 用于标记坐标系模式切换：

    - ``None``：普通指令，不改变模式
    - ``True``：本行动作是 ``G91``（进入相对模式）
    - ``False``：本行动作是 ``G90``（进入绝对模式）
    """

    text: str
    axis: str | None = None
    target: float = 0.0
    feedrate: int = 0
    dwell_ms: int = 0
    homing: bool = False
    relative: bool | None = None


def _build_actions(params: SwapParams, *, start_flag: str, end_flag: str) -> list[_Action]:
    """按机械动作顺序编排各阶段。"""
    actions: list[_Action] = []
    actions.append(_Action(text=start_flag))
    actions.append(_Action(text=""))

    actions.extend(_actions_initial_positioning(params))
    actions.extend(_actions_z_probe(params))
    actions.extend(_actions_push(params))
    actions.extend(_actions_eject(params))
    actions.extend(_actions_pull(params))

    actions.append(_Action(text=end_flag))
    return actions


def _actions_initial_positioning(params: SwapParams) -> list[_Action]:
    """归零并移动到 Y 后限位附近。"""
    actions: list[_Action] = []
    if params.home_y_before:
        actions.append(_Action(text="G28 Y", homing=True))
        actions.append(
            _Action(text=f"G1 Y{_fmt(params.y_limit - 2.0)} F{_FEED_SLOW}", axis="Y", target=params.y_limit - 2.0, feedrate=_FEED_SLOW)
        )
    else:
        # 快速档：跳过归零，直接以开环进给移动，缩短节拍
        target = params.y_limit - 2.0
        actions.append(
            _Action(text=f"G1 Y{_fmt(target)} F{params.approach_feedrate}", axis="Y", target=target, feedrate=params.approach_feedrate)
        )
    return actions


def _actions_z_probe(params: SwapParams) -> list[_Action]:
    """用 Z 轴力控升降把热床对齐到盘架高度。

    序列为「一次下压 + 若干次（抬升、回落）+ 收尾微调」，
    净位移由 :func:`estimate_duration_s` 按相对增量累计。
    """
    actions: list[_Action] = [_Action(text="G91", relative=True)]

    def force(level: str, target: float) -> None:
        actions.append(
            _Action(
                text=f"G380 {level} Z{_fmt(target)} F{_FEED_SLOW}",
                axis="Z",
                target=target,
                feedrate=_FEED_SLOW,
            )
        )

    force(params.force_level_probe, params.z_probe_down)
    for index in range(params.z_probe_cycles):
        force(params.force_level_push, params.z_probe_up)
        if index < params.z_probe_cycles - 1:
            force(params.force_level_probe, params.z_probe_mid_down)

    actions.append(
        _Action(text=f"G1 Z{_fmt(params.z_settle)} F{_FEED_SLOW}", axis="Z", target=params.z_settle, feedrate=_FEED_SLOW)
    )
    actions.append(_Action(text="G90;", relative=False))

    if params.dwell_after_z_ms > 0:
        actions.append(_Action(text=f"G4 P{params.dwell_after_z_ms}", dwell_ms=params.dwell_after_z_ms))
    return actions


def _push_to_limit(params: SwapParams) -> list[_Action]:
    """推热床到后限位（力控或开环）。"""
    if params.approach_mode is ApproachMode.FORCE:
        return [
            _Action(
                text=f"G380 {params.force_level_push} Y{_fmt(params.approach_target)} F{_FEED_FORCE}",
                axis="Y",
                target=params.approach_target,
                feedrate=_FEED_FORCE,
            )
        ]
    return [
        _Action(
            text=f"G1 Y{_fmt(params.approach_target)} F{params.approach_feedrate}",
            axis="Y",
            target=params.approach_target,
            feedrate=params.approach_feedrate,
        )
    ]


def _actions_push(params: SwapParams) -> list[_Action]:
    """预抖定位后推到后限位，并抬升热床到卸盘高度。"""
    actions: list[_Action] = []
    for position, feedrate in zip(params.y_approach_pre, params.y_approach_pre_feeds):
        actions.append(
            _Action(text=f"G1 Y{_fmt(position)} F{feedrate}", axis="Y", target=position, feedrate=feedrate)
        )
    actions.extend(_push_to_limit(params))

    actions.append(_Action(text="G91;", relative=True))
    actions.append(
        _Action(
            text=f"G1 Z{_fmt(params.z_lift_before_eject)} F{_FEED_SLOW}",
            axis="Z",
            target=params.z_lift_before_eject,
            feedrate=_FEED_SLOW,
        )
    )
    actions.append(_Action(text="G90;", relative=False))

    actions.append(
        _Action(
            text=f"G1 Y{_fmt(params.y_park)} F{_FEED_FAST}",
            axis="Y",
            target=params.y_park,
            feedrate=_FEED_FAST,
        )
    )
    return actions


def _actions_eject(params: SwapParams) -> list[_Action]:
    """卸旧盘：归零后越位，让前端退盘机构推落旧盘。

    卸盘前的 ``G28 Y`` 是**无条件**的 —— 与开头的首次归零不同，
    这里必须先回零才能保证越位量准确。
    """
    actions: list[_Action] = [_Action(text="G28 Y", homing=True)]
    # 刻意不使用 G380：力控可能在错误位置提前停止，导致旧盘未脱落
    actions.append(
        _Action(
            text=f"G1 Y{_fmt(params.eject_offset)} F{_FEED_SLOW}",
            axis="Y",
            target=params.eject_offset,
            feedrate=_FEED_SLOW,
        )
    )
    if params.shake_dwell_ms > 0:
        actions.append(_Action(text=f"G4 P{params.shake_dwell_ms}", dwell_ms=params.shake_dwell_ms))
    actions.extend(_build_shake(params))
    return actions


def _actions_pull(params: SwapParams) -> list[_Action]:
    """拉新盘：再次推到最后端让拉盘钩勾住盘夹，然后越位把盘拖到热床。"""
    actions: list[_Action] = []
    for position, feedrate in zip(params.y_pull_pre, params.y_pull_pre_feeds):
        actions.append(
            _Action(text=f"G1 Y{_fmt(position)} F{feedrate}", axis="Y", target=position, feedrate=feedrate)
        )
    actions.extend(_push_to_limit(params))

    if params.dwell_before_pull_ms > 0:
        actions.append(_Action(text=f"G4 P{params.dwell_before_pull_ms}", dwell_ms=params.dwell_before_pull_ms))

    actions.append(
        _Action(
            text=f"G1 Y{_fmt(params.y_pull_start)} F{params.y_pull_start_feed}",
            axis="Y",
            target=params.y_pull_start,
            feedrate=params.y_pull_start_feed,
        )
    )
    actions.append(
        _Action(
            text=f"G1 Y{_fmt(params.pull_offset)} F{params.pull_feedrate}",
            axis="Y",
            target=params.pull_offset,
            feedrate=params.pull_feedrate,
        )
    )

    actions.extend(_build_shake(params))

    actions.append(
        _Action(
            text=f"G1 Y{_fmt(params.y_final)} F{params.y_final_feed}",
            axis="Y",
            target=params.y_final,
            feedrate=params.y_final_feed,
        )
    )
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
            _Action(text=f"G1 Y0 F{retract_feed}", axis="Y", target=0.0, feedrate=retract_feed)
        )
        # 最后一组不额外停留：紧接着就是下一段动作，停留反而拖慢节奏
        if index < total - 1 and params.shake_dwell_ms > 0:
            actions.append(_Action(text=f"G4 P{params.shake_dwell_ms}", dwell_ms=params.shake_dwell_ms))

    actions.append(_Action(text=";end   Shake-triggered plate replacement"))
    return actions


def render_swap_code(
    params: SwapParams,
    *,
    newline: str = "\n",
    start_flag: str = ";start change plate",
    end_flag: str = ";end change plate",
) -> str:
    """渲染完整换盘 G-code。

    :param params: 换盘参数，内部会先做一次完整校验。
    :param newline: 换行符，应与目标文件保持一致（CRLF / LF）。
    :param start_flag: 起始标记，需与 :class:`MergeOptions` 的配置一致。
    :param end_flag: 结束标记。
    :raises SwapCodeError: 参数不合法。
    """
    issues = validate_params(params)
    if issues:
        raise SwapCodeError("换盘码参数非法", detail={"issues": "; ".join(issues)})

    actions = _build_actions(params, start_flag=start_flag, end_flag=end_flag)
    return newline.join(action.text for action in actions) + newline


def _all_y_positions(params: SwapParams) -> list[float]:
    """收集渲染器会用到的全部绝对 Y 坐标，用于行程校验。"""
    return [
        *params.y_approach_pre,
        *params.y_pull_pre,
        params.y_park,
        params.y_pull_start,
        params.y_final,
        params.approach_target,
        params.y_limit - 2.0,
    ]


def validate_params(params: SwapParams) -> list[str]:
    """校验参数，返回问题描述列表（空列表表示通过）。

    集中校验的原因：同一套约束要被 CLI、Web 表单与流水线复用。
    这里覆盖的不仅是「数值合理」，还包括**会让机械动作反向或超出行程**的符号与边界。
    """
    issues: list[str] = []

    # ---- 越位量：卸盘与拉盘都依赖物理越位，任何放宽都会导致换盘失败
    if params.eject_offset > -1:
        issues.append(f"卸盘越位量必须 <= -1，当前 {params.eject_offset}")
    if params.pull_offset > -1:
        issues.append(f"拉盘越位量必须 <= -1，当前 {params.pull_offset}")

    # ---- Y 行程
    if params.y_limit <= 0:
        issues.append("Y 行程上限必须为正数")
    if not 0 <= params.approach_target <= params.y_limit:
        issues.append(f"推盘目标 {params.approach_target} 必须在 [0, {params.y_limit}] 内")
    for position in _all_y_positions(params):
        if position < 0:
            issues.append(f"Y 目标坐标不能为负：{position}")
            break
    for position in _all_y_positions(params):
        if position > params.y_limit:
            issues.append(f"Y 目标坐标 {position} 超出行程上限 {params.y_limit}")
            break

    # ---- 序列长度必须一一对应，否则 zip 会静默截断动作
    if len(params.y_approach_pre) != len(params.y_approach_pre_feeds):
        issues.append("预抖位置与进给数量不一致")
    if len(params.y_pull_pre) != len(params.y_pull_pre_feeds):
        issues.append("拉盘预备位置与进给数量不一致")

    # ---- Z 符号：负值表示热床上升，写反会导致反向撞机
    if params.z_probe_down >= 0:
        issues.append(f"Z 首次下压量必须为负，当前 {params.z_probe_down}")
    if params.z_probe_mid_down >= 0:
        issues.append(f"Z 回落量必须为负，当前 {params.z_probe_mid_down}")
    if params.z_settle >= 0:
        issues.append(f"Z 收尾微调必须为负，当前 {params.z_settle}")
    if params.z_lift_before_eject >= 0:
        issues.append(f"卸盘前 Z 抬升量必须为负，当前 {params.z_lift_before_eject}")
    if params.z_probe_up <= 0:
        issues.append(f"Z 抬升量必须为正，当前 {params.z_probe_up}")
    if params.z_probe_cycles < 1:
        issues.append("Z 力控循环次数必须 >= 1")

    # ---- 抖动序列
    if not params.shake_offsets:
        issues.append("抖动越位序列不能为空")
    if len(params.shake_offsets) != len(params.retract_feedrates):
        issues.append(
            f"抖动越位与回位进给数量不一致：{len(params.shake_offsets)} vs {len(params.retract_feedrates)}"
        )
    if any(offset <= 0 for offset in params.shake_offsets):
        issues.append("抖动越位量必须全部为正")
    if list(params.shake_offsets) != sorted(params.shake_offsets):
        issues.append("抖动越位序列应由轻到重递增")

    # ---- 进给与停留
    for label, value in (
        ("抖动进给", params.shake_feedrate),
        ("开环推盘进给", params.approach_feedrate),
        ("拉盘越位进给", params.pull_feedrate),
        ("拉盘起始进给", params.y_pull_start_feed),
        ("结束停靠进给", params.y_final_feed),
    ):
        if value <= 0:
            issues.append(f"{label}必须为正数，当前 {value}")
    for label, dwell in (
        ("抖动停留", params.shake_dwell_ms),
        ("Z 后停留", params.dwell_after_z_ms),
        ("拉盘前停留", params.dwell_before_pull_ms),
    ):
        if dwell < 0:
            issues.append(f"{label}不能为负，当前 {dwell}")

    # ---- 力控档位会被直接插值进 G-code，必须限制形状
    for label, level in (("推盘", params.force_level_push), ("探测", params.force_level_probe)):
        if not _FORCE_LEVEL_PATTERN.match(level):
            issues.append(f"{label}力控档位必须形如 S2，当前 {level!r}")

    return issues


def estimate_duration_s(params: SwapParams) -> float:
    """估算一次换盘的动作耗时（秒）。

    与 :func:`render_swap_code` 消费**同一份动作列表**，并按 ``G91``/``G90``
    区分相对增量与绝对坐标，避免把增量当绝对位置累计。

    说明：``G380`` 是力控移动，实际位移取决于阻力，这里按**名义位移**计算，
    用于档位间横向比较与排产预估，不是精确墙钟时间。

    :raises SwapCodeError: 参数不合法（与渲染保持一致的行为）。
    """
    issues = validate_params(params)
    if issues:
        raise SwapCodeError("换盘码参数非法", detail={"issues": "; ".join(issues)})

    actions = _build_actions(params, start_flag="", end_flag="")
    clock_y = params.y_final  # 换盘开始时热床通常停在靠前位置
    clock_z = 0.0
    relative = False
    seconds = 0.0

    for action in actions:
        # 坐标系模式切换
        if action.relative is not None:
            relative = action.relative
            continue

        if action.homing:
            seconds += _HOME_SECONDS
            clock_y = 0.0
            continue

        if action.dwell_ms:
            seconds += action.dwell_ms / 1000.0

        if action.axis and action.feedrate > 0:
            if action.axis == "Y":
                distance = abs(action.target) if relative else abs(action.target - clock_y)
                clock_y = clock_y + action.target if relative else action.target
            else:
                distance = abs(action.target) if relative else abs(action.target - clock_z)
                clock_z = clock_z + action.target if relative else action.target
            seconds += distance / (action.feedrate / 60.0)

    return round(seconds, 1)
