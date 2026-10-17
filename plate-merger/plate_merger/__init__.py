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
from .gcode import (
    GcodeBlocks,
    count_occurrences,
    detect_newline,
    extract_header_block,
    find_all,
    locate_anchor,
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
from .presets import BALANCED, BUILTIN_PRESETS, CONSERVATIVE, FAST, get_preset, list_presets
from .sliceinfo import (
    PlateJson,
    SliceHeader,
    SliceInfo,
    SlicePlate,
    parse_filament_sequence,
    parse_plate_json,
    parse_project_settings,
    parse_slice_info,
)
from .swapcode import estimate_duration_s, render_swap_code, validate_params
from .utils import normalize_color, to_float, to_int

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
    # G-code 解析
    "GcodeBlocks",
    "count_occurrences",
    "detect_newline",
    "extract_header_block",
    "find_all",
    "locate_anchor",
    # 元数据解析
    "SliceHeader",
    "SlicePlate",
    "SliceInfo",
    "PlateJson",
    "parse_slice_info",
    "parse_plate_json",
    "parse_filament_sequence",
    "parse_project_settings",
    # 换盘码
    "SwapParams",
    "ApproachMode",
    "CONSERVATIVE",
    "BALANCED",
    "FAST",
    "BUILTIN_PRESETS",
    "get_preset",
    "list_presets",
    "render_swap_code",
    "validate_params",
    "estimate_duration_s",
    # 工具
    "normalize_color",
    "to_int",
    "to_float",
    # 领域模型
    "StartEndPolicy",
    "FilamentRef",
    "PlateInfo",
    "InputPlate",
    "MergeOptions",
    "MergeWarning",
    "MergeResult",
]
