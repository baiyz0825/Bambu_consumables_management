"""plate-merger：拓竹 A1 自动换盘的多盘 3MF 合盘工具。

对外稳定 API 统一在此导出；子模块之间的互相引用属实现细节，
调用方应优先使用本模块导出的名字，以便后续内部重构不破坏契约。
"""

from __future__ import annotations

from .audio import PLATE_SOUND_FLAG, render_audio
from .dispatch import (
    DispatchResult,
    PrinterTarget,
    build_project_file_command,
    dispatch,
    package_md5,
    upload_package,
)
from .errors import (
    InvalidPackageError,
    MetadataError,
    MissingAnchorError,
    PlateMergerError,
    SwapCodeError,
    UnsupportedFormatError,
    ValidationError,
)
from .filament import FilamentPlan, GlobalFilament, PlateMapping, build_plan, remap_gcode
from .fingerprint import Fingerprint, diff as fingerprint_diff, probe
from .gcode import (
    GcodeBlocks,
    check_relative_mode_balance,
    count_occurrences,
    detect_newline,
    extract_header_block,
    find_all,
    locate_anchor,
)
from .io3mf import CONTENT_TYPES, ThreeMfPackage, compute_md5, write_3mf
from .merger import MergeOutcome, PlateSegment, build_swap_block, merge_segments
from .metadata import (
    MERGED_GCODE_MEMBER,
    rewrite_filament_sequence,
    rewrite_model_settings,
    rewrite_plate_json,
    rewrite_project_settings,
    rewrite_slice_info,
    strip_extra_plate_assets,
)
from .models import (
    ApproachMode,
    AudioMode,
    FilamentRef,
    InputPlate,
    MergeOptions,
    MergeResult,
    MergeWarning,
    PlateDisplay,
    PlateInfo,
    StartEndPolicy,
    SwapParams,
)
from .pipeline import MergeRequest, merge
from .planner import PlanResult, PlateJob, PlannedPlate, plan as plan_plates
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
from .splitter import contains_swap_code, trim_epilogue, trim_executable_tail
from .swapcode import estimate_duration_s, render_swap_code, validate_params
from .toolfile import build_tool_file, neutralize_heating
from .utils import normalize_color, to_bool, to_float, to_int
from .verifier import CheckResult, VerificationReport, verify_package

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
    # G-code
    "GcodeBlocks",
    "check_relative_mode_balance",
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
    # 耗材
    "FilamentRef",
    "FilamentPlan",
    "GlobalFilament",
    "PlateMapping",
    "build_plan",
    "remap_gcode",
    # 裁剪与拼接
    "StartEndPolicy",
    "contains_swap_code",
    "trim_epilogue",
    "trim_executable_tail",
    "PlateSegment",
    "MergeOutcome",
    "build_swap_block",
    "merge_segments",
    # 元数据重写
    "MERGED_GCODE_MEMBER",
    "rewrite_slice_info",
    "rewrite_model_settings",
    "rewrite_filament_sequence",
    "rewrite_plate_json",
    "rewrite_project_settings",
    "strip_extra_plate_assets",
    # 校验
    "CheckResult",
    "VerificationReport",
    "verify_package",
    # 流水线
    "MergeRequest",
    "MergeOptions",
    "MergeResult",
    "MergeWarning",
    "merge",
    # 展示与音频
    "PlateDisplay",
    "AudioMode",
    "PLATE_SOUND_FLAG",
    "render_audio",
    # 指纹与排产
    "Fingerprint",
    "probe",
    "fingerprint_diff",
    "PlateJob",
    "PlannedPlate",
    "PlanResult",
    "plan_plates",
    # 测试文件
    "build_tool_file",
    "neutralize_heating",
    # 下发
    "PrinterTarget",
    "DispatchResult",
    "build_project_file_command",
    "package_md5",
    "upload_package",
    "dispatch",
    # 工具
    "normalize_color",
    "to_int",
    "to_float",
    "to_bool",
    "PlateInfo",
    "InputPlate",
]
