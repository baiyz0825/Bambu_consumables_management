"""3MF（OPC / ZIP）包的读写。

职责边界：本模块只做「字节层面的搬运」，不解释任何业务语义 ——
元数据解析在 :mod:`plate_merger.sliceinfo`，G-code 分块在 :mod:`plate_merger.gcode`。

为什么用标准库：3MF 就是 ZIP + 约定目录，``zipfile`` 足够；
少一个依赖就少一个版本风险（技术方案 §7.3 已明确运行时依赖清单）。
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from collections.abc import Mapping
from pathlib import Path

from .errors import InvalidPackageError

#: OPC 的包描述文件，必须排在压缩包首位
CONTENT_TYPES = "[Content_Types].xml"

#: 盘 G-code 成员名，如 ``Metadata/plate_1.gcode``
_PLATE_GCODE_PATTERN = re.compile(r"^Metadata/plate_(\d+)\.gcode$", re.IGNORECASE)

#: 固定时间戳：让「相同内容 → 相同字节」，便于回归测试与缓存
_FIXED_DATE_TIME = (1980, 1, 1, 0, 0, 0)


def compute_md5(data: bytes, *, upper: bool = True) -> str:
    """计算 32 位 MD5 十六进制串。

    Bambu 原生 3MF 内的 ``*.gcode.md5`` 使用**大写**，
    Bambu Connect 可能严格比对，因此默认输出大写。
    """
    digest = hashlib.md5(data).hexdigest()
    return digest.upper() if upper else digest


class ThreeMfPackage:
    """3MF 包的只读视图（上下文管理器）。

    用法::

        with ThreeMfPackage.open(path) as pkg:
            gcode = pkg.read_text("Metadata/plate_1.gcode")
    """

    def __init__(self, path: Path, archive: zipfile.ZipFile) -> None:
        self._path = path
        self._archive = archive
        # 小写名 -> 实际名。不同平台导出的成员名大小写可能不一致
        self._index: dict[str, str] = {name.lower(): name for name in archive.namelist()}

    # ------------------------------------------------------------------ 构造
    @classmethod
    def open(cls, path: str | Path) -> "ThreeMfPackage":
        """打开一个 3MF 文件。

        :raises InvalidPackageError: 文件不存在或不是合法 ZIP。
        """
        resolved = Path(path)
        if not resolved.is_file():
            raise InvalidPackageError("文件不存在", detail={"path": str(resolved)})
        try:
            archive = zipfile.ZipFile(resolved)
        except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError) as exc:
            # 统一收敛为工程内异常，避免底层异常类型逃逸到调用方
            raise InvalidPackageError(
                "无法作为 ZIP / 3MF 打开", detail={"path": str(resolved), "reason": type(exc).__name__}
            ) from exc
        return cls(resolved, archive)

    # ------------------------------------------------------------------ 元信息
    @property
    def path(self) -> Path:
        """包文件路径。"""
        return self._path

    @property
    def names(self) -> list[str]:
        """包内全部成员名（原始大小写）。"""
        return self._archive.namelist()

    def resolve(self, name: str) -> str | None:
        """大小写不敏感地把成员名解析为包内实际名称。

        :return: 实际成员名；不存在时返回 ``None``。
        """
        return self._index.get(name.lower())

    def has(self, name: str) -> bool:
        """判断成员是否存在（大小写不敏感）。"""
        return self.resolve(name) is not None

    # ------------------------------------------------------------------ 读取
    def read(self, name: str) -> bytes:
        """读取成员原始字节。

        :raises InvalidPackageError: 成员不存在。
        """
        actual = self.resolve(name)
        if actual is None:
            raise InvalidPackageError("包内缺少成员", detail={"path": str(self._path), "member": name})
        return self._archive.read(actual)

    def read_text(self, name: str, *, encoding: str = "utf-8") -> str:
        """严格解码读取文本成员。

        之所以默认严格：宽松解码会把非法字节静默替换成 U+FFFD，
        重新打包后与源文件字节不一致（md5 也会变），属于「静默产出半成品」。

        :raises InvalidPackageError: 成员不是合法文本。
        """
        try:
            return self.read(name).decode(encoding)
        except UnicodeDecodeError as exc:
            raise InvalidPackageError(
                "成员不是合法文本", detail={"member": name, "encoding": encoding}
            ) from exc

    def read_text_lossy(self, name: str, *, encoding: str = "utf-8") -> str:
        """宽松解码，仅用于日志与界面展示，不得用于重新打包。"""
        return self.read(name).decode(encoding, errors="replace")

    # ------------------------------------------------------------------ 盘相关
    def plate_gcodes(self) -> list[tuple[int, str]]:
        """列出所有盘 G-code 成员，按盘号升序。

        :return: ``[(盘号, 实际成员名), ...]``
        """
        found: list[tuple[int, str]] = []
        for actual in self.names:
            match = _PLATE_GCODE_PATTERN.match(actual)
            if match:
                found.append((int(match.group(1)), actual))
        found.sort(key=lambda item: item[0])
        return found

    def is_plate_sliced(self) -> bool:
        """是否包含内嵌 G-code（即 plate-sliced 导出，而非工程文件）。"""
        return bool(self.plate_gcodes())

    # ------------------------------------------------------------------ 生命周期
    def close(self) -> None:
        """关闭底层句柄。重复调用安全。"""
        self._archive.close()

    def __enter__(self) -> "ThreeMfPackage":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()


def write_3mf(
    path: str | Path,
    members: Mapping[str, bytes],
    *,
    opc_pack: bool = True,
) -> Path:
    """把成员字典写成 3MF 文件。

    ``opc_pack=True`` 时按 OPC 规范处理：

    1. ``[Content_Types].xml`` 作为**第一个**条目写入；
    2. 该条目使用 ``ZIP_STORED``（不压缩），其余使用 ``DEFLATE``。

    这两点是 Bambu Connect 接受文件的隐含前提，旧「数据重组」App 因未遵守而被静默拒绝。

    :param path: 输出路径，父目录不存在时自动创建。
    :param members: 成员名 -> 内容。
    :param opc_pack: 是否按 OPC 规范排序与设置存储方式。
    :raises InvalidPackageError: 开启 OPC 但缺少 ``[Content_Types].xml``。
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    # 决定写入顺序：Content_Types 必须最先，其余按名称排序以保证字节可复现
    ordered: list[tuple[str, bytes]] = []
    skip: str | None = None
    if opc_pack:
        content_key = next((name for name in members if name.lower() == CONTENT_TYPES.lower()), None)
        if content_key is None:
            raise InvalidPackageError("OPC 打包缺少包描述文件", detail={"member": CONTENT_TYPES})
        ordered.append((CONTENT_TYPES, members[content_key]))
        skip = content_key

    for name in sorted(members):
        if name == skip:
            continue
        ordered.append((name, members[name]))

    # 原子写入：先写临时文件再替换，避免中断时留下被当成成品的截断包
    temporary = target.with_name(f".{target.name}.tmp")
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in ordered:
                info = zipfile.ZipInfo(name, date_time=_FIXED_DATE_TIME)
                info.compress_type = (
                    zipfile.ZIP_STORED if (opc_pack and name == CONTENT_TYPES) else zipfile.ZIP_DEFLATED
                )
                info.external_attr = 0o600 << 16
                archive.writestr(info, data)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)

    return target
