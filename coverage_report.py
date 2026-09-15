"""用标准库 ``trace`` 统计单元测试的语句分支覆盖率。

为什么不用 coverage.py：本作业要求程序本身"零第三方依赖"，
而覆盖率只是开发期的度量手段，因此这里直接用标准库的 ``trace``
模块（等价于 coverage 的"行覆盖率"）实现，保证任何一台只装了
标准库 Python 的电脑都能复现这张覆盖率表格。

用法（在项目根目录执行）::

    python tools/coverage_report.py

输出：
* 屏幕上的覆盖率汇总表；
* ``docs/coverage/`` 下的带 ``>>>>>>`` 标记的源码副本（可截图放进博客）。
"""

from __future__ import annotations

import io
import os
import sys
import trace
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
COVER_DIR = PROJECT_ROOT / "docs" / "coverage"


def _run_test_suite() -> unittest.result.TestResult:
    """用 unittest 的编程接口运行 tests 包中的全部用例。"""
    suite = unittest.defaultTestLoader.discover(
        start_dir=str(PROJECT_ROOT / "tests"),
        top_level_dir=str(PROJECT_ROOT),
    )
    runner = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0)
    return runner.run(suite)


def main() -> int:
    os.chdir(PROJECT_ROOT)
    sys.path.insert(0, str(PROJECT_ROOT))
    COVER_DIR.mkdir(parents=True, exist_ok=True)

    # 只关心本项目源码的覆盖率，标准库与 Python 安装目录一律忽略，
    # 这样既能让报告聚焦，也能显著缩短带跟踪的运行时间。
    ignoredirs = [
        sys.prefix,
        sys.exec_prefix,
        str(PROJECT_ROOT / "tests"),
        str(PROJECT_ROOT / "tools"),
    ]
    tracer = trace.Trace(count=1, trace=0, ignoredirs=ignoredirs)
    result = tracer.runfunc(_run_test_suite)

    print(f"测试用例：{result.testsRun} 个，"
          f"失败 {len(result.failures)} 个，错误 {len(result.errors)} 个")
    if not result.wasSuccessful():
        return 1

    buffer = io.StringIO()
    real_stdout = sys.stdout
    try:
        sys.stdout = buffer
        tracer.results().write_results(
            show_missing=True, summary=True, coverdir=str(COVER_DIR)
        )
    finally:
        sys.stdout = real_stdout

    report_lines = ["语句覆盖率（只统计本项目的核心代码）：", ""]
    report_lines.append(f"{'模块':<24}{'覆盖率':>8}{'总语句':>8}{'未覆盖':>8}")
    report_lines.append("-" * 48)
    total_statement = 0
    total_hit = 0
    for line in buffer.getvalue().splitlines():
        if "plagiarism" not in line and "main.py" not in line:
            continue
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) < 4 or not fields[0].isdigit():
            continue
        statements, percent, module = int(fields[0]), fields[1], fields[-2]
        hit = round(statements * float(percent.rstrip("%")) / 100)
        missing = statements - hit
        total_statement += statements
        total_hit += hit
        report_lines.append(f"{module:<24}{percent:>8}{statements:>8}{missing:>8}")
    if total_statement:
        overall = total_hit / total_statement * 100
        report_lines.append("-" * 48)
        report_lines.append(
            f"{'合计':<24}{overall:>7.1f}%{total_statement:>8}{total_statement - total_hit:>8}"
        )

    # 汇总每个文件里仍未被执行到的行号，方便在博客中说明覆盖率的缺口。
    report_lines.extend(["", "未覆盖行号（按文件）："])
    for annotated in sorted(COVER_DIR.glob("*.cover")):
        missing_lines = []
        for number, text in enumerate(
            annotated.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if text.startswith(">>>>>>"):
                missing_lines.append(number)
        if missing_lines:
            report_lines.append(
                f"  {annotated.name}: {', '.join(str(n) for n in missing_lines)}"
            )
    if not any(line.startswith("  ") for line in report_lines):
        report_lines.append("  （无）")

    report_lines.append("")
    report_lines.append(f"标注源码已写入：{COVER_DIR}")
    report_text = "\n".join(report_lines)
    print(report_text)
    (PROJECT_ROOT / "docs" / "coverage_report.txt").write_text(
        report_text + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
