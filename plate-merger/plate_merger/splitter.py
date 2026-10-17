"""中间盘 start/end 段的裁剪策略。

合盘时只有**第一盘**使用完整的 start 段，只有**最后一盘**使用完整的 end 段；
中间盘的 start 段直接丢弃，end 段按策略裁剪。

为什么要裁剪 end 段：中间盘的 end 会关加热、关风扇、归位、甚至退料。
若不裁剪，每换一盘都会重新降温、重新调平，既浪费时间，也让热床在换盘时温度不足。

三档策略（技术方案 §5）：

- ``FULL``  不裁剪：最稳，最慢。
- ``SLIM``  剥离降温/关床/关风扇/归位，**保留退料**：默认档，避免喷嘴带料换盘。
- ``TURBO`` 连退料一起剥离：最快，但需实机验证带料换盘的滴料风险。
"""

from __future__ import annotations

import re

from .models import StartEndPolicy

#: 无论哪一档都剥离的指令：关闭加热、风扇与电机，或执行归位
_DROP_ALWAYS = (
    re.compile(r"^M10[46]\s+S0\b"),   # 关闭喷嘴
    re.compile(r"^M140\s+S0\b"),      # 关闭热床
    re.compile(r"^M190\s+S0\b"),      # 关闭热床并等待
    re.compile(r"^M106\b.*\bS0\b"),   # 关闭风扇
    re.compile(r"^M107\b"),           # 关闭风扇（等价写法）
    re.compile(r"^M18\b"),            # 电机断电
    re.compile(r"^G28\b"),            # 归位
)

#: 仅在 ``TURBO`` 档额外剥离：退料与工具切换。
#: 注意不能写 ``S255\b``：``M620 S255A`` 中数字与 ``A`` 之间不构成单词边界。
_DROP_TURBO_ONLY = (
    re.compile(r"^M62[01]\s+S255(?!\d)"),  # 退料
    re.compile(r"^T255(?!\d)"),
)


def should_drop(line: str, policy: StartEndPolicy) -> bool:
    """判断某一行在给定策略下是否应被剥离。"""
    if policy is StartEndPolicy.FULL:
        return False

    code = line.strip()
    if not code or code.startswith(";"):
        return False

    if any(pattern.search(code) for pattern in _DROP_ALWAYS):
        return True

    if policy is StartEndPolicy.TURBO:
        return any(pattern.search(code) for pattern in _DROP_TURBO_ONLY)

    return False


def trim_epilogue(text: str, policy: StartEndPolicy) -> str:
    """按策略裁剪 end 段。

    保留原有换行符与注释行，只删除命中的指令行。
    """
    if policy is StartEndPolicy.FULL or not text:
        return text

    kept: list[str] = []
    for line in text.splitlines(keepends=True):
        if should_drop(line, policy):
            continue
        kept.append(line)
    return "".join(kept)


def contains_swap_code(text: str, *flags: str) -> bool:
    """判断文本中是否已包含换盘码（用于避免重复注入）。

    :param flags: 起止标记，任一命中即认为已包含。
    """
    return any(flag and flag in text for flag in flags)
