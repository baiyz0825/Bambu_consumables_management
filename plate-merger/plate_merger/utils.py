"""通用值转换工具。

3MF 元数据中的数字与颜色大多以字符串形式存储，且不同固件/版本写法不一致
（例如 ``"8E9089FF"``、``"#8E9089"``、``"3"``、``"3.0"``）。
本模块集中处理这些边界情况，供解析层与换盘码层复用。
"""

from __future__ import annotations

from typing import Any

_HEX_DIGITS = set("0123456789ABCDEF")


def to_int(value: Any) -> int | None:
    """尽量把值转为整数。

    支持 ``int`` / 纯数字 ``str`` / 可无损转整数的浮点；其余返回 ``None``，
    不抛异常 —— 元数据缺字段属常态，由调用方决定默认值。
    """
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            try:
                number = float(text)
            except ValueError:
                return None
            return int(number) if number.is_integer() else None
    return None


def to_float(value: Any) -> float | None:
    """尽量把值转为浮点数；无法转换或为 NaN 时返回 ``None``。"""
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        number = float(value)
        return None if number != number else number  # NaN 自比较恒为假
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
        return None if number != number else number
    return None


def normalize_color(value: Any) -> str:
    """把各种颜色写法统一为 ``#RRGGBB``。

    兼容：

    - ``"F6DA5A"``        六位十六进制
    - ``"#F6DA5A"``       带井号
    - ``"F6DA5AFF"``      Bambu 常见 ``RRGGBBAA``（取前六位）
    - 无法识别时返回 ``"#000000"``，保证下游不必判空
    """
    if not isinstance(value, str):
        return "#000000"
    text = value.strip()
    if not text:
        return "#000000"
    raw = text[1:] if text.startswith("#") else text
    hex_part = raw.upper()
    if not hex_part or any(char not in _HEX_DIGITS for char in hex_part):
        return "#000000"
    if len(hex_part) == 8:
        # Bambu 的 tray_color 形如 RRGGBBAA，alpha 在末位
        return f"#{hex_part[:6]}"
    if len(hex_part) == 6:
        return f"#{hex_part}"
    return "#000000"
