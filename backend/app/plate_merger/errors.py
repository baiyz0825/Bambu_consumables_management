"""合盘工具的异常体系。

设计原则：

1. 所有可预期失败都抛 :class:`PlateMergerError` 的子类，并携带稳定的 ``code``，
   便于日志检索与前端按错误码提示。
2. 绝不在内部 ``except`` 后静默返回半成品 —— 这是与旧「数据重组」App 最重要的差异：
   旧实现锚点找不到时会「追加到文件末尾」，产出的文件看似正常、实际只在末尾换一次盘。
3. 异常只描述「哪一步失败了」，不负责决定「要不要继续」；是否降级由调用方决定。
"""

from __future__ import annotations

from typing import Any


class PlateMergerError(Exception):
    """合盘流程所有异常的基类。

    :param message: 面向人的错误描述，省略时使用类级默认值。
    :param detail: 结构化上下文（如文件名、锚点、期望值），用于日志与排查。
    """

    code: str = "plate_merger_error"
    message: str = "合盘处理失败"

    def __init__(self, message: str | None = None, *, detail: dict[str, Any] | None = None) -> None:
        self.message = message or self.message
        self.detail: dict[str, Any] = detail or {}
        super().__init__(self.message)

    def __str__(self) -> str:
        if not self.detail:
            return self.message
        pairs = ", ".join(f"{key}={value}" for key, value in self.detail.items())
        return f"{self.message} ({pairs})"


class InvalidPackageError(PlateMergerError):
    """输入不是合法的 3MF（ZIP / OPC）包。"""

    code = "invalid_package"
    message = "输入文件不是合法的 3MF 包"


class UnsupportedFormatError(PlateMergerError):
    """输入不是 plate-sliced 格式，缺少内嵌 G-code。

    工程格式（Save Project）带完整 mesh，必须先经切片器导出为 plate-sliced。
    """

    code = "unsupported_format"
    message = "输入不是已切片 3MF（缺少 Metadata/plate_N.gcode）"


class MissingAnchorError(PlateMergerError):
    """G-code 结构锚点缺失，无法安全定位拼接或注入位置。"""

    code = "missing_anchor"
    message = "未找到必要的 G-code 结构锚点"


class MetadataError(PlateMergerError):
    """3MF 元数据（XML / JSON）缺失或格式非法。"""

    code = "metadata_error"
    message = "3MF 元数据解析失败"


class SwapCodeError(PlateMergerError):
    """换盘码参数非法或渲染失败。"""

    code = "swap_code_error"
    message = "换盘码参数或渲染失败"


class ValidationError(PlateMergerError):
    """合盘输出未通过结构校验。"""

    code = "validation_error"
    message = "合盘输出未通过校验"
