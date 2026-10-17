"""层索引（G-code → 层号 / Z / XY bbox）测试。

全部用内联的最小 G-code 字符串构造，不依赖任何 3MF fixture：
层索引是纯文本算法，夹具反而会掩盖边界行为。
"""

from __future__ import annotations

import json

import pytest

from app.plate_merger.layers import (
    MODE_EMPTY,
    MODE_LAYER_CHANGE,
    MODE_Z,
    LayerIndex,
    LayerSlice,
)

#: 标准形态：Bambu/Orca 的切层注释 + `;Z:` + 绝对坐标
_SAMPLE_MARKED = (
    "; HEADER_BLOCK_START\n"
    "; layer_height = 0.2\n"
    "; HEADER_BLOCK_END\n"
    "M104 S220\n"
    "T0\n"
    "G28\n"
    ";LAYER_CHANGE\n"
    ";Z:0.2\n"
    ";HEIGHT:0.2\n"
    "G1 Z0.25 F720\n"
    "G1 X10 Y10 F9000\n"
    "G1 X20 Y12 E0.5\n"
    ";LAYER_CHANGE\n"
    ";Z:0.4\n"
    "G1 Z0.45 F720\n"
    "G1 X11 Y11 F9000\n"
    "G1 X21 Y21 E0.8\n"
)

#: 无切层注释：只能靠 Z 增大降级切层
_SAMPLE_Z_ONLY = (
    "G90\n"
    "G1 Z0.2 F720\n"
    "G1 X0 Y0\n"
    "G1 X5 Y5\n"
    "G1 Z0.4 F720\n"
    "G1 X6 Y6\n"
    "G1 Z0.6 F720\n"
    "G1 X7 Y7\n"
)


# --------------------------------------------------------------------- 基本切层
def test_build_splits_by_layer_change() -> None:
    """层号、Z、bbox、moves 的基础断言。"""
    index = LayerIndex.build(_SAMPLE_MARKED)

    assert index.mode == MODE_LAYER_CHANGE
    assert index.len == 2
    assert len(index) == 2

    first = index.layer(1)
    second = index.layer(2)
    assert first is not None
    assert second is not None
    assert (first.layer, second.layer) == (1, 2)

    # `;Z:` 优先于从 G1 推断的 Z（0.25 / 0.45 是 z-hop，不是层高）
    assert first.z_mm == pytest.approx(0.2)
    assert second.z_mm == pytest.approx(0.4)

    assert (first.x_min, first.x_max, first.y_min, first.y_max) == (10.0, 20.0, 10.0, 12.0)
    assert (second.x_min, second.x_max, second.y_min, second.y_max) == (11.0, 21.0, 11.0, 21.0)

    # G1 Z0.25 没有 XY，不计入 moves
    assert (first.moves, second.moves) == (2, 2)


def test_layer_change_discards_moves_before_first_layer() -> None:
    """首个切层注释之前的 start code / 擦嘴不应污染 bbox。"""
    gcode = "G28\nG1 X-40 Y0\nG1 X300 Y300\n;LAYER_CHANGE\n;Z:0.2\nG1 X10 Y10\n"

    index = LayerIndex.build(gcode)

    assert index.len == 1
    assert index.bbox() == (10.0, 10.0, 10.0, 10.0)


def test_crlf_input() -> None:
    """3MF 内的 G-code 可能是 CRLF，行尾的 \\r 不能被当成坐标内容。"""
    index = LayerIndex.build(_SAMPLE_MARKED.replace("\n", "\r\n"))

    assert index.len == 2
    assert index.layer(2) is not None
    assert index.layer(2).z_mm == pytest.approx(0.4)


def test_bbox_covers_all_layers() -> None:
    index = LayerIndex.build(_SAMPLE_MARKED)

    assert index.bbox() == (10.0, 21.0, 10.0, 21.0)


# --------------------------------------------------------------------- 降级切层
def test_fallback_split_by_z_increase() -> None:
    """没有 ;LAYER_CHANGE 时按 Z 增大切层。"""
    index = LayerIndex.build(_SAMPLE_Z_ONLY)

    assert index.mode == MODE_Z
    assert index.len == 3
    assert [item.z_mm for item in index.layers] == pytest.approx([0.2, 0.4, 0.6])

    assert index.layers[0].x_max == 5.0
    assert index.layers[1].x_max == 6.0
    assert (index.layers[2].x_min, index.layers[2].y_min) == (7.0, 7.0)


def test_fallback_ignores_repeated_z() -> None:
    """同层重复声明同一个 Z 不应切出新层。"""
    index = LayerIndex.build("G90\nG1 Z0.2\nG1 X1 Y1\nG1 Z0.2\nG1 X2 Y2\n")

    assert index.len == 1
    assert index.layers[0].x_max == 2.0
    assert [item.moves for item in index.layers] == [2]


def test_fallback_ignores_z_decrease() -> None:
    """Z 下降（回抽/探测）不算新层。"""
    index = LayerIndex.build("G90\nG1 Z0.6\nG1 X1 Y1\nG1 Z0.4\nG1 X2 Y2\n")

    assert index.len == 1
    assert index.layers[0].z_mm == pytest.approx(0.6)


# --------------------------------------------------------------------- 坐标模式
def test_relative_mode_accumulates() -> None:
    """G91 之后的坐标要累加到当前位置上。"""
    gcode = ";LAYER_CHANGE\n;Z:0.2\nG90\nG1 X10 Y10\nG91\nG1 X5 Y5\nG1 X1 Y2\nG90\n"

    layer = LayerIndex.build(gcode).layer(1)

    assert layer is not None
    assert (layer.x_min, layer.x_max, layer.y_min, layer.y_max) == (10.0, 16.0, 10.0, 17.0)
    assert layer.moves == 3


def test_g92_resets_origin() -> None:
    """G92 之后当前坐标被重置，随后的相对移动从新原点累加。

    若 G92 被忽略，``G91`` 后的 ``G1 X5 Y5`` 会加到 100 上得到 105，
    bbox 上界就成了 105 —— 用它来验证原点重置确实生效。
    """
    gcode = ";LAYER_CHANGE\n;Z:0.2\nG90\nG1 X100 Y100\nG92 X0 Y0\nG91\nG1 X5 Y5\n"

    layer = LayerIndex.build(gcode).layer(1)

    assert layer is not None
    assert (layer.x_min, layer.x_max, layer.y_min, layer.y_max) == (5.0, 100.0, 5.0, 100.0)


def test_arc_endpoint_extends_bbox_but_not_moves() -> None:
    """G2/G3 用端点近似，计 bbox 但不算「直线走线」。"""
    gcode = ";LAYER_CHANGE\n;Z:0.2\nG1 X0 Y0\nG3 X10 Y10 I5 J0\n"

    layer = LayerIndex.build(gcode).layer(1)

    assert layer is not None
    assert (layer.x_max, layer.y_max) == (10.0, 10.0)
    assert layer.moves == 1


# --------------------------------------------------------------------- locate
def test_locate_interpolates_bbox_diagonal() -> None:
    """fraction=0/1 必须落在 bbox 的两端。"""
    index = LayerIndex.build(_SAMPLE_MARKED)
    z = index.layers[0].z_mm

    assert index.locate(1, 0.0) == (10.0, 10.0, z)
    assert index.locate(1) == (10.0, 10.0, z)  # 默认 fraction=0
    assert index.locate(1, 1.0) == (20.0, 12.0, z)
    assert index.locate(1, 0.5) == pytest.approx((15.0, 11.0, z))

    # 越界 / 非法 fraction 一律夹到 [0, 1]，不抛异常
    assert index.locate(1, 2.0) == (20.0, 12.0, z)
    assert index.locate(1, -1.0) == (10.0, 10.0, z)
    assert index.locate(1, float("nan")) == (10.0, 10.0, z)


def test_locate_uses_layer_z() -> None:
    """不同层返回各自的 Z，便于孪生动画沿层高上升。"""
    index = LayerIndex.build(_SAMPLE_MARKED)

    assert index.locate(1, 0.5)[2] == pytest.approx(0.2)  # type: ignore[index]
    assert index.locate(2, 0.5)[2] == pytest.approx(0.4)  # type: ignore[index]


# --------------------------------------------------------------------- 越界与空输入
def test_layer_lookup_out_of_range() -> None:
    """越界层号返回 None，绝不抛异常（MQTT 层号会抖动）。"""
    index = LayerIndex.build(_SAMPLE_MARKED)

    assert index.layer(0) is None
    assert index.layer(3) is None
    assert index.layer(-1) is None
    assert index.locate(0) is None
    assert index.locate(3) is None
    assert index.locate(99, 0.5) is None


@pytest.mark.parametrize("text", ["", "\n\n\n", "; HEADER\n; layer_height = 0.2\n", "G28\nM400\n"])
def test_empty_input_yields_zero_layers(text: str) -> None:
    """空文本 / 只有注释时返回 0 层，各查询接口都不崩。"""
    index = LayerIndex.build(text)

    assert index.mode == MODE_EMPTY
    assert index.len == 0
    assert len(index) == 0
    assert index.bbox() is None
    assert index.layer(1) is None
    assert index.locate(1) is None
    assert index.to_dict()["layers"] == []


def test_empty_but_valid_index() -> None:
    """LayerIndex 直接构造空实例也可用。"""
    index = LayerIndex()

    assert index.len == 0
    assert index.bbox() is None
    assert LayerIndex.from_dict(index.to_dict()).mode == MODE_EMPTY


# --------------------------------------------------------------------- 非法数值
def test_invalid_numbers_are_skipped() -> None:
    """非法数值行被跳过，且不影响其它层的解析。"""
    gcode = (
        ";LAYER_CHANGE\n"
        ";Z:0.2\n"
        "G1 Xnan Y\n"
        ";LAYER_CHANGE\n"
        ";Z:0.4\n"
        "G1 X1 Y2\n"
    )

    index = LayerIndex.build(gcode)

    assert index.len == 2  # 坏行不产生异常，也不吞掉层
    bad = index.layer(1)
    good = index.layer(2)
    assert bad is not None
    assert good is not None

    assert bad.z_mm == pytest.approx(0.2)  # `;Z:` 仍然生效
    assert bad.moves == 0
    assert bad.has_xy is False

    assert (good.x_min, good.x_max, good.y_min, good.y_max) == (1.0, 1.0, 2.0, 2.0)
    assert good.moves == 1
    # 非法层不污染整体 bbox
    assert index.bbox() == (1.0, 1.0, 2.0, 2.0)


def test_empty_layer_is_kept_for_layer_number_alignment() -> None:
    """只有 Z、没有走线的层必须保留，否则后续层号整体错位。"""
    gcode = ";LAYER_CHANGE\n;Z:0.2\n;LAYER_CHANGE\n;Z:0.4\nG1 X5 Y5\n"

    index = LayerIndex.build(gcode)

    assert index.len == 2
    assert index.layer(1) is not None
    assert index.layer(1).z_mm == pytest.approx(0.2)
    assert index.layer(1).has_xy is False
    assert index.layer(2).z_mm == pytest.approx(0.4)  # type: ignore[union-attr]


# --------------------------------------------------------------------- 序列化
def test_to_dict_roundtrip() -> None:
    """to_dict / from_dict 往返一致，且体积可控（每层 6 个数字）。"""
    index = LayerIndex.build(_SAMPLE_MARKED)

    payload = index.to_dict()
    assert len(payload["layers"][0]) == 6
    assert json.dumps(payload)  # 必须可 JSON 序列化

    restored = LayerIndex.from_dict(json.loads(json.dumps(payload)))
    assert restored == index
    assert restored.to_dict() == payload


def test_from_dict_tolerates_missing_fields() -> None:
    """缺字段 / 坏行降级为占位层，不丢行（保住层号对齐）。"""
    assert LayerIndex.from_dict(None).len == 0
    assert LayerIndex.from_dict({}).len == 0
    assert LayerIndex.from_dict({"layers": "oops"}).len == 0  # type: ignore[dict-item]

    restored = LayerIndex.from_dict({"layers": [[0.2], [], "junk"]})

    assert restored.len == 3
    first = restored.layer(1)
    assert first is not None
    assert first.z_mm == pytest.approx(0.2)
    assert (first.x_min, first.moves) == (0.0, 0)
    assert restored.layer(3) == LayerSlice(
        layer=3, z_mm=0.0, x_min=0.0, x_max=0.0, y_min=0.0, y_max=0.0, moves=0
    )


def test_from_dict_accepts_mapping_rows() -> None:
    """兼容 dict 形式的历史缓存。"""
    restored = LayerIndex.from_dict(
        {
            "mode": MODE_LAYER_CHANGE,
            "layers": [{"z_mm": 0.2, "x_min": 1.0, "x_max": 2.0, "y_min": 3.0, "y_max": 4.0, "moves": 7}],
        }
    )

    assert restored.mode == MODE_LAYER_CHANGE
    assert restored.layer(1) == LayerSlice(
        layer=1, z_mm=0.2, x_min=1.0, x_max=2.0, y_min=3.0, y_max=4.0, moves=7
    )
