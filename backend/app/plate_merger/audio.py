"""换盘提示音渲染。

Bambu 用 ``M1006`` 驱动蜂鸣器：每条 ``M1006`` 写三个音符，``M1006 S1`` 开始、``M1006 W`` 结束播放。

设计说明：

- 使用**独立标记** ``;=====plate change sound=========``，不复用
  ``;=====printer finish  sound=========``，避免与原生结束音乐混淆
  （该标记同时被结构解析与去重逻辑使用）。
- 音频内容只含指令，标记由渲染器统一加，禁止把带标记的文本再次嵌入。
"""

from __future__ import annotations

from .errors import SwapCodeError
from .models import AudioMode

#: 换盘提示音的独立标记
PLATE_SOUND_FLAG = ";=====plate change sound========="

#: 短促提示音：三音上行，约 1 秒
_SHORT_NOTES = (
    "M1006 A0 B20 L100 C44 D10 M60 E44 F10 N60",
    "M1006 A0 B10 L100 C48 D10 M60 E48 F10 N60",
    "M1006 A0 B10 L100 C51 D20 M60 E51 F10 N60",
)

#: 结束风格提示音：四音，与原生结束音乐开头一致
_JINGLE_NOTES = (
    "M1006 A0 B20 L100 C37 D20 M40 E42 F20 N60",
    "M1006 A0 B10 L100 C44 D10 M60 E44 F10 N60",
    "M1006 A0 B10 L100 C46 D10 M80 E46 F10 N80",
    "M1006 A0 B20 L100 C0 D20 M60 E0 F20 N80",
)


def _normalize_custom_notes(notes: tuple[str, ...] | None) -> list[str]:
    """校验并规范化自定义乐谱行。

    只允许 ``M1006`` 开头的行：换盘段是裸 G-code 环境，任何其它指令都可能
    在换盘途中触发意外动作。
    """
    if not notes:
        raise SwapCodeError(
            "自定义提示音缺少乐谱内容",
            detail={"hint": "每行形如 M1006 A0 B20 L100 C44 D10 M60 E44 F10 N60"},
        )

    cleaned: list[str] = []
    for raw in notes:
        line = str(raw).strip()
        if not line:
            continue
        if not line.startswith("M1006"):
            raise SwapCodeError(
                "自定义提示音只能包含 M1006 乐谱指令",
                detail={"line": line},
            )
        cleaned.append(line)

    if not cleaned:
        raise SwapCodeError("自定义提示音缺少有效乐谱行")
    return cleaned


def render_audio(
    mode: AudioMode,
    *,
    notes: tuple[str, ...] | None = None,
    newline: str = "\n",
) -> str:
    """渲染提示音片段。

    :param mode: 提示音模式；``OFF`` 返回空串，``CUSTOM`` 使用 ``notes``。
    :param notes: 自定义乐谱行（每行 ``M1006`` 开头），``CUSTOM`` 模式必填。
    :param newline: 换行符。
    :raises SwapCodeError: ``CUSTOM`` 模式缺少乐谱，或含非 ``M1006`` 行。
    """
    if mode is AudioMode.OFF:
        return ""

    if mode is AudioMode.CUSTOM:
        body = _normalize_custom_notes(notes)
    else:
        body = list(_SHORT_NOTES if mode is AudioMode.SHORT else _JINGLE_NOTES)

    lines = [
        PLATE_SOUND_FLAG,
        "M17",        # 使能步进，蜂鸣器依赖电机供电
        "M400 S1",    # 等待运动与缓冲清空
        "M1006 S1",   # 开始写乐谱
        *body,
        "M1006 W",    # 结束并播放
        PLATE_SOUND_FLAG,
    ]
    return newline.join(lines) + newline
