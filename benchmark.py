"""对比三代实现的耗时与内存，量化"性能改进"的效果。

三代实现（思路见 docs 目录下的性能分析说明）：

* **v1 朴素版**：``text[i:i+2]`` 拼出字符串再手工累加 dict；
* **v2 整数键版**：整数编码 n-gram，但用"生成器表达式 + dict 复制"；
* **v3 当前版**：``array('I') + utf-32-le`` 取码点，``map/operator``
  留在 C 层计数，``Counter`` 直接作为结果返回，L2 范数用 ``map(mul)``。

用法（在项目根目录执行）::

    python tools/benchmark.py [文本字符数]
"""

from __future__ import annotations

import gc
import sys
import time
import tracemalloc
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from plagiarism.similarity import count_shingles  # noqa: E402

DEFAULT_CHARS = 1_000_000
REPORT_PATH = PROJECT_ROOT / "docs" / "benchmark.txt"


def make_text(size: int) -> str:
    """构造特征尽量分散的文本（大量不同的二元组），模拟真实论文。"""
    import random

    rng = random.Random(20240915)
    vocabulary = [chr(0x4E00 + index) for index in range(3000)]
    return "".join(rng.choice(vocabulary) for _ in range(size))


def count_v1(text: str) -> dict:
    """v1：字符串切片 + 手工字典累加。"""
    counts: dict = {}
    for index in range(len(text) - 1):
        key = text[index : index + 2]
        counts[key] = counts.get(key, 0) + 1
    return counts


def count_v2(text: str) -> dict:
    """v2：整数编码 + 生成器表达式 + 多余的 dict 复制。"""
    from array import array

    codepoints = array("I")
    codepoints.frombytes(text.encode("utf-32-le"))
    keys = ((left << 21) | right for left, right in zip(codepoints, codepoints[1:]))
    return dict(Counter(keys))


def count_v3(text: str) -> dict:
    """v3：当前实现（见 plagiarism.similarity.count_shingles）。"""
    return count_shingles(text)


def measure(function, text: str) -> tuple[float, float, int]:
    """返回 (耗时秒, 峰值内存 MB, 特征数)。

    耗时与内存分两轮测量：tracemalloc 会拦截每一次内存分配，
    用它测时间会严重失真（实测能把耗时放大 5~10 倍），
    因此第一轮关闭 tracemalloc 只测时间，第二轮才开 tracemalloc 测内存。
    """
    gc.collect()
    started = time.perf_counter()
    result = function(text)
    elapsed = time.perf_counter() - started
    features = len(result)
    del result

    gc.collect()
    tracemalloc.start()
    function(text)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return elapsed, peak / 2**20, features


def main() -> int:
    size = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CHARS
    text = make_text(size)
    lines = [
        f"语料规模：{size:,} 个字符（约 {size / 2**20:.1f} MB 的 UTF-8 中文文本）",
        "说明：tracemalloc 会放大耗时，因此下表的时间用于横向比较三种实现，"
        "不代表最终运行时间；最终运行时间见 profile_stats.txt。",
        "",
        f"{'实现':<16}{'耗时(秒)':>10}{'峰值内存(MB)':>14}{'特征数':>10}",
        "-" * 52,
    ]
    baseline = None
    for name, function in (
        ("v1 字符串切片", count_v1),
        ("v2 整数键", count_v2),
        ("v3 当前实现", count_v3),
    ):
        elapsed, peak, features = measure(function, text)
        if baseline is None:
            baseline = elapsed
        speedup = baseline / elapsed
        lines.append(
            f"{name:<16}{elapsed:>10.3f}{peak:>14.1f}{features:>10,}"
            f"   相对 v1 提速 {speedup:.2f}×"
        )

    report = "\n".join(lines)
    print(report)
    (PROJECT_ROOT / "docs").mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
