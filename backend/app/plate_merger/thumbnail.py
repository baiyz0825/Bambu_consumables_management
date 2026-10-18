"""换盘测试文件的文字缩略图渲染（纯标准库）。

生成一张一眼可辨的 PNG：深色底 + "SWAP TEST" 标题 + 环形排布的
N 个圆点（每个点代表一次换盘）+ 环心大数字。

不依赖 PIL：手写 PNG 编码（zlib 压缩扫描行 + CRC 块），
文字用内置 5×7 点阵字体缩放绘制。算法层「零第三方依赖」原则不变。
"""

from __future__ import annotations

import binascii
import math
import struct
import zlib

#: 5×7 点阵字模（仅测试缩略图需要的字符）
_GLYPHS: dict[str, list[str]] = {
    " ": ["00000"] * 7,
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00110", "01000", "10000", "11111"],
    "3": ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    "6": ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00010", "01100"],
    "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    "W": ["10001", "10001", "10001", "10101", "10101", "10101", "01010"],
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "P": ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "X": ["10001", "10001", "01010", "00100", "01010", "10001", "10001"],
}

#: 缩略图配色（与系统深色主题一致）
_BG = (31, 35, 40)
_FG = (245, 246, 248)
_ACCENT = (0, 113, 227)
_MUTED = (140, 146, 156)


def _draw_text(buf: bytearray, size: int, text: str, x: int, y: int, scale: int, color: tuple[int, int, int]) -> None:
    """把点阵文字画进 RGB 缓冲（左上角对齐）。"""
    cx = x
    for ch in text.upper():
        glyph = _GLYPHS.get(ch, _GLYPHS[" "])
        for row, bits in enumerate(glyph):
            for col, bit in enumerate(bits):
                if bit != "1":
                    continue
                for dy in range(scale):
                    for dx in range(scale):
                        px, py = cx + col * scale + dx, y + row * scale + dy
                        if 0 <= px < size and 0 <= py < size:
                            i = (py * size + px) * 3
                            buf[i : i + 3] = bytes(color)
        cx += 6 * scale  # 5 列 + 1 列间距


def _text_width(text: str, scale: int) -> int:
    return len(text) * 6 * scale - scale


def _draw_disc(buf: bytearray, size: int, cx: int, cy: int, r: int, color: tuple[int, int, int]) -> None:
    """画实心圆。"""
    r2 = r * r
    for py in range(max(0, cy - r), min(size, cy + r + 1)):
        dy = py - cy
        half = int((r2 - dy * dy) ** 0.5)
        for px in range(max(0, cx - half), min(size, cx + half + 1)):
            i = (py * size + px) * 3
            buf[i : i + 3] = bytes(color)


def _png(width: int, height: int, rgb: bytes) -> bytes:
    """把 RGB 像素编码为 PNG（无辅助块）。"""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", binascii.crc32(tag + data) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + rgb[y * width * 3 : (y + 1) * width * 3] for y in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8bit RGB
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def render_swap_thumbnail(cycles: int, *, size: int = 512) -> bytes:
    """渲染换盘测试缩略图 PNG 字节。

    布局：上方 "SWAP TEST" 标题；中部 N 个圆点围成圆环（一点 = 一次换盘）；
    环心为换盘次数大数字；底部 "X8" 式角标。cycles 为换盘次数。
    """
    size = max(size, 128)
    buf = bytearray(bytes(_BG) * (size * size))
    center = size // 2

    # 标题
    title = "SWAP TEST"
    scale = max(2, size // 64)
    _draw_text(buf, size, title, center - _text_width(title, scale) // 2, int(size * 0.08), scale, _FG)

    # 环形 N 个点（一点 = 一次换盘）
    ring_r = int(size * 0.30)
    dot_r = max(4, int(ring_r * 0.13))
    for k in range(cycles):
        angle = -math.pi / 2 + k * 2 * math.pi / cycles
        dx = center + ring_r * math.cos(angle)
        dy = center + int(size * 0.03) + ring_r * math.sin(angle)
        _draw_disc(buf, size, int(dx), int(dy), dot_r, _ACCENT)

    # 环心大数字（换盘次数）
    label = str(cycles)
    num_scale = max(3, size // 14)
    _draw_text(
        buf,
        size,
        label,
        center - _text_width(label, num_scale) // 2,
        center + int(size * 0.03) - 3 * num_scale,
        num_scale,
        _FG,
    )

    # 底部角标
    foot = f"X{cycles}"
    foot_scale = max(2, size // 80)
    _draw_text(buf, size, foot, center - _text_width(foot, foot_scale) // 2, int(size * 0.88), foot_scale, _MUTED)

    return _png(size, size, bytes(buf))
