"""把 AMS Lite 模型合并进打印机 GLB。

背景
----
A1 的官方结构 STEP 只含打印本体（25 个装配件），**不含 AMS Lite**。
AMS 需要单独找模型，转成网格后按真实位置拼到机器旁边。

三个必须处理的坑（本脚本就是为了解决它们）：

1. **单位不一致**：CAD 导出的 GLB 常以「米」为单位（机架高 0.426），
   而 AMS 模型多用「毫米」。直接合并会让 AMS 大 1000 倍、占满画面。
   → 脚本自动探测 base 的单位，把所有 mm 参数换算过去。
2. **变换丢失**：用 ``scene.geometry`` 直接取几何会丢掉每个节点的平移/旋转，
   所有部件会堆到原点。→ 用 ``scene.graph`` 遍历，保留变换与节点名。
3. **单料盘位**：社区常见的是「一个料盘位」的模型（约 70×130×115mm），
   而 AMS Lite 是 4 位 2×2。→ ``--repeat 2x2`` 先拼装再整体归一化。

用法
----
    # 1) 先看模型自身的尺寸与朝向
    python3 scripts/merge_ams_model.py ams.step --dry-run

    # 2) 单料盘位 → 2×2 拼装，合并到机器右侧
    python3 scripts/merge_ams_model.py ams.stl --repeat 2x2 --gap 30 --offset 380,0,-60

    # 3) 完整 AMS 模型（已是整机）
    python3 scripts/merge_ams_model.py ams.step --offset 380,0,-60

依赖: pip install cascadio trimesh
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_BASE = (
    Path(__file__).resolve().parents[2] / "frontend" / "public" / "models" / "a1.glb"
)


def _deps():
    try:
        import trimesh  # noqa: F401
    except ImportError:  # pragma: no cover
        print("缺少依赖：pip install cascadio trimesh", file=sys.stderr)
        raise SystemExit(1)
    return trimesh


def _load_any(path: Path):
    """加载 STEP / STL / GLB，统一返回 scene。"""
    trimesh = _deps()

    suffix = path.suffix.lower()
    if suffix in {".step", ".stp"}:
        try:
            import cascadio
        except ImportError:  # pragma: no cover
            print("读取 STEP 需要 cascadio：pip install cascadio", file=sys.stderr)
            raise SystemExit(1)
        tmp = path.with_suffix(".tmp-ams.glb")
        try:
            cascadio.step_to_glb(str(path), str(tmp), tol_linear=0.2, tol_angular=0.5)
        except TypeError:
            cascadio.step_to_glb(str(path), str(tmp))
        scene = trimesh.load(str(tmp), force="scene")
        tmp.unlink(missing_ok=True)
    elif suffix == ".stl":
        scene = trimesh.Scene(trimesh.load(str(path), force="mesh"))
    else:
        scene = trimesh.load(str(path), force="scene")

    return scene


def _describe(scene) -> dict:
    box = scene.bounds
    size = box[1] - box[0]
    faces = sum(len(g.faces) for g in scene.geometry.values()) if scene.geometry else 0
    return {
        "size": [round(float(x), 2) for x in size],
        "faces": faces,
        "geometries": len(scene.geometry),
    }


def normalize(scene, target: float, axis: str = "height"):
    """缩放到目标尺寸（默认按高度）、底部贴 y=0、水平居中。

    ``axis`` 可选 ``width`` / ``height`` / ``depth``：
    横向并排的部件（如 4 联送料器）应该按宽度归一化，按高度会被拉得巨大。
    """
    trimesh = _deps()

    box = scene.bounds
    size = box[1] - box[0]
    index = {"width": 0, "height": 1, "depth": 2}.get(axis, 1)
    current = float(size[index])
    scale = target / current if current > 1e-9 else 1.0
    scene.apply_transform(trimesh.transformations.scale_matrix(scale))

    box = scene.bounds
    center = (box[0] + box[1]) / 2
    scene.apply_transform(
        trimesh.transformations.translation_matrix(
            [-float(center[0]), -float(box[0][1]), -float(center[2])]
        )
    )
    return scene


def repeat_layout(scene, spec: str, gap: float):
    """把单个料盘位复制成 cols × rows 网格。"""
    trimesh = _deps()

    try:
        cols, rows = (int(v) for v in spec.lower().split("x"))
    except ValueError:
        return scene, (1, 1)
    if cols <= 1 and rows <= 1:
        return scene, (cols, rows)

    box = scene.bounds
    size = box[1] - box[0]
    step_x = float(size[0]) + gap
    step_z = float(size[2]) + gap

    out = trimesh.Scene()
    total = 0
    for row in range(rows):
        for col in range(cols):
            for geom in scene.geometry.values():
                copy = geom.copy()
                copy.apply_translation([col * step_x, 0.0, row * step_z])
                name = f"AMS_Lite_{total}"
                out.add_geometry(copy, geom_name=name, node_name=name)
                total += 1

    return out, (cols, rows)


def _add_preserving_transforms(target, source, prefix: str, rename_to: str | None = None):
    """把 source 的全部节点按原变换加入 target，保留节点名（前端靠名字识别部件）。"""
    count = 0
    for node in source.graph.nodes_geometry:
        transform, geom_name = source.graph[node]
        geom = source.geometry.get(geom_name)
        if geom is None:
            continue

        node_name = node if rename_to is None else (
            rename_to if count == 0 else f"{rename_to}_{count}"
        )
        # geom_name 也需唯一，否则 trimesh 会覆盖共用几何
        target.add_geometry(
            geom,
            transform=transform,
            geom_name=f"{prefix}{count}",
            node_name=node_name,
        )
        count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="合并 AMS Lite 到打印机 GLB")
    parser.add_argument("ams", type=Path, help="AMS 模型（.step/.stl/.glb）")
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE, help="打印机 GLB")
    parser.add_argument("--out", type=Path, default=None, help="输出 GLB")
    parser.add_argument("--height", type=float, default=400.0, help="AMS 目标尺寸 mm（默认 400）")
    parser.add_argument(
        "--fit",
        default="height",
        choices=["width", "height", "depth"],
        help="按哪个轴向归一化；横向并排的送料器用 width",
    )
    parser.add_argument("--offset", default="380,0,-60", help="摆放位置 x,y,z（mm）")
    parser.add_argument("--rotate-z", type=float, default=0.0, help="绕 Z 轴旋转角度")
    parser.add_argument("--repeat", default="1x1", help="复制成 NxM（单料盘位用 2x2）")
    parser.add_argument("--gap", type=float, default=20.0, help="复制间距 mm")
    parser.add_argument("--dry-run", action="store_true", help="只报告尺寸，不写文件")
    args = parser.parse_args()

    trimesh = _deps()

    if not args.ams.is_file():
        print(f"[error] 文件不存在：{args.ams}", file=sys.stderr)
        return 1

    print(f"[1/5] 读取 AMS：{args.ams.name} …", flush=True)
    try:
        scene = _load_any(args.ams)
    except Exception as exc:  # noqa: BLE001
        print(f"[error] 读取失败：{exc}", file=sys.stderr)
        return 1

    info = _describe(scene)
    print(f"      原始尺寸 {info['size']} | 部件 {info['geometries']} | 面数 {info['faces']:,}")

    if args.dry_run:
        print("\n[dry-run] 未写文件。判断要点：")
        print("  - 尺寸第 2 项（高度）若明显不是最大项，说明模型躺倒，需要先转正")
        print("  - AMS Lite 整机约 400(宽) × 300(深) × 400(高)；单料盘位约 70×130×115")
        return 0

    if not args.base.is_file():
        print(f"[error] 找不到打印机模型：{args.base}", file=sys.stderr)
        return 1

    # 探测 base 的单位：CAD 导出的 GLB 常是米制（机架高 0.426）
    printer = trimesh.load(str(args.base), force="scene")
    printer_height = float(printer.bounds[1][1] - printer.bounds[0][1])
    unit = 0.001 if printer_height < 10 else 1.0
    print(f"      打印机高度 {printer_height:.3f} → 单位换算 {unit}（1mm = {unit}）")

    scene, grid = repeat_layout(scene, args.repeat, args.gap * unit)
    if grid != (1, 1):
        print(f"[2/5] 复制 {grid[0]}×{grid[1]} 后整体归一化到 {args.height} mm")
    else:
        print(f"[2/5] 归一化到 {args.height} mm")
    scene = normalize(scene, args.height * unit, args.fit)

    if args.rotate_z:
        print(f"[3/5] 绕 Z 轴旋转 {args.rotate_z}°")
        scene.apply_transform(
            trimesh.transformations.rotation_matrix(
                args.rotate_z * 3.141592653589793 / 180.0, [0, 0, 1]
            )
        )

    try:
        ox, oy, oz = (float(v) for v in args.offset.split(","))
    except ValueError:
        print("[error] --offset 格式应为 x,y,z", file=sys.stderr)
        return 1
    print(f"[4/5] 偏移到 ({ox}, {oy}, {oz}) mm")
    scene.apply_transform(
        trimesh.transformations.translation_matrix([ox * unit, oy * unit, oz * unit])
    )

    out_path = args.out or args.base.with_name("a1-combo.glb")

    print("[5/5] 合并导出 …")
    combined = trimesh.Scene()
    printer_nodes = _add_preserving_transforms(combined, printer, prefix="printer_")
    ams_nodes = _add_preserving_transforms(combined, scene, prefix="ams_", rename_to="AMS_Lite")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    combined.export(str(out_path))

    total_faces = sum(len(g.faces) for g in combined.geometry.values())
    print(f"\n完成 → {out_path}")
    print(f"  部件 {printer_nodes} + {ams_nodes} | 总面数 {total_faces:,} | 大小 {out_path.stat().st_size / 1048576:.1f} MB")
    print("\n下一步：替换 frontend/public/models/a1.glb 后刷新页面。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
