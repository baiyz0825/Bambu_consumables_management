"""命令行入口。

子命令：

- ``merge``     合并多个已切片盘
- ``stats``     只统计不生成（盘数 / 时长 / 耗材）
- ``presets``   列出内置换盘码预设
- ``probe``     探测切片产物结构指纹（用于版本适配）
- ``test-file`` 生成不加热、不耗料的换盘测试文件
- ``dispatch``  上传并启动打印
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .audio import PLATE_SOUND_FLAG  # noqa: F401 - 保留导出便于排查
from .dispatch import PrinterTarget, dispatch
from .errors import PlateMergerError
from .filament import build_plan
from .fingerprint import probe
from .io3mf import ThreeMfPackage
from .models import AudioMode, MergeOptions, PlateDisplay, PlateInfo, StartEndPolicy
from .pipeline import MergeRequest, merge
from .presets import get_preset, list_presets
from .sliceinfo import parse_slice_info
from .toolfile import build_tool_file


def _parse_request(token: str) -> MergeRequest:
    """解析 ``路径#盘号`` 形式的输入；``#`` 缺省时取第 1 盘。"""
    source, separator, plate = token.rpartition("#")
    if not separator:
        if not token:
            raise argparse.ArgumentTypeError("输入路径不能为空")
        return MergeRequest(source=Path(token), plate_index=1)
    if not source:
        raise argparse.ArgumentTypeError(f"缺少文件路径：{token}")
    if not plate.isdigit():
        raise argparse.ArgumentTypeError(f"盘号必须是数字：{token}")
    if int(plate) < 1:
        raise argparse.ArgumentTypeError(f"盘号必须 >= 1：{token}")
    return MergeRequest(source=Path(source), plate_index=int(plate))


def _load_plates(requests: Sequence[MergeRequest]) -> list[PlateInfo]:
    """读取各盘的耗材信息（仅元数据，不读 G-code 正文）。"""
    plates: list[PlateInfo] = []
    for position, request in enumerate(requests, start=1):
        with ThreeMfPackage.open(request.source) as package:
            slice_info = parse_slice_info(package.read_text("Metadata/slice_info.config"))
            slice_plate = slice_info.plate(request.plate_index)
            if slice_plate is None:
                raise PlateMergerError(
                    "slice_info 中缺少对应盘",
                    detail={"source": str(request.source), "plate": request.plate_index},
                )
            plates.append(
                PlateInfo(
                    index=position,
                    gcode_member=f"Metadata/plate_{request.plate_index}.gcode",
                    prediction_s=slice_plate.prediction_s,
                    weight_g=slice_plate.weight_g,
                    filaments=slice_plate.filaments,
                    client_version=slice_info.header.client_version,
                )
            )
    return plates


def build_parser() -> argparse.ArgumentParser:
    """构建参数解析器。"""
    parser = argparse.ArgumentParser(prog="plate-merger", description="拓竹 A1 自动换盘：多盘 3MF 合盘工具")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    sub = parser.add_subparsers(dest="command", required=True)

    merge_parser = sub.add_parser("merge", help="合并多个已切片盘")
    merge_parser.add_argument("inputs", nargs="+", help="输入，格式为 路径#盘号（如 a.3mf#1）")
    merge_parser.add_argument("-o", "--output", help="输出文件路径")
    merge_parser.add_argument("--preset", default="builtin:a1-conservative", help="换盘码预设 ID")
    merge_parser.add_argument(
        "--policy",
        default=StartEndPolicy.SLIM.value,
        choices=[item.value for item in StartEndPolicy],
        help="中间盘 start/end 裁剪策略",
    )
    merge_parser.add_argument("--cooldown", type=int, default=None, help="换盘前热床降温目标（摄氏度）")
    merge_parser.add_argument("--wait", type=int, default=0, help="换盘后等待秒数")
    merge_parser.add_argument(
        "--display",
        default=PlateDisplay.OFF.value,
        choices=[item.value for item in PlateDisplay],
        help="盘号显示方式（需实机验证）",
    )
    merge_parser.add_argument(
        "--pre-sound",
        default=AudioMode.OFF.value,
        choices=[item.value for item in AudioMode],
        help="换盘前提示音",
    )
    merge_parser.add_argument(
        "--post-sound",
        default=AudioMode.JINGLE.value,
        choices=[item.value for item in AudioMode],
        help="换盘后提示音",
    )

    stats_parser = sub.add_parser("stats", help="只统计盘数、时长与耗材")
    stats_parser.add_argument("inputs", nargs="+", help="输入，格式为 路径#盘号")

    sub.add_parser("presets", help="列出内置换盘码预设")

    probe_parser = sub.add_parser("probe", help="探测切片产物结构指纹")
    probe_parser.add_argument("file", help="3MF 路径")
    probe_parser.add_argument("--save", help="把指纹保存到指定目录")

    test_parser = sub.add_parser("test-file", help="生成不加热、不耗料的换盘测试文件")
    test_parser.add_argument("template", help="作为壳的已切片 3MF")
    test_parser.add_argument("--cycles", type=int, default=1, help="换盘次数")
    test_parser.add_argument("--preset", default="builtin:a1-conservative", help="换盘码预设 ID")
    test_parser.add_argument("-o", "--output", help="输出路径")

    dispatch_parser = sub.add_parser("dispatch", help="上传并启动打印")
    dispatch_parser.add_argument("file", help="合盘后的 .gcode.3mf")
    dispatch_parser.add_argument("--host", required=True, help="打印机 IP")
    dispatch_parser.add_argument("--code", required=True, help="访问码")
    dispatch_parser.add_argument("--serial", required=True, help="序列号")
    dispatch_parser.add_argument("--use-ams", action="store_true", help="启用 AMS")
    dispatch_parser.add_argument("--mapping", default="", help="AMS 映射，如 0,1")
    dispatch_parser.add_argument("--wait", type=float, default=15.0, help="等待状态确认的秒数")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """命令行主入口，返回进程退出码。"""
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "presets":
            return _cmd_presets()
        if args.command == "probe":
            return _cmd_probe(args)
        if args.command == "stats":
            return _cmd_stats(args)
        if args.command == "test-file":
            return _cmd_test_file(args)
        if args.command == "dispatch":
            return _cmd_dispatch(args)
        return _cmd_merge(args)
    except PlateMergerError as exc:
        print(f"[失败] {exc.code}: {exc}", file=sys.stderr)
        return 1
    except argparse.ArgumentTypeError as exc:
        print(f"[失败] 参数错误: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"[失败] 文件操作失败: {exc}", file=sys.stderr)
        return 3


def _cmd_presets() -> int:
    for preset in list_presets():
        print(f"{preset.preset_id:<28} {preset.name}  (Y≤{preset.y_limit:g}, {preset.approach_mode.value})")
    return 0


def _cmd_merge(args: argparse.Namespace) -> int:
    requests = [_parse_request(token) for token in args.inputs]
    options = MergeOptions(
        swap_params=get_preset(args.preset),
        start_end_policy=StartEndPolicy(args.policy),
        hotbed_cooldown_c=args.cooldown,
        wait_after_swap_s=args.wait,
        plate_display=PlateDisplay(args.display),
        pre_change_sound=AudioMode(args.pre_sound),
        post_change_sound=AudioMode(args.post_sound),
    )
    result = merge(requests, options=options, output=args.output)

    print(f"输出：{result.output_path}")
    print(f"盘数：{result.plate_count}　G-code：{result.gcode_bytes} 字节　md5：{result.md5}")
    if result.total_time_s:
        print(f"预计时长：{result.total_time_s // 3600} 时 {result.total_time_s % 3600 // 60} 分")
    if result.total_weight_g:
        print(f"预计耗材：{result.total_weight_g:g} g")
    for warning in result.warnings:
        print(f"[提示] {warning.code}: {warning.message}")
    return 0


def _cmd_stats(args: argparse.Namespace) -> int:
    plates = _load_plates([_parse_request(token) for token in args.inputs])
    plan = build_plan(plates)

    total_seconds = sum(plate.prediction_s or 0 for plate in plates)
    total_weight = sum(plate.weight_g or 0.0 for plate in plates)
    print(f"盘数：{len(plates)}　预计时长：{total_seconds // 3600} 时 {total_seconds % 3600 // 60} 分　耗材：{total_weight:g} g")
    print()
    print(f"{'全局槽位':<10}{'类型':<10}{'颜色':<10}{'用量(g)':<12}{'出现盘'}")
    for item in plan.filaments:
        plates_text = ",".join(str(index) for index in item.plate_indexes)
        print(f"{item.slot:<12}{item.type or '-':<12}{item.color:<12}{item.total_used_g:<14.2f}{plates_text}")
    for warning in plan.warnings:
        print(f"[提示] {warning.code}: {warning.message}")
    return 0


def _cmd_probe(args: argparse.Namespace) -> int:
    fingerprint = probe(args.file)
    payload = fingerprint.to_dict()

    if args.save:
        directory = Path(args.save)
        directory.mkdir(parents=True, exist_ok=True)
        name = f"{fingerprint.client_version or 'unknown'}.json"
        target = directory / name
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"指纹已保存：{target}")
        return 0

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _cmd_test_file(args: argparse.Namespace) -> int:
    options = MergeOptions(swap_params=get_preset(args.preset))
    path = build_tool_file(args.template, cycles=args.cycles, options=options, output=args.output)
    print(f"测试文件：{path}")
    print(f"换盘次数：{args.cycles}（不加热、不耗料）")
    return 0


def _cmd_dispatch(args: argparse.Namespace) -> int:
    target = PrinterTarget(host=args.host, access_code=args.code, serial=args.serial)
    result = dispatch(
        args.file,
        target,
        use_ams=args.use_ams,
        ams_mapping=args.mapping,
        wait_s=args.wait,
    )
    print(f"上传：{result.remote_name}")
    print(f"结果：{'已接受' if result.accepted else '未确认'}（{result.detail}）")
    return 0 if result.accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
