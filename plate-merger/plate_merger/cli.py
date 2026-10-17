"""命令行入口。

用法示例：

.. code-block:: bash

    # 把同一个 3MF 的 3 个盘合并（带自动换盘）
    plate-merger merge "拖鞋架子.3mf#1" "拖鞋架子.3mf#2" "拖鞋架子.3mf#3" -o out.gcode.3mf

    # 指定换盘档位与裁剪策略
    plate-merger merge a.3mf#1 b.3mf#1 --preset builtin:a1-fast --policy slim
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .errors import PlateMergerError
from .models import MergeOptions, StartEndPolicy
from .pipeline import MergeRequest, merge
from .presets import get_preset, list_presets


def _parse_request(token: str) -> MergeRequest:
    """解析 ``路径#盘号`` 形式的输入。

    ``#`` 缺省时取第 1 盘。
    """
    source, separator, plate = token.rpartition("#")
    if not separator:
        return MergeRequest(source=Path(token), plate_index=1)
    if not plate.isdigit():
        raise argparse.ArgumentTypeError(f"盘号必须是数字：{token}")
    return MergeRequest(source=Path(source), plate_index=int(plate))


def build_parser() -> argparse.ArgumentParser:
    """构建参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="plate-merger",
        description="拓竹 A1 自动换盘：多盘 3MF 合盘工具",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    merge_parser = subparsers.add_parser("merge", help="合并多个已切片盘")
    merge_parser.add_argument("inputs", nargs="+", help="输入，格式为 路径#盘号（如 a.3mf#1）")
    merge_parser.add_argument("-o", "--output", help="输出文件路径")
    merge_parser.add_argument(
        "--preset",
        default="builtin:a1-conservative",
        help=f"换盘码预设，可用：{', '.join(item.preset_id for item in list_presets())}",
    )
    merge_parser.add_argument(
        "--policy",
        default=StartEndPolicy.SLIM.value,
        choices=[policy.value for policy in StartEndPolicy],
        help="中间盘 start/end 裁剪策略",
    )
    merge_parser.add_argument("--cooldown", type=int, default=None, help="换盘前热床降温目标（摄氏度）")
    merge_parser.add_argument("--wait", type=int, default=0, help="换盘后等待秒数")

    subparsers.add_parser("presets", help="列出内置换盘码预设")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """命令行主入口，返回进程退出码。"""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "presets":
        for preset in list_presets():
            print(f"{preset.preset_id:<28} {preset.name}  (Y≤{preset.y_limit:g}, {preset.approach_mode.value})")
        return 0

    try:
        requests = [_parse_request(token) for token in args.inputs]
        options = MergeOptions(
            swap_params=get_preset(args.preset),
            start_end_policy=StartEndPolicy(args.policy),
            hotbed_cooldown_c=args.cooldown,
            wait_after_swap_s=args.wait,
        )
        result = merge(requests, options=options, output=args.output)
    except PlateMergerError as exc:
        print(f"[失败] {exc.code}: {exc}", file=sys.stderr)
        return 1
    except argparse.ArgumentTypeError as exc:
        print(f"[失败] 参数错误: {exc}", file=sys.stderr)
        return 2

    print(f"输出：{result.output_path}")
    print(f"盘数：{result.plate_count}　G-code：{result.gcode_bytes} 字节　md5：{result.md5}")
    if result.total_time_s:
        print(f"预计时长：{result.total_time_s // 60} 分 {result.total_time_s % 60} 秒")
    if result.total_weight_g:
        print(f"预计耗材：{result.total_weight_g:g} g")
    for warning in result.warnings:
        print(f"[提示] {warning.code}: {warning.message}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
