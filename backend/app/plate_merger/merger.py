"""多盘 G-code 拼接与换盘码注入。

拼接顺序（N 个盘）：

.. code-block:: text

    [第 1 盘 preamble]          完整 start 段（加热 / 归零 / 调平 / 擦嘴）
    [第 1 盘 executable]        打印动作
    [第 1 盘 epilogue 裁剪]     保留退料，剥离降温与断电
    [换盘码]                    ← 此处完成一次机械换盘
    [第 2 盘 executable]
    [第 2 盘 epilogue 裁剪]
    [换盘码]
    ...
    [第 N 盘 executable]
    [第 N 盘 epilogue 完整]     完整 end 段（含结束音乐）

关键约束：

- 中间盘**不使用** preamble，否则每盘都会重新加热、调平；
- 换盘码插在**退料之后**，保证喷嘴不带料换盘；
- 换盘码位置不能早于 ``EXECUTABLE_BLOCK_END``，否则会打断打印路径。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .audio import render_audio
from .errors import ValidationError
from .filament import remap_gcode
from .gcode import GcodeBlocks, detect_newline
from .models import MergeOptions, PlateDisplay
from .splitter import trim_epilogue, trim_executable_tail
from .swapcode import render_swap_code


@dataclass(frozen=True)
class PlateSegment:
    """参与拼接的单盘素材。

    :param index: 盘号（1-based）。
    :param blocks: 该盘 G-code 的三段结构。
    :param mapping: 本地槽位 -> 全局槽位。
    """

    index: int
    blocks: GcodeBlocks
    mapping: Mapping[int, int] = field(default_factory=dict)


@dataclass(frozen=True)
class MergeOutcome:
    """拼接结果。"""

    text: str
    plate_count: int
    swap_count: int


def build_swap_block(
    options: MergeOptions,
    *,
    plate_index: int = 1,
    total_plates: int = 1,
    newline: str = "\n",
) -> str:
    """构建「提示音 + 降温 + 换盘码 + 盘号 + 等待 + 完成音」的完整注入块。

    :param plate_index: 即将打印的盘号（1-based），用于屏幕显示。
    :param total_plates: 总盘数，用于 ``M117`` 文本。
    """
    parts: list[str] = []

    pre_sound = render_audio(options.pre_change_sound, newline=newline)
    if pre_sound:
        parts.append(pre_sound.rstrip("\r\n"))

    if options.hotbed_cooldown_c is not None and options.hotbed_cooldown_c >= 0:
        parts.append(f"M190 S{options.hotbed_cooldown_c} ; 热床降温")

    # 换盘码假定绝对坐标、且所有运动已结束；被裁掉的尾部不再保证这两点
    parts.append("M400 ; 等待运动完成")
    parts.append("G90 ; 强制绝对坐标")

    swap_code = render_swap_code(
        options.swap_params,
        newline=newline,
        start_flag=options.swap_start_flag,
        end_flag=options.swap_end_flag,
    )
    # render_swap_code 已带结尾换行，去掉后再统一拼接
    parts.append(swap_code.rstrip("\r\n"))

    if options.plate_display in (PlateDisplay.M73, PlateDisplay.BOTH):
        # 用剩余时间的高位承载盘号；会牺牲时间显示准确性，默认关闭
        parts.append(f"M73 P0 R{options.m73_base * plate_index}")
    if options.plate_display in (PlateDisplay.M117, PlateDisplay.BOTH):
        parts.append(f"M117 Plate {plate_index}/{total_plates}")

    if options.wait_after_swap_s > 0:
        parts.append(f"G4 P{int(options.wait_after_swap_s * 1000)}")

    post_sound = render_audio(options.post_change_sound, newline=newline)
    if post_sound:
        parts.append(post_sound.rstrip("\r\n"))

    return newline.join(parts) + newline


def merge_segments(
    segments: Sequence[PlateSegment],
    *,
    options: MergeOptions,
    newline: str | None = None,
) -> MergeOutcome:
    """按顺序拼接多盘 G-code。

    :param segments: 按打印顺序排列的盘素材。
    :param options: 合盘配置。
    :param newline: 目标换行符；``None`` 时沿用第一个盘的换行风格。
    :raises ValidationError: 未提供任何盘。
    """
    if not segments:
        raise ValidationError("没有可拼接的盘")

    if newline is None:
        newline = detect_newline(segments[0].blocks.executable or segments[0].blocks.preamble)

    total = len(segments)
    chunks: list[str] = [_ensure_trailing_newline(segments[0].blocks.preamble, newline)]

    for position, segment in enumerate(segments):
        if position > 0:
            chunks.append(
                build_swap_block(
                    options,
                    plate_index=position + 1,
                    total_plates=total,
                    newline=newline,
                )
            )

        is_last = position == total - 1
        # 中间盘必须裁掉 EXECUTABLE 段尾部的结束序列（关加热 / 抬 Z / 结束音乐 / M18 断电），
        # 否则换盘码会在电机断电后执行
        body = segment.blocks.executable_body
        if is_last:
            # 只有最后一盘保留 END 标记：全文只能有一个 EXECUTABLE_BLOCK_END，
            # 否则后续任何按块解析（包括对合盘产物再次合盘）都会在第一个 END 处截断
            executable_text = f"{body}{segment.blocks.executable_end_marker}"
        else:
            executable_text = trim_executable_tail(body, options.start_end_policy)
        chunks.append(_ensure_trailing_newline(remap_gcode(executable_text, segment.mapping), newline))

        if not is_last:
            trimmed = trim_epilogue(segment.blocks.epilogue, options.start_end_policy)
            chunks.append(_ensure_trailing_newline(trimmed, newline))
        else:
            # 最后一盘保留完整 end 段，包含结束音乐与断电指令
            chunks.append(segment.blocks.epilogue)

    return MergeOutcome(
        text="".join(chunks),
        plate_count=total,
        swap_count=max(total - 1, 0),
    )


def _ensure_trailing_newline(text: str, newline: str) -> str:
    """确保片段以换行结尾，避免与后续片段粘连成一行。"""
    if not text:
        return ""
    if text.endswith(("\n", "\r")):
        return text
    return text + newline
