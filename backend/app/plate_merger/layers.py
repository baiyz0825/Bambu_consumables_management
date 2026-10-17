"""G-code 层索引：从切片产物反推每一层的 Z 高度与 XY 范围。

为什么要它
----------
拓竹的 MQTT ``print`` 消息只上报 ``layer_num``（当前层号），**不回传实时 XYZ**。
数字孪生要让喷嘴动起来，唯一可行的反推路径是：

.. code-block:: text

    layer_num ──► LayerIndex.layer(n) ──► (z_mm, XY bbox) ──► locate(n, fraction)

因此本模块把 G-code 压缩成「层号 → Z / bbox」的查表结构，而不是重建几何。
三条底线：

1. **层号必须与打印机对齐**：1-based，从 ``;LAYER_CHANGE`` 计数，
   空层（只有 Z 没有走线）也保留，否则越往后层号偏得越多；
2. **Z 优先信任切片器注释**（``;Z:``），其次 Z 变化，最后继承上一层；
3. **XY 只到包围盒**：逐条轨迹比 bbox 多不出信息价值，却会让缓存体积翻上百倍。

已知近似与限制
--------------
- :meth:`LayerIndex.locate` 的 XY 是**沿 bbox 对角线插值**的近似值：
  ``fraction=0`` 落在 ``(x_min, y_min)``，``fraction=1`` 落在 ``(x_max, y_max)``。
  真实喷嘴路径（逐条走线）**不在本结构中**，孪生动画只能做到「层内线性扫过」。
- 圆弧 ``G2``/``G3`` 只用端点近似，不展开圆心/半径，弧顶可能略微越界。
- 没采到 XY 的层 bbox 退化为 0，``LayerSlice.has_xy`` 为 ``False``；
  这类层不参与 :meth:`LayerIndex.bbox`，:meth:`LayerIndex.locate` 则返回床原点。
- 坐标必须以空白分隔（``G1 X10 Y10``）。Bambu / Orca / PrusaSlicer 均如此；
  紧凑写法 ``G1X10Y10`` 不支持，会被当作无坐标行跳过。
- 降级切层（无 ``;LAYER_CHANGE``）时，相对模式下的 z-hop 会被误判为新层，
  详见 :meth:`LayerIndex.build`。

性能与容错
----------
单次顺序扫描：无逐行正则、无中间对象；1M 行 G-code 约 1~2 秒。
非法数值与残缺行一律跳过而不抛异常 —— 层索引是旁路数据，
宁可少一层 bbox，也不能让孪生整体失败。
"""

from __future__ import annotations

import io
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .utils import to_float

#: 切层策略：按 ``;LAYER_CHANGE`` 注释切层（Bambu / Orca / PrusaSlicer 产物）
MODE_LAYER_CHANGE = "layer_change"
#: 切层策略：无注释可用，降级为「Z 增大即新层」
MODE_Z = "z"
#: 没有任何可解析内容的空索引
MODE_EMPTY = "empty"

#: 层变更注释的关键字（不含前导分号，便于大小写宽容匹配）
_LAYER_MARKER = "LAYER_CHANGE"
#: 探测文件是否采用注释切层；大小写各查一次，两个 C 级扫描，代价可忽略
_MARKER_TOKENS = (";LAYER_CHANGE", ";layer_change")
#: 层 Z 注释前缀，如 ``;Z:0.20``
_Z_PREFIX = "Z:"
#: 「Z 增大」的判定容差（mm）：小于该变化视为同层，滤掉浮点噪声
_Z_EPS = 1e-4
#: 直线移动指令：既更新 bbox 也累加 ``moves``
_MOVE_CODES = frozenset({"G0", "G1"})
#: 圆弧指令：只按端点近似 bbox，不计入 ``moves``
_ARC_CODES = frozenset({"G2", "G3"})
#: 超过该字节数改用流式迭代，避免 ``splitlines`` 一次性生成上百万个 str
_STREAM_THRESHOLD = 4 << 20
#: 坐标写入缓存时保留的小数位（体积与精度的折中）
_PRECISION = 4
#: 缓存格式版本，便于日后迁移
_FORMAT_VERSION = 1
#: 每层在缓存中的字段顺序
_ROW_FIELDS = ("z_mm", "x_min", "x_max", "y_min", "y_max", "moves")


@dataclass(frozen=True)
class LayerSlice:
    """单层摘要（只读值对象）。

    :param layer: 1-based 层号，与打印机上报的 ``layer_num`` 同源
    :param z_mm: 该层 Z 高度（喷嘴在层内打印时的 Z）
    :param x_min: XY 包围盒 X 下界
    :param x_max: XY 包围盒 X 上界
    :param y_min: XY 包围盒 Y 下界
    :param y_max: XY 包围盒 Y 上界
    :param moves: 该层直线移动（``G0``/``G1``）条数，用于判断层内是否真有走线；
        圆弧 ``G2``/``G3`` 只更新 bbox，不计数

    未采到任何 XY 信息时，bbox 四个字段保持 ``0.0`` 且 ``moves == 0``，
    由 :attr:`has_xy` 判定 —— 用 ``0`` 而不是 ``None`` 是为了
    :meth:`LayerIndex.to_dict` 能存成等宽的纯数字，直接进 JSON / DB。
    """

    layer: int
    z_mm: float
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    moves: int

    @property
    def has_xy(self) -> bool:
        """该层是否采到了 XY 信息。

        判定标准不是「bbox 非零」（首层可能就贴着原点），而是
        「有过 XY 移动」或「bbox 非退化」二者之一。
        """
        if self.moves:
            return True
        return not (
            self.x_min == 0.0
            and self.x_max == 0.0
            and self.y_min == 0.0
            and self.y_max == 0.0
        )


@dataclass
class LayerIndex:
    """一份 G-code 的层索引。

    :param layers: 按层号升序排列的层摘要（``layers[n-1].layer == n``）
    :param mode: 实际生效的切层策略，取值见 ``MODE_*`` 常量
    """

    layers: list[LayerSlice] = field(default_factory=list)
    mode: str = MODE_EMPTY

    # ------------------------------------------------------------------ 构建
    @classmethod
    def build(cls, gcode: str) -> "LayerIndex":
        """从 G-code 文本构建层索引。**任何输入都不抛异常**。

        切层策略按优先级自动选择：

        1. 文本中出现 ``;LAYER_CHANGE`` → 每个该注释开启新一层。
           注释之后若还有 ``;Z:<值>``，用它的值作为该层 Z（压过从 ``G1`` 推断的 Z）。
           **首个注释之前的内容（start code、擦嘴、拉屎线）整体丢弃**，
           否则擦嘴线会把首层 bbox 撑到热床边缘。
        2. 完全没有注释 → 降级为「``G0``/``G1`` 的 Z 增大即新层」，
           每次触发时的目标 Z 即该层 Z。该降级路径较脆（见「已知近似」），
           仅用于兜底非 Bambu 产物。

        :param gcode: 完整 G-code 文本，``\\n`` / ``\\r\\n`` 均可
        :return: 层索引；无可解析内容时返回空索引（``len == 0``）
        """
        if not isinstance(gcode, str) or not gcode:
            return cls(layers=[], mode=MODE_EMPTY)

        if any(token in gcode for token in _MARKER_TOKENS):
            drafts = _parse(gcode, split_by_marker=True)
            mode = MODE_LAYER_CHANGE
            if not drafts:
                # 关键字只出现在文件头注释里（例如切片器把关键字写进了元信息）
                drafts = _parse(gcode, split_by_marker=False)
                mode = MODE_Z
        else:
            drafts = _parse(gcode, split_by_marker=False)
            mode = MODE_Z

        layers = _freeze(drafts)
        return cls(layers=layers, mode=mode if layers else MODE_EMPTY)

    # ------------------------------------------------------------------ 查询
    @property
    def len(self) -> int:
        """层数。"""
        return len(self.layers)

    def __len__(self) -> int:
        return len(self.layers)

    def layer(self, n: int) -> LayerSlice | None:
        """取第 ``n`` 层（1-based）。

        :return: 层摘要；越界或下标非法时返回 ``None``，**不抛异常**
            （MQTT 层号偶尔会超出切片层数，属正常抖动）。
        """
        if not isinstance(n, int) or isinstance(n, bool):
            return None
        if 1 <= n <= len(self.layers):
            return self.layers[n - 1]
        return None

    def bbox(self) -> tuple[float, float, float, float] | None:
        """全模型 XY 包围盒 ``(x_min, x_max, y_min, y_max)``。

        只统计采到 XY 的层（``has_xy``），因此 start code 里的大范围移动
        不会污染结果。无有效层时返回 ``None``。
        """
        x_min: float | None = None
        x_max: float | None = None
        y_min: float | None = None
        y_max: float | None = None
        for item in self.layers:
            if not item.has_xy:
                continue
            if x_min is None or item.x_min < x_min:
                x_min = item.x_min
            if x_max is None or item.x_max > x_max:
                x_max = item.x_max
            if y_min is None or item.y_min < y_min:
                y_min = item.y_min
            if y_max is None or item.y_max > y_max:
                y_max = item.y_max
        if x_min is None or x_max is None or y_min is None or y_max is None:
            return None
        return (x_min, x_max, y_min, y_max)

    def locate(self, layer_num: int, fraction: float = 0.0) -> tuple[float, float, float] | None:
        """估算指定层的喷嘴位置 ``(x, y, z)``，供孪生动画使用。

        ``z`` 直接取该层 ``z_mm``；XY 沿该层 bbox 的**对角线**插值：
        ``fraction`` 从 ``0``（``(x_min, y_min)``）线性走到 ``1``（``(x_max, y_max)``）。
        越界的 ``fraction`` 会被夹到 ``[0, 1]``，非法值按 ``0`` 处理。

        .. warning::
           这是**近似**：层内真实走线并不在索引里，
           喷嘴看起来会沿对角线匀速扫过，而不是逐条打印。

        :param layer_num: 1-based 层号
        :param fraction: 层内进度，0~1
        :return: ``(x, y, z)``；层号越界返回 ``None``。
            无 XY 数据的层返回 ``(0.0, 0.0, z)``（床原点）。
        """
        current = self.layer(layer_num)
        if current is None:
            return None
        ratio = to_float(fraction)
        ratio = 0.0 if ratio is None else min(max(ratio, 0.0), 1.0)
        x = current.x_min + (current.x_max - current.x_min) * ratio
        y = current.y_min + (current.y_max - current.y_min) * ratio
        return (x, y, current.z_mm)

    # ------------------------------------------------------------------ 序列化
    def to_dict(self) -> dict[str, Any]:
        """转成可 JSON 序列化的紧凑字典（用于写入磁盘 / DB 缓存）。

        每层只存 6 个数字 ``[z, x_min, x_max, y_min, y_max, moves]``，
        层号由列表下标隐含（1-based），坐标保留 4 位小数：
        1 万层约 0.5 MB、10 万层约 5 MB，按需缓存不会撑爆存储。
        """
        return {
            "version": _FORMAT_VERSION,
            "mode": self.mode,
            "layers": [
                [
                    round(item.z_mm, _PRECISION),
                    round(item.x_min, _PRECISION),
                    round(item.x_max, _PRECISION),
                    round(item.y_min, _PRECISION),
                    round(item.y_max, _PRECISION),
                    item.moves,
                ]
                for item in self.layers
            ],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "LayerIndex":
        """从 :meth:`to_dict` 的产物还原。

        容错约定：缺字段补 ``0``、坏行降级为全零层、整体非法则返回空索引。
        **坏行不丢弃**——层号由行序决定，丢一行会让后续所有层的
        ``layer_num`` 错位，比一个全零层危险得多。
        """
        if not isinstance(data, Mapping):
            return cls(layers=[], mode=MODE_EMPTY)

        mode = data.get("mode")
        mode = mode if isinstance(mode, str) and mode else MODE_EMPTY
        rows = data.get("layers")
        if not isinstance(rows, list):
            return cls(layers=[], mode=MODE_EMPTY)

        layers = [_slice_from_row(row, number) for number, row in enumerate(rows, start=1)]
        return cls(layers=layers, mode=mode if layers else MODE_EMPTY)


# ---------------------------------------------------------------------- 内部实现


@dataclass(slots=True)
class _LayerDraft:
    """单层的可变累加器（只在解析过程中存在，避免反复重建 frozen 对象）。"""

    #: ``;Z:`` 注释给出的 Z，优先级最高
    z_explicit: float | None = None
    #: 层内出现过的最小 Z，用于 z-hop 场景下反推层高
    z_min: float | None = None
    x_min: float | None = None
    x_max: float | None = None
    y_min: float | None = None
    y_max: float | None = None
    moves: int = 0


def _iter_lines(gcode: str) -> Iterable[str]:
    """逐行迭代 G-code。

    大文件走 ``StringIO``（常量内存，避免一次性构造百万个 str），
    小文件走 ``splitlines``（纯 C 路径，更快）。两者都不处理裸 ``\\r``。
    """
    if len(gcode) > _STREAM_THRESHOLD:
        return io.StringIO(gcode)
    return gcode.splitlines()


def _parse(gcode: str, *, split_by_marker: bool) -> list[_LayerDraft]:
    """顺序扫描 G-code，产出每层的累加器。

    :param split_by_marker: ``True`` 只在 ``;LAYER_CHANGE`` 处切层；
        ``False`` 降级为「Z 增大即新层」。
    """
    drafts: list[_LayerDraft] = []
    current: _LayerDraft | None = None
    #: 出现在首个切层注释之前的 ``;Z:``，留给下一层
    pending_z: float | None = None
    #: Z 模式下当前层的基准 Z
    layer_z: float | None = None
    absolute = True
    pos_x: float | None = None
    pos_y: float | None = None
    pos_z: float | None = None

    for raw in _iter_lines(gcode):
        line = raw.strip()
        if not line:
            continue

        # ------------------------------------------------------------ 注释行
        if line[0] == ";":
            body = line[1:].strip()
            if not body:
                continue
            head = body[:12].upper()
            if head.startswith(_LAYER_MARKER):
                if split_by_marker:
                    current = _LayerDraft(z_explicit=pending_z)
                    pending_z = None
                    drafts.append(current)
                continue
            if head.startswith(_Z_PREFIX):
                value = to_float(body[len(_Z_PREFIX) :])
                if value is None:
                    continue
                if current is None:
                    pending_z = value
                else:
                    current.z_explicit = value
            continue

        # ------------------------------------------------------------ 指令行
        # T / M 及其它指令与本模块无关，先按首字母快速排除
        if line[0] not in "Gg":
            continue
        tokens = line.split()
        command = tokens[0].upper()
        if command == "G90":
            absolute = True
            continue
        if command == "G91":
            absolute = False
            continue
        if command != "G92" and command not in _MOVE_CODES and command not in _ARC_CODES:
            continue

        # 逐 token 取 X/Y/Z。Bambu/Orca 的坐标一律空白分隔，
        # 逐 token 比逐行正则快一个量级；非数值（nan/空值）由 to_float 过滤成 None。
        # 三个分支刻意重复而不抽函数：这是百万行级热路径，省下的调用开销可观。
        x = y = z = None
        for token in tokens[1:]:
            axis = token[0]
            if axis == "X" or axis == "x":
                value = to_float(token[1:])
                if value is not None:
                    x = value
            elif axis == "Y" or axis == "y":
                value = to_float(token[1:])
                if value is not None:
                    y = value
            elif axis == "Z" or axis == "z":
                value = to_float(token[1:])
                if value is not None:
                    z = value

        # G92 只改坐标原点，不产生移动；缺省的轴保持不变
        if command == "G92":
            if x is not None:
                pos_x = x
            if y is not None:
                pos_y = y
            if z is not None:
                pos_z = z
            continue

        # ------------------------------------------------------------ 推进位置
        if absolute:
            if x is not None:
                pos_x = x
            if y is not None:
                pos_y = y
            if z is not None:
                pos_z = z
        else:
            if x is not None:
                pos_x = (pos_x or 0.0) + x
            if y is not None:
                pos_y = (pos_y or 0.0) + y
            if z is not None:
                pos_z = (pos_z or 0.0) + z

        # ------------------------------------------------------------ 降级切层
        # 无 ;LAYER_CHANGE 时，Z 抬高即视为进入新一层（同层重复 Z 不算）
        if not split_by_marker and pos_z is not None:
            if layer_z is None or pos_z > layer_z + _Z_EPS:
                current = _LayerDraft(z_explicit=pos_z)
                layer_z = pos_z
                drafts.append(current)

        # 层内 Z 采样：z-hop 会抬高 Z，最小值最接近该层的真实打印高度
        if current is not None and pos_z is not None:
            if current.z_min is None or pos_z < current.z_min:
                current.z_min = pos_z

        # ------------------------------------------------------------ 累加 bbox
        if x is None and y is None:
            continue  # 纯 Z / 纯挤出线，不影响 XY 范围
        if current is None:
            if split_by_marker:
                continue  # 首层之前的内容（start code / 擦嘴）不计入 bbox
            current = _LayerDraft(z_explicit=pos_z)
            drafts.append(current)

        # 入 bbox 的是「解析后的绝对坐标」而不是行内的 x/y：
        # 相对模式下 x/y 只是增量，直接累加会把 bbox 完全算错。
        if x is not None and pos_x is not None:
            if current.x_min is None or pos_x < current.x_min:
                current.x_min = pos_x
            if current.x_max is None or pos_x > current.x_max:
                current.x_max = pos_x
        if y is not None and pos_y is not None:
            if current.y_min is None or pos_y < current.y_min:
                current.y_min = pos_y
            if current.y_max is None or pos_y > current.y_max:
                current.y_max = pos_y
        if command in _MOVE_CODES:
            current.moves += 1

    return drafts


def _freeze(drafts: list[_LayerDraft]) -> list[LayerSlice]:
    """把累加器固化成不可变层摘要，并补齐 Z。

    Z 取值顺序：``;Z:`` 注释 → 层内最小 Z → 上一层 Z（继承）→ ``0.0``。
    """
    slices: list[LayerSlice] = []
    last_z = 0.0
    for number, draft in enumerate(drafts, start=1):
        z_mm = draft.z_explicit
        if z_mm is None:
            z_mm = draft.z_min
        if z_mm is None:
            z_mm = last_z
        last_z = z_mm
        slices.append(
            LayerSlice(
                layer=number,
                z_mm=z_mm,
                x_min=0.0 if draft.x_min is None else draft.x_min,
                x_max=0.0 if draft.x_max is None else draft.x_max,
                y_min=0.0 if draft.y_min is None else draft.y_min,
                y_max=0.0 if draft.y_max is None else draft.y_max,
                moves=draft.moves,
            )
        )
    return slices


def _row_values(row: Any) -> list[Any]:
    """把缓存里的一行规整成 6 个位置参数（缺项补 ``0``）。"""
    if isinstance(row, Mapping):
        return [
            row.get("z_mm", row.get("z")),
            row.get("x_min"),
            row.get("x_max"),
            row.get("y_min"),
            row.get("y_max"),
            row.get("moves"),
        ]
    if isinstance(row, (list, tuple)):
        values = list(row[: len(_ROW_FIELDS)])
        values.extend([0.0] * (len(_ROW_FIELDS) - len(values)))
        return values
    return [0.0] * len(_ROW_FIELDS)


def _slice_from_row(row: Any, layer: int) -> LayerSlice:
    """从一行缓存数据还原层摘要；任何非法值降级为 ``0``。"""
    z_mm, x_min, x_max, y_min, y_max, moves = _row_values(row)
    count = to_float(moves)
    return LayerSlice(
        layer=layer,
        z_mm=_number(z_mm),
        x_min=_number(x_min),
        x_max=_number(x_max),
        y_min=_number(y_min),
        y_max=_number(y_max),
        moves=0 if count is None or count <= 0 else int(count),
    )


def _number(value: Any) -> float:
    """转 float；非法 / 缺失一律返回 ``0.0``（层索引宁可粗糙也不能缺行）。"""
    number = to_float(value)
    if number is None or not math.isfinite(number):
        return 0.0
    return number
