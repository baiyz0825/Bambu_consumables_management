"""换盘提示音渲染。

Bambu 用 ``M1006`` 驱动蜂鸣器：每条 ``M1006`` 写三个音符，``M1006 S1`` 开始、``M1006 W`` 结束播放。

设计说明：

- 使用**独立标记** ``;=====plate change sound=========``，不复用
  ``;=====printer finish  sound=========``，避免与原生结束音乐混淆
  （该标记同时被结构解析与去重逻辑使用）。
- 音频内容只含指令，标记由渲染器统一加，禁止把带标记的文本再次嵌入。
"""

from __future__ import annotations

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


def render_audio(mode: AudioMode, *, newline: str = "\n") -> str:
    """渲染提示音片段。

    :param mode: 提示音模式；``OFF`` 返回空串。
    :param newline: 换行符。
    """
    if mode is AudioMode.OFF:
        return ""

    notes = _SHORT_NOTES if mode is AudioMode.SHORT else _JINGLE_NOTES
    lines = [
        PLATE_SOUND_FLAG,
        "M17",        # 使能步进，蜂鸣器依赖电机供电
        "M400 S1",    # 等待运动与缓冲清空
        "M1006 S1",   # 开始写乐谱
        *notes,
        "M1006 W",    # 结束并播放
        PLATE_SOUND_FLAG,
    ]
    return newline.join(lines) + newline
