"""相似度计算模块的单元测试（核心计算模块测试）。

测试思路：

* **白盒**：验证 n-gram 整数编码与朴素字符串实现完全等价（无哈希冲突）、
  余弦相似度与手工计算的点积/范数公式一致、短文本自动收缩 ngram；
* **黑盒**：输入"完全相同 / 完全不同 / 只改标点 / 增删改"等文本，
  检查输出是否落在符合直觉的区间，并满足对称性与单调性。
"""

from __future__ import annotations

import math
import random
import unittest
from collections import Counter

from plagiarism.similarity import (
    DEFAULT_NGRAM,
    METRICS,
    compare_texts,
    containment_ratio,
    cosine_similarity,
    count_shingles,
    jaccard_similarity,
)
from plagiarism.textio import normalize_text

ORIGINAL_SAMPLE = "今天是星期天，天气晴，今天晚上我要去看电影。"
PLAGIARISM_SAMPLE = "今天是周天，天气晴朗，我晚上要去看电影。"


def _naive_counts(text: str, ngram: int) -> Counter:
    """朴素实现：直接拼接子字符串计数，只用于对照验证。"""
    return Counter(text[i : i + ngram] for i in range(len(text) - ngram + 1))


class CountingTests(unittest.TestCase):
    def test_bigram_encoding_matches_naive_counting(self) -> None:
        """整数编码的 n-gram 数量必须与朴素字符串实现完全一致（无冲突）。"""
        text = normalize_text("数据 结构 与 算法，Data Structures & Algorithms 2024。")
        for ngram in (1, 2, 3, 4):
            with self.subTest(ngram=ngram):
                self.assertEqual(
                    len(count_shingles(text, ngram)),
                    len(_naive_counts(text, ngram)),
                )

    def test_count_shingles_frequencies_are_correct(self) -> None:
        """出现次数也应与朴素实现一致，而不仅仅是没有冲突。"""
        text = normalize_text("abcabc")
        counts = count_shingles(text, 2)
        naive = _naive_counts(text, 2)
        self.assertEqual(sorted(counts.values()), sorted(naive.values()))
        self.assertEqual(sum(counts.values()), len(text) - 1)

    def test_empty_text_has_no_shingles(self) -> None:
        """空文本的特征向量为空，对应重复率 0。"""
        self.assertEqual(count_shingles(""), {})

    def test_invalid_ngram_raises_value_error(self) -> None:
        """ngram < 1 属于调用方错误，应抛出 ValueError。"""
        with self.assertRaises(ValueError):
            count_shingles("论文查重", 0)


class CosineFormulaTests(unittest.TestCase):
    def test_cosine_matches_manual_formula(self) -> None:
        """余弦相似度必须等于按公式手工计算的结果（白盒验证）。"""
        left = count_shingles(normalize_text("论文查重算法实现"), 2)
        right = count_shingles(normalize_text("论文查重方法实现"), 2)
        keys = set(left) & set(right)
        dot = sum(left[key] * right[key] for key in keys)
        manual = dot / (
            math.sqrt(sum(v * v for v in left.values()))
            * math.sqrt(sum(v * v for v in right.values()))
        )
        self.assertAlmostEqual(cosine_similarity(left, right), manual, places=12)

    def test_cosine_is_symmetric(self) -> None:
        """交换两个输入的先后顺序，结果必须相同。"""
        left = count_shingles(normalize_text("软件工程 个人项目 论文查重"), 2)
        right = count_shingles(normalize_text("个人项目论文查重与性能优化"), 2)
        self.assertAlmostEqual(
            cosine_similarity(left, right),
            cosine_similarity(right, left),
            places=12,
        )

    def test_cosine_with_empty_vector_is_zero(self) -> None:
        """空向量与任何向量都没有方向可言，按约定返回 0。"""
        self.assertEqual(cosine_similarity({}, count_shingles("论文")), 0.0)
        self.assertEqual(cosine_similarity({}, {}), 0.0)

    def test_cosine_with_zero_weight_vector_is_zero(self) -> None:
        """向量非空但点积为 0（不存在公共特征）时也返回 0，而不是抛异常。"""
        self.assertEqual(cosine_similarity({1: 0}, {2: 5}), 0.0)


class CompareTextsTests(unittest.TestCase):
    def test_identical_texts_score_one(self) -> None:
        """完全相同的文本，重复率为 1。"""
        self.assertEqual(compare_texts("论文查重", "论文查重"), 1.0)

    def test_texts_without_common_features_score_zero(self) -> None:
        """完全没有共同二元组的文本，重复率为 0。"""
        self.assertEqual(compare_texts("数据库索引优化", "山河湖海风雨雷电"), 0.0)

    def test_punctuation_and_whitespace_do_not_matter(self) -> None:
        """标点、空格、换行的差异不应影响结论（归一化后完全相同）。"""
        left = normalize_text("今天是星期天，天气晴。")
        right = normalize_text("今天是星期天\n天气晴 ！")
        self.assertEqual(compare_texts(left, right), 1.0)

    def test_empty_input_scores_zero(self) -> None:
        """任一侧为空时按 0 处理，保证程序总能输出合法答案。"""
        self.assertEqual(compare_texts("", "论文查重"), 0.0)
        self.assertEqual(compare_texts("论文查重", ""), 0.0)
        self.assertEqual(compare_texts("", ""), 1.0)

    def test_single_character_text_uses_unigrams(self) -> None:
        """单字文本没有二元组，应自动退化为字符频率比较而不是崩溃/恒为 0。"""
        self.assertEqual(compare_texts("论", "论"), 1.0)
        self.assertEqual(compare_texts("论", "文"), 0.0)

    def test_sample_pair_from_statement_is_in_expected_range(self) -> None:
        """题目给出的样例（改词 + 调序）应落在"相似但不同"的区间。"""
        score = compare_texts(
            normalize_text(ORIGINAL_SAMPLE),
            normalize_text(PLAGIARISM_SAMPLE),
        )
        self.assertGreater(score, 0.4)
        self.assertLess(score, 0.8)

    def test_more_shared_content_scores_higher(self) -> None:
        """共享内容越多，重复率单调不降——保证结果具有可解释性。"""
        original = normalize_text("论文查重是软件工程课程的重要实验内容。")
        close = normalize_text("论文查重是软件工程课程的重要实验内容，需要认真完成。")
        far = normalize_text("论文查重与数据库索引优化没有直接关系。")
        self.assertGreater(
            compare_texts(original, close),
            compare_texts(original, far),
        )

    def test_scores_always_within_unit_interval(self) -> None:
        """随机文本对：余弦、Jaccard、包含率都必须落在 [0, 1]。"""
        rng = random.Random(20240915)
        alphabet = "论文查重算法性能测试abc123"
        for _ in range(30):
            left = normalize_text("".join(rng.choice(alphabet) for _ in range(40)))
            right = normalize_text("".join(rng.choice(alphabet) for _ in range(40)))
            for name, metric in METRICS.items():
                with self.subTest(metric=name):
                    score = compare_texts(left, right, DEFAULT_NGRAM, name)
                    self.assertGreaterEqual(score, 0.0)
                    self.assertLessEqual(score, 1.0)

    def test_unknown_metric_raises_value_error(self) -> None:
        """指标名拼写错误时应抛出 ValueError，而不是静默返回 0。"""
        with self.assertRaises(ValueError):
            compare_texts("论文查重", "论文查重实验", 2, "unknown-metric")


class MetricVariantTests(unittest.TestCase):
    def test_jaccard_matches_manual_set_formula(self) -> None:
        """Jaccard 指标应等于集合交集/并集（忽略出现次数）。"""
        left = count_shingles("abcdeabcde", 2)
        right = count_shingles("abcdexyz", 2)
        intersection = len(set(left) & set(right))
        union = len(set(left) | set(right))
        self.assertAlmostEqual(
            jaccard_similarity(left, right),
            intersection / union,
            places=12,
        )

    def test_containment_is_one_when_original_is_fully_contained(self) -> None:
        """抄袭版 = 原文 + 大段新增内容时，包含率应接近 1（扩展指标价值）。"""
        original = count_shingles("论文查重算法实现与测试", 2)
        extended = count_shingles("论文查重算法实现与测试，另外补充了异常处理说明。", 2)
        self.assertEqual(containment_ratio(original, extended), 1.0)
        self.assertLess(cosine_similarity(original, extended), 1.0)

    def test_variant_metrics_handle_empty_vectors(self) -> None:
        """空向量在 Jaccard / 包含率下同样返回 0，保证接口行为一致。"""
        features = count_shingles("论文查重", 2)
        self.assertEqual(jaccard_similarity({}, features), 0.0)
        self.assertEqual(jaccard_similarity(features, {}), 0.0)
        self.assertEqual(containment_ratio({}, {}), 0.0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
