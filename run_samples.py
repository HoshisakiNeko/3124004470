"""对 ``sample_data`` 中的样例文件批量运行查重，输出结果对照表。

对应作业里"课堂上下发的 orig.txt / orig_add.txt 等样例"的验证方式：
把样例放在 ``sample_data`` 目录下，本脚本会依次调用与评测完全相同的
命令行入口（``main.py``）并打印每个样例的重复率。

用法（在项目根目录执行）::

    python tools/run_samples.py

输出的表格会同时写入 ``docs/samples_report.txt``，可直接放进博客。
"""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from plagiarism.cli import main  # noqa: E402  (需先补 sys.path)

SAMPLE_DIR = PROJECT_ROOT / "sample_data"
REPORT_PATH = PROJECT_ROOT / "docs" / "samples_report.txt"


def main_entry() -> int:
    original = SAMPLE_DIR / "orig.txt"
    if not original.exists():
        print(f"找不到样例文件：{original}")
        return 1

    rows = []
    with tempfile.TemporaryDirectory() as temp_dir:
        answer = Path(temp_dir) / "ans.txt"
        for suspect in sorted(SAMPLE_DIR.glob("orig*.txt")):
            if suspect == original:
                continue
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main([str(original), str(suspect), str(answer)])
            score = answer.read_text(encoding="utf-8").strip() if code == 0 else "失败"
            rows.append((suspect.name, score, code))

    lines = [
        "样例文件查重结果（原文 sample_data/orig.txt，指标：字符二元组 + 余弦相似度）",
        "",
        f"{'抄袭版文件':<20}{'重复率':>10}{'返回码':>8}",
        "-" * 40,
    ]
    for name, score, code in rows:
        lines.append(f"{name:<20}{score:>10}{code:>8}")
    report = "\n".join(lines)

    print(report)
    (PROJECT_ROOT / "docs").mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_entry())

