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
