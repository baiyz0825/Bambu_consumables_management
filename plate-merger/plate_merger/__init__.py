"""plate-merger：拓竹 A1 自动换盘的多盘 3MF 合盘工具。

对外稳定 API 统一在此导出；子模块之间的互相引用属实现细节，
调用方应优先使用本模块导出的名字，以便后续内部重构不破坏契约。
"""

from __future__ import annotations

from .errors import (
    InvalidPackageError,
    MetadataError,
    MissingAnchorError,
    PlateMergerError,
    SwapCodeError,
    UnsupportedFormatError,
    ValidationError,
)
from .io3mf import CONTENT_TYPES, ThreeMfPackage, compute_md5, write_3mf
from .models import (
    ApproachMode,
    FilamentRef,
    InputPlate,
    MergeOptions,
    MergeResult,
    MergeWarning,
    PlateInfo,
    StartEndPolicy,
    SwapParams,
)

__version__ = "0.1.0"

__all__ = [
    # 异常
    "PlateMergerError",
    "InvalidPackageError",
    "UnsupportedFormatError",
    "MissingAnchorError",
    "MetadataError",
    "SwapCodeError",
    "ValidationError",
    # 3MF 读写
    "CONTENT_TYPES",
    "ThreeMfPackage",
    "compute_md5",
    "write_3mf",
    # 领域模型
    "ApproachMode",
    "StartEndPolicy",
    "FilamentRef",
    "PlateInfo",
    "InputPlate",
    "SwapParams",
    "MergeOptions",
    "MergeWarning",
    "MergeResult",
]
