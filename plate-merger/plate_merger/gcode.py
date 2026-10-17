"""G-code 三段块解析。

Bambu Studio 导出的 plate-sliced G-code 固定包含三段：

.. code-block:: text

    ; HEADER_BLOCK_START ... ; HEADER_BLOCK_END      时间 / 重量 / 层高
    ; CONFIG_BLOCK_START ...                         工艺参数（以注释形式内嵌）
    ; EXECUTABLE_BLOCK_START ... ; EXECUTABLE_BLOCK_END   实际打印动作

合盘只在 EXECUTABLE 段做拼接与注入，因此必须先可靠定位三段边界。

设计要点：

1. **不做行重组**：全部用字符串切片，原样保留换行符（CRLF / LF），
   避免 G-code 行尾被无意改写。
2. **锚点缺失即报错**：不提供「追加到末尾」的兜底（旧 App 因此产出过坏文件）。
3. 本模块只负责定位与切分，不解释任何指令语义。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import MissingAnchorError

#: EXECUTABLE 段起始行（Bambu 写作 ``; EXECUTABLE_BLOCK_START``）
_EXECUTABLE_START_RE = re.compile(r"^;[ \t]*EXECUTABLE_BLOCK_START[^\n]*$", re.MULTILINE)
#: EXECUTABLE 段结束行
_EXECUTABLE_END_RE = re.compile(r"^;[ \t]*EXECUTABLE_BLOCK_END[^\n]*$", re.MULTILINE)
#: HEADER 段（元信息，仅用于读取，不参与拼接）
_HEADER_START_RE = re.compile(r"^;[ \t]*HEADER_BLOCK_START[^\n]*$", re.MULTILINE)
_HEADER_END_RE = re.compile(r"^;[ \t]*HEADER_BLOCK_END[^\n]*$", re.MULTILINE)


def _line_end(text: str, position: int) -> int:
    """返回 ``position`` 所在行的行尾（含换行符）偏移。

    找不到换行时返回字符串长度，保证返回值始终可直接用于切片。
    """
    newline = text.find("\n", position)
    return len(text) if newline < 0 else newline + 1


def detect_newline(text: str) -> str:
    """探测文本使用的换行符。

    3MF 内的 G-code 通常为 ``\\n``，但不同平台导出可能为 ``\\r\\n``。
    合盘时必须全线统一，否则拼接处会出现孤立 ``\\r``。
    """
    return "\r\n" if "\r\n" in text else "\n"


def find_all(text: str, needle: str) -> list[int]:
    """返回 ``needle`` 在文本中出现的全部起始偏移。"""
    if not needle:
        return []
    positions: list[int] = []
    start = 0
    while True:
        index = text.find(needle, start)
        if index < 0:
            return positions
        positions.append(index)
        start = index + len(needle)


def count_occurrences(text: str, needle: str) -> int:
    """统计 ``needle`` 出现次数。"""
    return len(find_all(text, needle))


def locate_anchor(
    text: str,
    needle: str,
    *,
    search_from: int = 0,
    search_to: int | None = None,
    occurrence: int = -1,
    required: bool = True,
) -> int:
    """定位锚点并返回起始偏移。

    :param needle: 锚点文本（如 ``";=====printer finish  sound========="``）。
    :param search_from: 搜索起点，用于把搜索限制在某个块内。
    :param search_to: 搜索终点（不含），``None`` 表示到文本末尾。
    :param occurrence: 取第几次出现；``-1`` 表示最后一次，``0`` 表示第一次。
    :param required: 未命中时是否抛异常。
    :return: 命中偏移；未命中且 ``required=False`` 时返回 ``-1``。
    :raises MissingAnchorError: 未命中且 ``required=True``。
    """
    end = len(text) if search_to is None else search_to
    positions = [pos for pos in find_all(text, needle) if search_from <= pos < end]
    if not positions:
        if required:
            raise MissingAnchorError("未找到锚点", detail={"anchor": needle, "occurrences": 0})
        return -1
    try:
        return positions[occurrence]
    except IndexError as exc:
        raise MissingAnchorError(
            "锚点出现次数不足",
            detail={"anchor": needle, "occurrences": len(positions), "wanted": occurrence},
        ) from exc


@dataclass(frozen=True)
class GcodeBlocks:
    """一份 G-code 的三段结构。

    - ``preamble``：文件开头到 ``EXECUTABLE_BLOCK_START`` 行尾（含该行）
    - ``executable``：``EXECUTABLE_BLOCK_START`` 之后到 ``EXECUTABLE_BLOCK_END`` 行尾（含）
    - ``epilogue``：``EXECUTABLE_BLOCK_END`` 之后
    """

    preamble: str
    executable: str
    epilogue: str

    @classmethod
    def parse(cls, text: str) -> "GcodeBlocks":
        """按块标记切分文本。

        :raises MissingAnchorError: 缺少 EXECUTABLE 段起止标记。
        """
        start_match = _EXECUTABLE_START_RE.search(text)
        if start_match is None:
            raise MissingAnchorError("缺少 EXECUTABLE_BLOCK_START", detail={"anchor": "EXECUTABLE_BLOCK_START"})

        end_match = _EXECUTABLE_END_RE.search(text, pos=start_match.end())
        if end_match is None:
            raise MissingAnchorError("缺少 EXECUTABLE_BLOCK_END", detail={"anchor": "EXECUTABLE_BLOCK_END"})

        preamble = text[: _line_end(text, start_match.start())]
        executable = text[len(preamble) : _line_end(text, end_match.start())]
        epilogue = text[len(preamble) + len(executable) :]
        return cls(preamble=preamble, executable=executable, epilogue=epilogue)

    def render(self) -> str:
        """按原顺序拼回完整文本。"""
        return f"{self.preamble}{self.executable}{self.epilogue}"

    @property
    def preamble_line_count(self) -> int:
        """preamble 的行数。

        用于把 EXECUTABLE 段内的偏移换算成整份文件的行号（便于日志定位）。
        """
        return self.preamble.count("\n")

    @property
    def executable_body(self) -> str:
        """去掉末尾 END 标记行后的纯打印动作正文。

        注意：``executable`` 段**不包含** START 标记行（它已归入 ``preamble``），
        只包含末尾的 END 标记行，因此这里只需裁掉最后一行。
        """
        lines = self.executable.splitlines(keepends=True)
        if not lines:
            return ""
        return "".join(lines[:-1])


def extract_header_block(text: str) -> str | None:
    """提取 HEADER 块文本（含起止标记行）；不存在时返回 ``None``。

    HEADER 含 ``total filament weight``、``layer height`` 等摘要，
    主要用于展示与交叉校验，不参与合盘拼接。
    """
    start_match = _HEADER_START_RE.search(text)
    if start_match is None:
        return None
    end_match = _HEADER_END_RE.search(text, pos=start_match.end())
    if end_match is None:
        return None
    return text[start_match.start() : _line_end(text, end_match.start())]
