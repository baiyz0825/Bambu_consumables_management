"""导出 Bambu Studio 本地 HMS 错误码表为后端可直接加载的 JSON。

背景
----
MQTT 上报的 ``print.hms[]`` 只有 ``{attr, code}`` 整数，需要拼成 8 位 ecode
（attr 在前、code 在后，各 4 位 hex）才能查到人话文案。权威码表由 Bambu Studio
随版本更新，安装后落在：

- macOS:   ``~/Library/Application Support/BambuStudio/hms/``
- Windows: ``%APPDATA%/BambuStudio/hms/``
- Linux:   ``~/.config/BambuStudio/hms/``

本脚本把 ``hms_<lang>_<device>.json`` 与 ``hms_action_<device>.json`` 合并成
一份 ``app/data/hms_codes.json``，使容器内无需安装 Studio 也能展示故障文案。

用法
----
    python3 scripts/export_hms_codes.py                # 默认 A1(039) + 中文
    python3 scripts/export_hms_codes.py --device 039 --lang zh-cn
    python3 scripts/export_hms_codes.py --source /path/to/hms --out app/data/hms_codes.json

退出码
------
- ``0`` 导出成功，或源文件不存在（CI/容器环境属正常，直接跳过）；
- ``1`` 源文件存在但内容无法解析。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

#: 模块号 → 中文名。仅收录可从官方文档/现象确认的部分；
#: 未收录的模块前端显示为「模块 XX」，不做猜测。
MODULES: dict[str, str] = {
    "03": "运动控制",
    "05": "主板",
    "07": "AMS",
    "0C": "视觉模块",
}

#: 机型设备码 → 型号名
DEVICES: dict[str, str] = {
    "039": "A1",
    "030": "A1 mini",
    "01P": "P1P",
    "01S": "P1S",
    "03W": "X1",
    "03W2": "X1 Carbon",
    "BL-P002": "H2D",
}


def default_source_dir() -> Path:
    """按平台返回 Studio 的 hms 目录。"""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "BambuStudio" / "hms"
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home())) / "BambuStudio" / "hms"
    return Path.home() / ".config" / "BambuStudio" / "hms"


def load_codes(path: Path, lang: str) -> dict[str, str]:
    """读取 ``hms_<lang>_<device>.json``，返回 ``{ecode: intro}``。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data["data"]["device_error"][lang]
    return {
        str(item["ecode"]).upper(): str(item.get("intro", "")).strip()
        for item in entries
        if item.get("ecode")
    }


def load_actions(path: Path) -> dict[str, list[int]]:
    """读取 ``hms_action_<device>.json``，返回 ``{ecode: [action_id, ...]}``。"""
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, list[int]] = {}
    for item in data.get("data", []):
        ecode = item.get("ecode")
        if not ecode:
            continue
        out[str(ecode).upper()] = [int(a) for a in item.get("actions", []) if isinstance(a, int)]
    return out


def build(source: Path, device: str, lang: str) -> dict:
    codes_path = source / f"hms_{lang}_{device}.json"
    if not codes_path.is_file():
        # 某些版本语言文件名可能带其它后缀，退回扫描
        candidates = sorted(source.glob(f"hms_{lang}_{device}*.json"))
        if not candidates:
            raise FileNotFoundError(codes_path)
        codes_path = candidates[0]

    intros = load_codes(codes_path, lang)
    actions = load_actions(source / f"hms_action_{device}.json")

    codes = {}
    for ecode, intro in intros.items():
        codes[ecode] = {"intro": intro, "actions": actions.get(ecode, [])}

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "device": device,
        "device_name": DEVICES.get(device, device),
        "language": lang,
        "source": str(codes_path),
        "count": len(codes),
        "modules": MODULES,
        "codes": codes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="导出 Bambu Studio HMS 码表")
    parser.add_argument("--source", type=Path, default=default_source_dir())
    parser.add_argument("--device", default="039", help="设备码，A1 为 039")
    parser.add_argument("--lang", default="zh-cn")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "app" / "data" / "hms_codes.json",
    )
    args = parser.parse_args()

    if not args.source.is_dir():
        print(f"[skip] 未找到 HMS 目录：{args.source}", file=sys.stderr)
        print("[skip] 该环境未安装 Bambu Studio，保留仓库内已有码表。", file=sys.stderr)
        return 0

    try:
        payload = build(args.source, args.device, args.lang)
    except FileNotFoundError as exc:
        print(f"[skip] 未找到码表文件：{exc}", file=sys.stderr)
        return 0
    except (KeyError, json.JSONDecodeError) as exc:
        print(f"[error] 码表格式异常：{exc}", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"[ok] {payload['count']} 条 → {args.out} ({args.out.stat().st_size / 1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
