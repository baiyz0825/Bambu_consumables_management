"""内置换盘码预设。

三档的来源与差异：

- **保守档**：完整 ``0623 code.gcode``，含 ``G28 Y`` 归零与 ``G380`` 力控推盘，最稳。
- **均衡档**：保留力控与归零，仅压缩停留时间，在可靠性与速度之间取中。
- **快速档**：跳过归零、改为开环 ``G1`` 推盘（对应 10 盘测试文件第 2–8 块的做法），最快，
  但依赖机械一致性。

内置预设是不可变对象：调用方要调整参数时应使用 ``dataclasses.replace`` 派生新对象，
从而天然保留「预置打底」的语义。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from types import MappingProxyType

from .errors import SwapCodeError
from .models import ApproachMode, SwapParams

#: 保守档（等价于基准文件）
CONSERVATIVE = SwapParams(
    preset_id="builtin:a1-conservative",
    name="A1 第二代套件 · 保守档",
    machine="A1",
)

#: 均衡档：保留力控与归零，压缩停留
BALANCED = replace(
    CONSERVATIVE,
    preset_id="builtin:a1-balanced",
    name="A1 第二代套件 · 均衡档",
    dwell_after_z_ms=1000,
    dwell_before_pull_ms=500,
    shake_dwell_ms=300,
)

#: 快速档：跳过归零、开环推盘
FAST = replace(
    CONSERVATIVE,
    preset_id="builtin:a1-fast",
    name="A1 第二代套件 · 快速档",
    approach_mode=ApproachMode.OPEN,
    approach_target=260.0,
    approach_feedrate=3000,
    home_y_before=False,
    dwell_after_z_ms=0,
    dwell_before_pull_ms=0,
    shake_dwell_ms=300,
)

#: 预设索引：ID -> 参数对象。只读代理，防止外部注册表被就地污染。
BUILTIN_PRESETS: Mapping[str, SwapParams] = MappingProxyType(
    {preset.preset_id: preset for preset in (CONSERVATIVE, BALANCED, FAST)}
)


def list_presets() -> tuple[SwapParams, ...]:
    """按稳定顺序返回全部内置预设。"""
    return (CONSERVATIVE, BALANCED, FAST)


#: 允许调用方覆盖的参数（只开放数值与开关；**动作顺序由渲染器固定**，
#: 因为顺序本身即机械动作的语义，开放编辑极易撞机）。
EDITABLE_FIELDS: Mapping[str, str] = MappingProxyType(
    {
        "y_limit": "Y 轴行程上限（mm）",
        "approach_target": "推盘目标位置（mm）",
        "approach_feedrate": "开环推盘进给（mm/min）",
        "home_y_before": "推盘前是否 G28 Y 归零",
        "dwell_after_z_ms": "Z 到位后停留（ms）",
        "dwell_before_pull_ms": "拉盘前停留（ms）",
        "shake_dwell_ms": "抖盘后停留（ms）",
    }
)

#: 覆盖值的目标类型，前端传来的 JSON 数字需要显式收敛
_CASTERS: Mapping[str, type] = MappingProxyType(
    {
        "y_limit": float,
        "approach_target": float,
        "approach_feedrate": int,
        "home_y_before": bool,
        "dwell_after_z_ms": int,
        "dwell_before_pull_ms": int,
        "shake_dwell_ms": int,
    }
)


def resolve_preset(preset_id: str, overrides: Mapping[str, object] | None = None) -> SwapParams:
    """在预设基础上应用覆盖参数，返回新的 ``SwapParams``。

    未知字段**直接报错**而不是静默忽略——静默忽略会让用户以为改动生效了，
    实际没有，这对换盘动作是危险的。

    :raises SwapCodeError: 预设不存在，或覆盖字段非法。
    """
    base = get_preset(preset_id)
    if not overrides:
        return base

    unknown = sorted(set(overrides) - {k for k in EDITABLE_FIELDS if overrides.get(k) is not None})
    if unknown:
        raise SwapCodeError(
            "存在不可覆盖的换盘参数",
            detail={"unknown": unknown, "editable": sorted(EDITABLE_FIELDS)},
        )

    cleaned: dict[str, object] = {}
    for key, value in overrides.items():
        if value is None:
            continue
        try:
            cleaned[key] = _CASTERS[key](value)
        except (TypeError, ValueError) as exc:
            raise SwapCodeError(
                f"换盘参数 {key} 的值不合法",
                detail={"value": value},
            ) from exc

    return replace(base, **cleaned)


def get_preset(preset_id: str) -> SwapParams:
    """按 ID 取内置预设。

    :raises SwapCodeError: 预设不存在。
    """
    preset = BUILTIN_PRESETS.get(preset_id)
    if preset is None:
        raise SwapCodeError(
            "未知的换盘码预设",
            detail={"preset_id": preset_id, "available": sorted(BUILTIN_PRESETS)},
        )
    return preset
