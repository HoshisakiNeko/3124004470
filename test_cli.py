"""命令行入口与端到端流程的单元测试。

测试思路：直接调用 :func:`plagiarism.cli.main`（等价于
``python main.py ...``）并断言"返回码 + 答案文件内容"，
避免启动子进程，测试更快也更稳定。

覆盖的场景：

* 正常参数（默认/百分数/其他指标）；
* 参数个数错误、帮助、ngram 非法、答案文件与输入文件相同；
* 文件不存在、答案目录不存在（异常处理分支）；
* 输出格式（两位小数 + 结尾换行）、安静模式、明细模式；
* 只读写指定的三个文件（安全性要求）；
* 大文本（约 20 万字符）的运行时间远小于评测要求的 5 秒。
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from plagiarism.cli import (
    Settings,
    configure_console,
    format_score,
    main,
    parse_args,
)
from plagiarism.errors import InvalidArgumentError, OutputWriteError

ORIGINAL = (
    "论文查重是高校教学管理中一项重要的工作。随着信息技术的普及，"
    "学生提交的课程论文数量逐年增长，教师依靠人工阅读来判断论文是否存在抄袭。"
)
COPY = (
    "论文查重是高校教学管理中一项重要的工作。随着信息技术的普及，"
    "学生提交的课程论文数量逐年增加，教师依靠人工阅读来判断论文是不是存在抄袭。"
)


class CliTestCase(unittest.TestCase):
    """准备临时目录中的原文/抄袭版文件，并封装一次完整的命令行调用。"""

    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        self.temp_path = Path(self._temp_dir.name)
        self.original = self._write("orig.txt", ORIGINAL)
        self.suspect = self._write("orig_add.txt", COPY)
        self.answer = str(self.temp_path / "ans.txt")

    def _write(self, name: str, text: str, encoding: str = "utf-8") -> str:
        path = self.temp_path / name
        with open(path, "w", encoding=encoding, newline="\n") as handle:
            handle.write(text)
        return str(path)

    def invoke(self, *arguments: str) -> tuple[int, str, str]:
        """调用命令行入口，返回 (返回码, 标准输出, 标准错误)。"""
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(list(arguments))
        return code, stdout.getvalue(), stderr.getvalue()

    def read_answer(self) -> str:
        with open(self.answer, encoding="utf-8") as handle:
            return handle.read()

    def invoke_without_stdout_redirect(self, *arguments: str) -> tuple[int, str, str]:
        """只重定向标准错误流，标准输出交给调用方自己准备。

        测试"标准输出编码受限"的场景时不能再用 ``io.StringIO`` 覆盖
        ``sys.stdout``（StringIO 没有编码问题，测不出真实缺陷）。
        """
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = main(list(arguments))
        return code, "", stderr.getvalue()


class SuccessPathTests(CliTestCase):
    def test_end_to_end_writes_two_decimal_score(self) -> None:
        """正常调用应返回 0，答案文件只包含两位小数的浮点数。"""
        code, stdout, _ = self.invoke(self.original, self.suspect, self.answer)
        self.assertEqual(code, 0)
        answer = self.read_answer()
        self.assertRegex(answer, r"^\d\.\d{2}\n$")
        self.assertIn(answer.strip(), stdout)

    def test_identical_files_score_one(self) -> None:
        """完全相同的文件，答案应为 1.00。"""
        code, _, _ = self.invoke(self.original, self.original, self.answer)
        self.assertEqual(code, 0)
        self.assertEqual(self.read_answer(), "1.00\n")

    def test_score_is_reproducible(self) -> None:
        """同一组输入多次运行必须得到完全相同的答案（可复现）。"""
        self.invoke(self.original, self.suspect, self.answer)
        first = self.read_answer()
        self.invoke(self.original, self.suspect, self.answer)
        self.assertEqual(first, self.read_answer())

    def test_percent_mode_outputs_percentage(self) -> None:
        """--percent 时应输出百分数，仍然保留两位小数。"""
        code, _, _ = self.invoke(self.original, self.suspect, self.answer, "--percent")
        self.assertEqual(code, 0)
        value = float(self.read_answer())
        self.assertGreater(value, 50.0)
        self.assertLessEqual(value, 100.0)

    def test_metric_option_changes_result(self) -> None:
        """--metric 切换指标后，结果应随之变化（说明参数确实生效）。"""
        self.invoke(self.original, self.suspect, self.answer)
        cosine_answer = self.read_answer()
        self.invoke(self.original, self.suspect, self.answer, "--metric", "jaccard")
        jaccard_answer = self.read_answer()
        self.assertNotEqual(cosine_answer, jaccard_answer)

    def test_ngram_option_is_applied(self) -> None:
        """--ngram 3 应使用三元组特征，结果与默认二元组不同。"""
        self.invoke(self.original, self.suspect, self.answer)
        default_answer = self.read_answer()
        self.invoke(self.original, self.suspect, self.answer, "--ngram", "3")
        self.assertNotEqual(default_answer, self.read_answer())

    def test_quiet_mode_suppresses_output(self) -> None:
        """--quiet 时标准输出应为空，但答案文件照常写出。"""
        code, stdout, stderr = self.invoke(
            self.original, self.suspect, self.answer, "--quiet"
        )
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        self.assertRegex(self.read_answer(), r"^\d\.\d{2}\n$")

    def test_verbose_mode_prints_details_to_stderr(self) -> None:
        """--verbose 时明细写在标准错误流，不污染标准输出。"""
        code, stdout, stderr = self.invoke(
            self.original, self.suspect, self.answer, "--verbose"
        )
        self.assertEqual(code, 0)
        self.assertIn("明细", stderr)
        self.assertNotIn("明细", stdout)

    def test_ascii_console_does_not_break_the_program(self) -> None:
        """控制台不支持中文（ASCII 编码）时也不能异常退出，答案文件照常写出。

        对应真实风险：某些 IDE 或重定向环境下 ``sys.stdout.encoding`` 是
        ASCII，而程序默认会打印中文摘要，处理不当就会抛
        ``UnicodeEncodeError``，评测时表现为"异常退出"。
        """
        buffer = io.BytesIO()
        ascii_stdout = io.TextIOWrapper(buffer, encoding="ascii", errors="strict")
        self.addCleanup(ascii_stdout.close)
        self.invoke(self.original, self.suspect, self.answer)
        expected_answer = self.read_answer()
        with contextlib.redirect_stdout(ascii_stdout):
            code, _, _ = self.invoke_without_stdout_redirect(
                self.original, self.suspect, self.answer
            )
        ascii_stdout.flush()
        self.assertEqual(code, 0)
        self.assertEqual(self.read_answer(), expected_answer)

    def test_only_the_three_given_files_are_touched(self) -> None:
        """程序只应读写命令行给出的三个文件，不在目录里留下其他文件。"""
        before = sorted(p.name for p in self.temp_path.iterdir())
        self.invoke(self.original, self.suspect, self.answer)
        after = sorted(p.name for p in self.temp_path.iterdir())
        self.assertEqual(after, sorted(before + ["ans.txt"]))

    def test_large_input_finishes_well_within_time_limit(self) -> None:
        """约 20 万字符的输入应在 5 秒评测上限内完成（留出充足余量）。"""
        big_original = self._write("big_orig.txt", ORIGINAL * 2000)
        big_suspect = self._write("big_add.txt", COPY * 2000)
        started = time.perf_counter()
        code, _, _ = self.invoke(big_original, big_suspect, self.answer)
        elapsed = time.perf_counter() - started
        self.assertEqual(code, 0)
        self.assertLess(elapsed, 5.0)


class ArgumentErrorTests(CliTestCase):
    def test_missing_arguments_return_code_two(self) -> None:
        """参数个数不足时应返回 2，并在标准错误流给出用法提示。"""
        for arguments in ([], [self.original], [self.original, self.suspect]):
            with self.subTest(arguments=arguments):
                code, _, stderr = self.invoke(*arguments)
                self.assertEqual(code, 2)
                self.assertIn("用法", stderr)

    def test_extra_arguments_return_code_two(self) -> None:
        """给出多余的位置参数时报参数错误，而不是被静默忽略。"""
        code, _, stderr = self.invoke(
            self.original, self.suspect, self.answer, "extra.txt"
        )
        self.assertEqual(code, 2)
        self.assertIn("参数错误", stderr)

    def test_answer_path_equal_to_input_is_rejected(self) -> None:
        """答案文件与输入文件相同时必须先报错，避免破坏原始数据。"""
        code, _, stderr = self.invoke(self.original, self.suspect, self.original)
        self.assertEqual(code, 2)
        self.assertIn("参数错误", stderr)

    def test_invalid_ngram_is_rejected(self) -> None:
        """--ngram 0 属于非法参数，应在写文件之前被拦截。"""
        code, _, stderr = self.invoke(
            self.original, self.suspect, self.answer, "--ngram", "0"
        )
        self.assertEqual(code, 2)
        self.assertIn("--ngram", stderr)
        self.assertFalse(os.path.exists(self.answer))

    def test_help_returns_zero(self) -> None:
        """--help 属于正常请求：用法写在标准输出，返回码为 0。"""
        code, stdout, stderr = self.invoke("--help")
        self.assertEqual(code, 0)
        self.assertIn("main.py", stdout)
        self.assertEqual(stderr, "")

    def test_parse_args_defaults(self) -> None:
        """不传可选参数时，默认使用二元组 + 余弦相似度。"""
        settings = parse_args([self.original, self.suspect, self.answer])
        self.assertEqual(settings.ngram, 2)
        self.assertEqual(settings.metric, "cosine")
        self.assertFalse(settings.percent)
        self.assertIsInstance(settings, Settings)

    def test_parse_args_rejects_unknown_option(self) -> None:
        """未知选项应转换成 InvalidArgumentError，而不是让 argparse 直接退出。"""
        # argparse 会先把用法信息写到标准错误流，这里一并屏蔽掉。
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(InvalidArgumentError):
                parse_args([self.original, self.suspect, self.answer, "--nope"])

    def test_parse_args_reports_help_request(self) -> None:
        """parse_args 遇到 -h/--help 时用 InvalidArgumentError 传递用法说明。

        命令行层（main）会在此之前拦截帮助请求并正常退出，
        因此这里测的是"直接调用 API"时的约定，防止该分支无人覆盖。
        """
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(InvalidArgumentError) as context:
                parse_args(["-h"])
        self.assertIn("main.py", str(context.exception.detail))


class FileErrorTests(CliTestCase):
    def test_missing_input_file_returns_code_three(self) -> None:
        """原文文件不存在时返回 3，并给出可读的错误说明。"""
        code, _, stderr = self.invoke(
            str(self.temp_path / "missing.txt"), self.suspect, self.answer
        )
        self.assertEqual(code, 3)
        self.assertIn("运行失败", stderr)

    def test_directory_as_input_returns_code_three(self) -> None:
        """把目录当文件传入时返回 3，而不是抛出未捕获异常。"""
        code, _, stderr = self.invoke(
            str(self.temp_path), self.suspect, self.answer
        )
        self.assertEqual(code, 3)
        self.assertIn("目录", stderr)

    def test_output_directory_missing_returns_code_three(self) -> None:
        """答案文件所在目录不存在时返回 3（程序不擅自创建目录）。"""
        code, _, stderr = self.invoke(
            self.original, self.suspect, str(self.temp_path / "no-such-dir" / "ans.txt")
        )
        self.assertEqual(code, 3)
        self.assertIn("写入失败", stderr)

    def test_write_answer_translates_oserror(self) -> None:
        """write_answer 内部把 OSError 翻译成 OutputWriteError（白盒）。"""
        from plagiarism.cli import write_answer

        with self.assertRaises(OutputWriteError):
            write_answer(str(self.temp_path / "no-such-dir" / "ans.txt"), 0.5)

    def test_undecodable_input_returns_code_three(self) -> None:
        """输入文件无法解码时返回 3，避免拿乱码算出一个假分数。"""
        binary = self.temp_path / "binary.bin"
        binary.write_bytes(b"\xff\xff\xff")
        code, _, stderr = self.invoke(str(binary), self.suspect, self.answer)
        self.assertEqual(code, 3)
        self.assertIn("无法解码", stderr)

    def test_unexpected_error_returns_code_one(self) -> None:
        """最后一道防线：任何未预期异常都转成返回码 1，绝不"异常退出"。"""
        with mock.patch("plagiarism.cli.run", side_effect=RuntimeError("内部故障")):
            code, _, stderr = self.invoke(self.original, self.suspect, self.answer)
        self.assertEqual(code, 1)
        self.assertIn("未预期的内部错误", stderr)


class FormattingTests(unittest.TestCase):
    def test_format_score_keeps_two_decimals(self) -> None:
        """格式化结果始终保留两位小数（含进位与补零两种边界）。

        注意：0.855 这类十进制小数无法用二进制浮点精确表示，
        ``format`` 使用"四舍六入五取偶"规则，因此这里选用
        0.856 这类不会有歧义的取值做断言。
        """
        self.assertEqual(format_score(0.0), "0.00")
        self.assertEqual(format_score(1.0), "1.00")
        self.assertEqual(format_score(0.2), "0.20")
        self.assertEqual(format_score(0.856), "0.86")
        self.assertEqual(format_score(0.1234, percent=True), "12.34")

    def test_configure_console_tolerates_failure(self) -> None:
        """极端环境下 reconfigure 失败也不能让程序崩溃（防御性分支）。"""
        broken_stream = mock.Mock()
        broken_stream.reconfigure.side_effect = ValueError("该流不支持重配置")
        with mock.patch.object(sys, "stdout", broken_stream), mock.patch.object(
            sys, "stderr", broken_stream
        ):
            configure_console()  # 不应抛出异常
        self.assertEqual(broken_stream.reconfigure.call_count, 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
