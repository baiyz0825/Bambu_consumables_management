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

from .errors import MissingAnchorError
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


#: 结束序列的锚点：退料指令（优先）与关闭喷嘴（兜底）
_UNLOAD_ANCHOR = re.compile(r"^M62[01]\s+S255")
_HOTEND_OFF_ANCHOR = re.compile(r"^M104\s+S0\b")
_POWER_OFF = re.compile(r"^M18\b")
#: 结束音乐标记（与 ``;=====start printer sound`` 区分）
_FINISH_SOUND = re.compile(r";=====printer finish\s+sound")


def _find_end_anchor(lines: list[str]) -> int | None:
    """从尾部向前找结束序列的起始行索引。

    实测结构（Bambu 原生）::

        M621 S255            ← 退料，结束序列起点
        M104 S0 ; turn off hotend
        M400
        M17 Z0.4 / G1 Z135   ← 抬 Z
        ...
        ;=====printer finish  sound=========   ← 结束音乐
        M18 X Y Z            ← 电机断电

    优先以退料为锚点；没有退料时退化为关闭喷嘴。
    """
    for index in range(len(lines) - 1, -1, -1):
        code = lines[index].strip()
        if _UNLOAD_ANCHOR.match(code):
            return index
    for index in range(len(lines) - 1, -1, -1):
        code = lines[index].strip()
        if _HOTEND_OFF_ANCHOR.match(code):
            return index
    return None


def _find_finish_sound(lines: list[str]) -> int | None:
    """从尾部向前找结束音乐标记所在行索引。"""
    for index in range(len(lines) - 1, -1, -1):
        if _FINISH_SOUND.search(lines[index]):
            return index
    return None


def trim_executable_tail(body: str, policy: StartEndPolicy) -> str:
    """裁剪 ``EXECUTABLE`` 正文尾部的结束序列（中间盘专用）。

    这是合盘最关键的一步：Bambu 的关加热、**抬 Z**、结束音乐与 ``M18`` 断电
    **全部位于 EXECUTABLE 段内部**。

    裁剪点必须保留「抬 Z + 移到后部」—— 它把喷嘴抬离零件并让出换盘空间；
    若只截到退料行，喷嘴会停在零件顶面，随后换盘码的 Y 全行程移动会撞件。

    三档行为：

    - ``FULL``：只剥离 ``M18`` 断电（且只作用于结束序列区，避免误伤启动段），
      保留降温、退料、抬 Z 与提示音；
    - ``SLIM``：截断到**结束音乐之前**，保留退料、关喷嘴、抬 Z 与移位；
    - ``TURBO``：同 ``SLIM``，但额外去掉退料行。

    :param body: 不含 ``EXECUTABLE_BLOCK_END`` 标记的正文。
    :return: 裁剪后的正文。
    :raises MissingAnchorError: 找不到任何结束序列锚点，无法安全裁剪。
    """
    if not body:
        return body

    lines = body.splitlines(keepends=True)

    if policy is StartEndPolicy.FULL:
        anchor = _find_end_anchor(lines)
        start = 0 if anchor is None else anchor
        kept = [
            line
            for index, line in enumerate(lines)
            if not (index >= start and _POWER_OFF.match(line.strip()))
        ]
        return "".join(kept)

    music = _find_finish_sound(lines)
    if music is not None:
        kept = lines[:music]
    else:
        anchor = _find_end_anchor(lines)
        if anchor is None:
            raise MissingAnchorError(
                "未找到结束序列锚点，无法安全裁剪",
                detail={"policy": policy.value, "lines": len(lines)},
            )
        kept = lines[: anchor + 1]

    if policy is StartEndPolicy.TURBO:
        kept = [line for line in kept if not _UNLOAD_ANCHOR.match(line.strip())]

    return "".join(kept)
