"""相似度计算模块（本程序的核心计算模块）。

算法总览
--------
1. **切分**：把归一化后的文本切成重叠的字符 n-gram（默认 ``n=2``，即
   "字符二元组"）。中文没有天然的词边界，使用字符 n-gram 可以完全
   避免引入分词词典，也就避免了额外的依赖和词典带来的误差。
2. **向量化**：统计每个 n-gram 的出现次数，得到稀疏词频向量
   ``Counter[int, int]``。为了节省内存，n-gram 被编码成整数而不去
   真的拼接子字符串：码点小于 ``2**21``，因此二元组可用
   ``(左码点 << 21) | 右码点`` 精确编码，不会产生哈希冲突。
3. **度量**：默认用余弦相似度衡量两个稀疏向量的夹角
   ``dot(a, b) / (|a| * |b|)``，结果落在 ``[0, 1]`` 区间。

为什么选余弦相似度：它对文本长度不敏感（把同一篇文章节选一半，
向量方向几乎不变），对局部的增删改只有平缓的惩罚，正好对应
"抄袭版 = 原文 + 增删改"的场景；计算时只需遍历较小的那个稀疏向量，
复杂度为 ``O(|A| + |B|)``。

性能要点（详见 ``docs`` 目录下的性能分析报告）：

* 用 ``array("I") + utf-32-le`` 一次性取出码点，避免逐字符 ``ord()``；
* 二元组用 ``map(map(lshift), islice)`` 组合，让计数循环留在 C 层；
* 直接用 ``Counter`` 存放结果，不再复制成普通 dict；
* 点积只遍历较小的向量，并把 ``Counter.get`` 提前绑定为局部变量。
"""

from __future__ import annotations

import math
from array import array
from collections import Counter
from itertools import islice, repeat
from operator import lshift, mul, or_
from typing import Iterator, Mapping

#: 默认的 n-gram 长度：字符二元组。
DEFAULT_NGRAM: int = 2

#: 词频向量的类型：n-gram 的整数编码 -> 出现次数。
ShingleCounts = Mapping[int, int]

_MASK64 = (1 << 64) - 1
_HASH_BASE = 0x1000193
_CODEPOINT_BITS = 21  # Unicode 码点最大值 0x10FFFF 需要 21 位


def _to_codepoints(text: str) -> array:
    """把字符串一次性转换成码点数组（C 层完成，无需逐字符调用 ``ord``）。"""
    codepoints = array("I")
    codepoints.frombytes(text.encode("utf-32-le"))
    return codepoints


def _polynomial_keys(codepoints: array, ngram: int) -> Iterator[int]:
    """``n >= 3`` 时用 64 位滚动多项式哈希把窗口压缩成整数键。"""
    size = len(codepoints)
    prefix = [0] * (size + 1)
    rolling = 0
    for index, code in enumerate(codepoints):
        rolling = (rolling * _HASH_BASE + code) & _MASK64
        prefix[index + 1] = rolling
    high = pow(_HASH_BASE, ngram, 1 << 64)
    for start in range(size - ngram + 1):
        yield (prefix[start + ngram] - prefix[start] * high) & _MASK64


def iter_shingle_keys(codepoints: array, ngram: int) -> Iterator[int]:
    """返回 n-gram 整数键的迭代器（惰性，不生成任何中间字符串）。

    ``ngram`` 为 1、2 时直接返回 C 层实现的迭代器（``iter`` / ``map``），
    因此 ``Counter`` 能以接近 C 的速度完成计数；``ngram >= 3`` 时才退回
    生成器实现。
    """
    if ngram <= 1:
        return iter(codepoints)
    if ngram == 2:
        # 热点路径：位移与按位或由 C 函数完成，避免 Python 层逐项循环。
        return map(
            or_,
            map(lshift, codepoints, repeat(_CODEPOINT_BITS)),
            islice(codepoints, 1, None),
        )
    return _polynomial_keys(codepoints, ngram)


def count_shingles(text: str, ngram: int = DEFAULT_NGRAM) -> ShingleCounts:
    """统计 ``text`` 中所有 n-gram 的出现次数。

    ``ngram`` 会自动收缩到文本长度（例如单字文本退化为字符频率对比），
    保证短文本也有定义良好的结果，而不是返回空向量。
    """
    if not text:
        return {}
    if ngram < 1:
        raise ValueError("ngram 必须是不小于 1 的整数")
    effective = min(ngram, len(text))
    # Counter 本身就是 dict 的子类，直接返回即可，无需再复制一次。
    return Counter(iter_shingle_keys(_to_codepoints(text), effective))


def _l2_norm(counts: ShingleCounts) -> float:
    """稀疏向量的 L2 范数。

    ``sum(map(mul, values, values))`` 把"求平方和"的循环留在 C 层，
    比生成器表达式快一倍左右（实测 95 万个特征：0.065s → 0.033s）。
    """
    return math.sqrt(sum(map(mul, counts.values(), counts.values())))


def cosine_similarity(left: ShingleCounts, right: ShingleCounts) -> float:
    """词频向量余弦相似度，返回 ``[0, 1]`` 的浮点数。"""
    if not left or not right:
        return 0.0
    # 只遍历元素较少的向量做点积，减少字典查找次数。
    if len(left) > len(right):
        left, right = right, left
    lookup = right.get
    dot = 0
    for key, value in left.items():
        other = lookup(key)
        if other is not None:
            dot += value * other
    if dot == 0:
        return 0.0
    # dot != 0 说明两个向量都含有非零分量，分母必然大于 0。
    denominator = _l2_norm(left) * _l2_norm(right)
    return min(1.0, dot / denominator)


def jaccard_similarity(left: ShingleCounts, right: ShingleCounts) -> float:
    """集合 Jaccard 相似度 ``|A∩B| / |A∪B|``（忽略出现次数）。

    作为扩展指标提供：它对"同一个片段重复出现几次"不敏感，
    适合衡量用词集合的重合程度，可与默认指标互相印证。
    """
    if not left or not right:
        return 0.0
    if len(left) > len(right):
        left, right = right, left
    intersection = sum(1 for key in left if key in right)
    # 两个向量都非空，因此并集大小一定大于 0。
    union = len(left) + len(right) - intersection
    return intersection / union


def containment_ratio(left: ShingleCounts, right: ShingleCounts) -> float:
    """包含率：较小的向量有多大比例被较大的向量覆盖。

    适用于"原文 + 大段新增内容"这种抄袭方式：此时余弦相似度会因为
    篇幅变长而下降，而包含率仍然接近 1。
    """
    if not left or not right:
        return 0.0
    if len(left) > len(right):
        left, right = right, left
    covered = sum(1 for key in left if key in right)
    return covered / len(left)


#: 指标注册表：命令行 ``--metric`` 的取值即此处的键。
METRICS = {
    "cosine": cosine_similarity,
    "jaccard": jaccard_similarity,
    "containment": containment_ratio,
}


def compare_texts(
    original: str,
    suspect: str,
    ngram: int = DEFAULT_NGRAM,
    metric: str = "cosine",
) -> float:
    """计算两段**已归一化**文本的重复率，返回 ``[0, 1]`` 的浮点数。

    快速路径：两侧完全相同（含都为空）时直接返回 ``1.0``；任一侧为空
    时返回 ``0.0``，既符合直觉，也避免无意义的向量运算。
    """
    if original == suspect:
        return 1.0
    if not original or not suspect:
        return 0.0
    try:
        metric_function = METRICS[metric]
    except KeyError as exc:  # pragma: no cover - 命令行层已校验取值范围
        raise ValueError(f"未知的相似度指标：{metric}") from exc

    # 两个文本必须使用同一个 ngram 长度，过短的文本会自动收缩。
    effective = max(1, min(ngram, len(original), len(suspect)))
    return metric_function(
        count_shingles(original, effective),
        count_shingles(suspect, effective),
    )
