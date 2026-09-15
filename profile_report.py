"""用标准库 ``cProfile`` 做性能分析，并生成性能分析图（SVG）。

对应作业要求中的"使用性能分析工具找出代码中的性能瓶颈并进行改进"：

* 用 ``cProfile`` 采集整条流水线（读取 → 归一化 → 特征提取 → 相似度）的耗时；
* 用 ``pstats`` 输出"消耗最大的函数"排名（按累计时间与自身时间两种口径）；
* 生成一张横向条形图 ``docs/profile_chart.svg``，可直接插入博客或截图。

用法（在项目根目录执行）::

    python tools/profile_report.py [文本字符数]

默认使用约 100 万字符的合成语料，模拟"较长的论文"。
"""

from __future__ import annotations

import cProfile
import io
import json
import pstats
import platform
import random
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from plagiarism.cli import Settings, run  # noqa: E402  (需先补 sys.path)

DEFAULT_CHARS = 1_000_000
CHART_PATH = PROJECT_ROOT / "docs" / "profile_chart.svg"
STATS_PATH = PROJECT_ROOT / "docs" / "profile_stats.txt"


def build_corpus(size: int, seed: int = 20240915) -> tuple[str, str]:
    """生成一对"原文 / 抄袭版"合成语料（抄袭版 = 原文 + 改动 + 新增）。"""
    rng = random.Random(seed)
    vocabulary = [chr(0x4E00 + index) for index in range(3000)]
    original = "".join(rng.choice(vocabulary) for _ in range(size))
    # 保留前 70%，其余替换为新字符，模拟"增删改"的抄袭方式。
    suspect = original[: int(size * 0.7)] + "".join(
        rng.choice(vocabulary) for _ in range(int(size * 0.3))
    )
    return original, suspect


def run_pipeline(original_path: str, suspect_path: str, answer_path: str) -> float:
    """执行一次完整流程，返回耗时（秒）。"""
    settings = Settings(
        original_path=original_path,
        suspect_path=suspect_path,
        answer_path=answer_path,
        quiet=True,
    )
    started = time.perf_counter()
    run(settings)
    return time.perf_counter() - started


def write_bar_chart(path: Path, entries: list[tuple[str, float]], total: float) -> None:
    """把"函数 → 累计耗时占比"画成简单的 SVG 条形图（不依赖第三方库）。"""
    row_height = 26
    width = 860
    height = 70 + row_height * len(entries)
    bar_width_max = 460

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="20" y="32" font-family="Consolas,monospace" font-size="16" '
        f'font-weight="bold">cProfile cumulative time (total '
        f'{total:.3f}s)</text>',
    ]
    for index, (name, value) in enumerate(entries):
        top = 52 + index * row_height
        ratio = value / total if total else 0.0
        bar_width = max(1.0, bar_width_max * ratio)
        parts.append(
            f'<text x="20" y="{top + 14}" font-family="Consolas,monospace" '
            f'font-size="12">{name}</text>'
        )
        parts.append(
            f'<rect x="330" y="{top}" width="{bar_width:.1f}" height="16" '
            f'fill="#3b7dd8"/>'
        )
        parts.append(
            f'<text x="{340 + bar_width:.1f}" y="{top + 13}" '
            f'font-family="Consolas,monospace" font-size="12">'
            f'{value:.4f}s ({ratio * 100:.1f}%)</text>'
        )
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def main() -> int:
    size = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CHARS
    original_text, suspect_text = build_corpus(size)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        original_path = temp / "orig.txt"
        suspect_path = temp / "orig_add.txt"
        answer_path = temp / "ans.txt"
        original_path.write_text(original_text, encoding="utf-8")
        suspect_path.write_text(suspect_text, encoding="utf-8")

        # 预热一次，避免把首次运行的模块导入、内存分配开销算进结果。
        run_pipeline(str(original_path), str(suspect_path), str(answer_path))

        # 不带 profiler 的真实耗时（cProfile 会给每一次函数调用加开销）。
        clean_elapsed = run_pipeline(
            str(original_path), str(suspect_path), str(answer_path)
        )
        profiler = cProfile.Profile()
        profiler.enable()
        elapsed = run_pipeline(str(original_path), str(suspect_path), str(answer_path))
        profiler.disable()
        answer = answer_path.read_text(encoding="utf-8").strip()

    stats = pstats.Stats(profiler)
    stats.sort_stats("cumulative")
    output = [
        f"语料规模：{size:,} 字符 × 2 个文件",
        f"真实耗时（不带 profiler）：{clean_elapsed:.3f} 秒",
        f"带 cProfile 的耗时：{elapsed:.3f} 秒（cProfile 会放大耗时，仅用于定位瓶颈）",
        f"答案文件内容：{answer}",
        "",
        "函数耗时排名：",
    ]
    buffer = io.StringIO()
    stats.stream = buffer
    stats.sort_stats("cumulative").print_stats(14)
    stats.sort_stats("tottime").print_stats(10)
    output.append(buffer.getvalue())

    report = "\n".join(output)
    print(report)
    STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATS_PATH.write_text(report + "\n", encoding="utf-8")

    entries: list[tuple[str, float]] = []
    for (filename, lineno, name), data in stats.stats.items():
        if "plagiarism" not in filename:
            continue
        entries.append((f"{Path(filename).name}:{lineno}({name})", data[3]))
    entries.sort(key=lambda item: item[1], reverse=True)
    write_bar_chart(CHART_PATH, entries[:10], stats.total_tt)

    # 同时导出一份 JSON，便于用其他工具（Excel、PowerPoint、博客编辑器）
    # 重新绘制同一份数据，保证图表与文字里的数字永远一致。
    data_path = PROJECT_ROOT / "docs" / "profile_data.json"
    data_path.write_text(
        json.dumps(
            {
                "title": (
                    f"cProfile 累计耗时（总 {stats.total_tt:.3f} 秒，"
                    f"{platform.python_implementation()} "
                    f"{platform.python_version()}）"
                ),
                "total_seconds": stats.total_tt,
                "clean_elapsed_seconds": clean_elapsed,
                "entries": [
                    {"function": name, "cumulative_seconds": value}
                    for name, value in entries[:10]
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n性能分析图已生成：{CHART_PATH}")
    print(f"性能分析数据已导出：{data_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
