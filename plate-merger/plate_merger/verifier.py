"""合盘输出的结构校验。

校验发生在打包之后、交付之前。任何一项失败都意味着产物可能被打印机拒绝
或打印出错，因此 :meth:`VerificationReport.raise_if_failed` 会抛异常而非告警。

检查项覆盖三类风险：

1. **结构**：只能有一个 ``plate_*.gcode``，``model_settings`` 只能有一个 ``<plate>``；
2. **一致性**：``gcode_file`` 指向正确成员，``md5`` 与 G-code 实际内容一致；
3. **安全**：``G91``/``G90`` 必须成对（否则后续打印路径全错），换盘标记数量应等于盘数减一。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import ValidationError
from .gcode import check_relative_mode_balance, count_occurrences
from .io3mf import ThreeMfPackage, compute_md5
from .metadata import MERGED_GCODE_MEMBER

_PLATE_ID_PATTERN = re.compile(r'key="plater_id"\s+value="(\d+)"')
_GCODE_FILE_PATTERN = re.compile(r'key="gcode_file"\s+value="([^"]+)"')


@dataclass(frozen=True)
class CheckResult:
    """单项检查结果。"""

    name: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class VerificationReport:
    """整体校验报告。"""

    checks: tuple[CheckResult, ...]

    @property
    def passed(self) -> bool:
        """是否全部通过。"""
        return all(check.passed for check in self.checks)

    @property
    def failures(self) -> tuple[CheckResult, ...]:
        """未通过的检查项。"""
        return tuple(check for check in self.checks if not check.passed)

    def raise_if_failed(self) -> None:
        """存在失败项时抛异常。

        :raises ValidationError: 任一检查失败。
        """
        if self.passed:
            return
        summary = "; ".join(f"{check.name}: {check.detail}" for check in self.failures)
        raise ValidationError("合盘输出未通过校验", detail={"issues": summary})


def verify_package(
    package: ThreeMfPackage,
    *,
    expected_swap_count: int | None = None,
    swap_flag: str = ";start change plate",
) -> VerificationReport:
    """校验一个已打包的 3MF。

    :param package: 待校验的包。
    :param expected_swap_count: 期望的换盘次数（盘数 - 1）；``None`` 表示不检查。
    :param swap_flag: 换盘起始标记，必须与渲染时使用的一致（可通过配置自定义）。
    """
    checks: list[CheckResult] = []

    # ---- 1. 只能有一个盘 G-code
    gcodes = package.plate_gcodes()
    checks.append(
        CheckResult(
            name="single_plate_gcode",
            passed=len(gcodes) == 1,
            detail=f"发现 {len(gcodes)} 个盘 G-code：{[name for _, name in gcodes]}",
        )
    )

    if len(gcodes) == 1:
        member = gcodes[0][1]
        checks.append(
            CheckResult(
                name="gcode_member_name",
                passed=member.lower() == MERGED_GCODE_MEMBER.lower(),
                detail=f"实际成员为 {member}",
            )
        )

    # ---- 2. model_settings 结构
    try:
        model_settings = package.read_text("Metadata/model_settings.config")
    except Exception as exc:  # noqa: BLE001 - 校验器本身不应因读取失败而中断
        checks.append(CheckResult(name="model_settings_readable", passed=False, detail=str(exc)))
        model_settings = ""

    if model_settings:
        plate_ids = _PLATE_ID_PATTERN.findall(model_settings)
        checks.append(
            CheckResult(
                name="single_plate_entry",
                passed=len(plate_ids) == 1,
                detail=f"发现 {len(plate_ids)} 个 plater_id：{plate_ids}",
            )
        )

        gcode_refs = _GCODE_FILE_PATTERN.findall(model_settings)
        checks.append(
            CheckResult(
                name="gcode_file_points_to_merged",
                passed=gcode_refs == [MERGED_GCODE_MEMBER],
                detail=f"实际 gcode_file={gcode_refs}",
            )
        )

    # ---- 3. md5 一致性
    if len(gcodes) == 1:
        gcode_bytes = package.read(gcodes[0][1])
        expected = compute_md5(gcode_bytes, upper=True)
        md5_member = f"{gcodes[0][1]}.md5"
        if package.has(md5_member):
            actual = package.read_text(md5_member).strip()
            checks.append(
                CheckResult(
                    name="md5_matches",
                    passed=actual == expected,
                    detail=f"期望 {expected}，实际 {actual}",
                )
            )
            checks.append(
                CheckResult(
                    name="md5_is_uppercase",
                    passed=actual == actual.upper(),
                    detail=f"实际 {actual}",
                )
            )
        else:
            checks.append(CheckResult(name="md5_present", passed=False, detail=f"缺少 {md5_member}"))

    # ---- 4. G-code 安全项
    if len(gcodes) == 1:
        gcode_text = package.read_text(gcodes[0][1])
        mode_ok, mode_reason = check_relative_mode_balance(gcode_text)
        checks.append(
            CheckResult(
                name="relative_mode_closed",
                passed=mode_ok,
                detail=mode_reason or "模式已闭合",
            )
        )

        if expected_swap_count is not None:
            swaps = count_occurrences(gcode_text, swap_flag)
            checks.append(
                CheckResult(
                    name="swap_count",
                    passed=swaps == expected_swap_count,
                    detail=f"期望 {expected_swap_count}，实际 {swaps}",
                )
            )

    return VerificationReport(checks=tuple(checks))
