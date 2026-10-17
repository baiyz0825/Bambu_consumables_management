"""领域模型：合盘流程各阶段之间传递的不可变数据结构。

命名约定：

- ``*Info``    解析产出的只读事实（不允许调用方改写）
- ``*Options`` 调用方传入的配置（带默认值，显式优于隐式）
- ``*Result``  阶段产出
- ``*Warning`` 非致命问题：不阻断流程，但必须展示给用户

不可变性说明：值对象统一使用 ``frozen=True`` 与 ``tuple``，
避免流水线中某一步意外修改上游数据导致难以排查的串改。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class StartEndPolicy(str, Enum):
    """中间盘 start/end G-code 的剥离强度。

    - ``FULL``  全保留：最稳，但每盘都重新加热、调平、退料，最慢。
    - ``SLIM``  剥离降温/调平/归位，**保留退料**：默认档，避免喷嘴带料换盘。
    - ``TURBO`` 完全精简：最快，需实机验证首层质量。
    """

    FULL = "full"
    SLIM = "slim"
    TURBO = "turbo"


class ApproachMode(str, Enum):
    """换盘时把热床推到后限位的方式。

    - ``FORCE`` 使用 ``G380`` 力控，遇到阻力提前停止（安全，慢）。
    - ``OPEN``  使用 ``G1`` 开环移动，固定坐标（快，依赖机械一致性）。
    """

    FORCE = "force"
    OPEN = "open"


@dataclass(frozen=True)
class FilamentRef:
    """一条耗材引用，对应切片时的一个挤出机槽位。

    ``slot`` 为 0-based，与 G-code 中 ``M620 S{slot}A`` 的编号一致。
    """

    slot: int
    tray_info_idx: str = ""
    type: str = ""
    color: str = "#000000"
    used_g: float | None = None
    used_m: float | None = None

    @property
    def identity(self) -> tuple[str, str, str]:
        """跨盘去重键：预设 ID + 类型 + 颜色（大小写不敏感）。

        必须用三者联合，而不是只比槽位号 —— 实测同一 ``S0`` 在不同盘
        可能对应不同颜色（见技术方案 §4.2）。
        """
        return (self.tray_info_idx.upper(), self.type.upper(), self.color.upper())


@dataclass(frozen=True)
class PlateInfo:
    """单个盘的切片元信息（只读事实）。"""

    index: int
    gcode_member: str
    prediction_s: int | None = None
    weight_g: float | None = None
    filaments: tuple[FilamentRef, ...] = ()
    client_version: str | None = None
    bed_type: str | None = None

    @property
    def slot_count(self) -> int:
        """本盘占用的槽位数。"""
        return len(self.filaments)


@dataclass(frozen=True)
class InputPlate:
    """一个输入 3MF 及其选中的盘。"""

    source: Path
    plate: PlateInfo

    @property
    def display_name(self) -> str:
        """用于日志与报表的短名称。"""
        return f"{self.source.name}#plate_{self.plate.index}"


@dataclass(frozen=True)
class SwapParams:
    """换盘码渲染参数。默认值即「保守档」，取自 ``0623 code.gcode``。"""

    preset_id: str = "builtin:a1-conservative"
    name: str = "A1 第二代套件 · 保守档"
    machine: str = "A1"

    #: Y 轴行程上限；A1 为 264，A1 mini 为 180
    y_limit: float = 264.0
    #: 推到后限位的方式
    approach_mode: ApproachMode = ApproachMode.FORCE
    #: 开环推盘速度（仅 OPEN 模式使用）
    approach_feedrate: int = 3000
    #: 推盘前是否先 ``G28 Y`` 归零
    home_y_before: bool = True

    #: 抖动脱盘的正向越位序列（毫米），由轻到重
    shake_offsets: tuple[float, ...] = (1.0, 1.5, 2.0, 2.5, 3.0, 3.5)
    #: 抖动时的低速进给
    shake_feedrate: int = 100
    #: 回位的高速进给序列，与 ``shake_offsets`` 一一对应
    retract_feedrates: tuple[int, ...] = (20000, 10000, 5000)

    #: 力控档位：推盘用 S2，探测用 S3
    force_level_push: str = "S2"
    force_level_probe: str = "S3"

    #: Z 轴相对移动序列（毫米），净位移决定热床最终高度
    z_moves: tuple[float, ...] = (-25.0, 85.0, -5.0, -55.0)
    #: 停留时间序列（毫秒），不足时循环复用最后一个值
    dwell_ms: tuple[int, ...] = (500, 1000, 2000)

    #: 卸盘越位量（毫米）。硬约束：必须 <= -1，否则无法触发前端退盘机构。
    eject_offset: float = -2.0


@dataclass(frozen=True)
class MergeOptions:
    """合盘调用配置。"""

    swap_params: SwapParams = field(default_factory=SwapParams)
    #: 中间盘 start/end 处理策略
    start_end_policy: StartEndPolicy = StartEndPolicy.SLIM
    #: 是否把 md5 转为大写（Bambu 原生为大写）
    md5_upper: bool = True
    #: 是否按 OPC 规范打包（Content_Types 首位且 STORED）
    opc_pack: bool = True
    #: 换盘码前是否插入热床降温（None 表示不降温）
    hotbed_cooldown_c: int | None = None
    #: 换盘完成后等待秒数（0 表示不等待）
    wait_after_swap_s: int = 0
    #: 换盘码起止标记（用于去重与结构校验）
    swap_start_flag: str = ";start change plate"
    swap_end_flag: str = ";end change plate"
    #: 输出文件名，None 时由流水线生成
    output_name: str | None = None


@dataclass(frozen=True)
class MergeWarning:
    """非致命问题：流程继续，但必须在结果中呈现。"""

    code: str
    message: str
    plate_index: int | None = None


@dataclass(frozen=True)
class MergeResult:
    """合盘最终产出。"""

    output_path: Path
    plate_count: int
    gcode_bytes: int
    total_time_s: int | None = None
    total_weight_g: float | None = None
    md5: str = ""
    warnings: tuple[MergeWarning, ...] = ()
