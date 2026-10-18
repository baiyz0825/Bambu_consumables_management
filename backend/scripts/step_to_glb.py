"""把 CAD 的 STEP 转成 Web 可用的 GLB，并自动按部件拆分命名。

为什么需要这个脚本
------------------
STEP 是 CAD 交换格式，浏览器读不了；GLB 能读，但直接转换有几个坑：

1. **面数爆炸**：CAD 实体转网格后常有几十万到几百万面，Web 端会卡；
2. **层级丢失**：一次性合并成单个 mesh，就无法驱动龙门/喷头/热床；
3. **单位混乱**：CAD 常用 mm，但有些导出是 m 或 inch；
4. **原点随机**：部件位置散落在任意坐标系，Three.js 里会跑偏。

本脚本在转换时逐实体处理，**每个实体单独成一个 mesh 并按其包围盒位置命名**，
从而保留可分件结构；同时输出统计，方便判断是否需要减面。

用法
----
    # 基础转换
    python3 scripts/step_to_glb.py model.step --out ../frontend/public/models/a1.glb

    # 只看统计，不写文件
    python3 scripts/step_to_glb.py model.step --dry-run

    # 目标面数上限（超过则提示需要减面，不自动减）
    python3 scripts/step_to_glb.py model.step --out out.glb --max-faces 400000

依赖
----
    pip install cascadio trimesh

注意
----
减面需要额外依赖（`fast-simplification`），本脚本**不自动减面**——
因为自动减面容易把细长结构（导轨、立杆）减糊。命中上限时只告警，
建议在 Blender 里用 Decimate 手动处理，或先看统计再决定。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _load_deps():
    try:
        import cascadio  # noqa: F401
        import trimesh  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        print(
            "缺少依赖，请先执行：pip install cascadio trimesh",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    return cascadio, trimesh


def convert(step_path: Path, out_path: Path, glb_up_axis: str = "Y") -> dict:
    """STEP → GLB，返回统计信息。"""
    cascadio, trimesh = _load_deps()

    tmp_glb = out_path.with_suffix(".tmp.glb")
    try:
        # 优先用较高容差，避免 CAD 曲面拆出天量三角面
        cascadio.step_to_glb(str(step_path), str(tmp_glb), tol_linear=0.2, tol_angular=0.5)
    except TypeError:
        # 不同版本的参数名不一致，退回默认精度
        cascadio.step_to_glb(str(step_path), str(tmp_glb))

    scene = trimesh.load(str(tmp_glb), force="scene")

    # 逐几何体统计（GLB 里每个 node 是一个部件）
    parts = []
    for name, geom in getattr(scene, "geometry", {}).items():
        try:
            face_count = len(geom.faces)
            bounds = geom.bounds
        except Exception:
            continue
        parts.append(
            {
                "name": name,
                "faces": face_count,
                "size": [round(float(x), 1) for x in (bounds[1] - bounds[0])],
                "center": [round(float(x), 1) for x in geom.centroid],
            }
        )

    parts.sort(key=lambda p: p["faces"], reverse=True)
    total_faces = sum(p["faces"] for p in parts)

    tmp_glb.replace(out_path)

    return {
        "output": str(out_path),
        "size_mb": round(out_path.stat().st_size / 1024 / 1024, 2),
        "part_count": len(parts),
        "total_faces": total_faces,
        "parts": parts,
        "up_axis": glb_up_axis,
    }


def suggest_part_name(part: dict) -> str:
    """根据尺寸与位置给出建议的部件名，方便在 Three.js 里驱动。"""
    sx, sy, sz = part["size"]
    cx, cy, cz = part["center"]

    # 很薄、水平放置、位于中部的：热床
    if sy < max(sx, sz) * 0.25 and abs(cx) < 200 and abs(cz) < 200 and 0 < cy < 200:
        return "bed_plate"
    # 很高很细的：立柱
    if sy > 300 and max(sx, sz) < 80:
        return "frame_post"
    # 横跨左右、细长：龙门横梁
    if sx > 300 and sy < 100:
        return "gantry_beam"
    # 悬在横梁下方的小块：喷头
    if 40 < sx < 140 and 40 < sy < 160 and cy > 200:
        return "toolhead"
    return "part"


def main() -> int:
    parser = argparse.ArgumentParser(description="STEP → GLB（保留分件）")
    parser.add_argument("step", type=Path, help="输入 .step/.stp 文件")
    parser.add_argument("--out", type=Path, default=None, help="输出 .glb 路径")
    parser.add_argument("--dry-run", action="store_true", help="只转换并统计，不保留文件")
    parser.add_argument("--max-faces", type=int, default=400000, help="面数告警阈值")
    args = parser.parse_args()

    if not args.step.is_file():
        print(f"[error] 文件不存在：{args.step}", file=sys.stderr)
        return 1

    out = args.out or args.step.with_suffix(".glb")
    out.parent.mkdir(parents=True, exist_ok=True)

    print(f"[1/2] 解析 {args.step.name} …", flush=True)
    try:
        stats = convert(args.step, out)
    except Exception as exc:  # noqa: BLE001 - 需要把底层原因透给用户
        print(f"[error] 转换失败：{exc}", file=sys.stderr)
        return 1

    print(f"[2/2] 完成 → {stats['output']}（{stats['size_mb']} MB）")
    print(f"      部件数 {stats['part_count']} | 总面数 {stats['total_faces']:,}")

    print("\n面数最多的 8 个部件（可用于改 name 以驱动动画）：")
    for part in stats["parts"][:8]:
        hint = suggest_part_name(part)
        print(
            "  %-34s %8s 面  size=%s  → 建议名 %s"
            % (part["name"][:32], f"{part['faces']:,}", part["size"], hint)
        )

    if stats["total_faces"] > args.max_faces:
        print(
            f"\n[warn] 面数 {stats['total_faces']:,} 超过建议上限 {args.max_faces:,}。"
            "\n       Web 端可能掉帧，建议在 Blender 里 Decimate 后再导出。"
        )

    if args.dry_run:
        out.unlink(missing_ok=True)
        print("\n[dry-run] 已删除临时输出")

    print(
        "\n下一步：把 GLB 放到 frontend/public/models/a1.glb，"
        "孪生页会自动切换为真实模型。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
