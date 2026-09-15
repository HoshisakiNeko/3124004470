"""异常体系的单元测试。

设计目标：确认每种异常都携带正确的进程返回码，并且都属于
``PlagiarismCheckError`` 这一基类——这样 ``main`` 只需要捕获基类
就能保证"任何已知错误都不会导致程序异常退出"。
"""

from __future__ import annotations

import unittest

from plagiarism.errors import (
    FileAccessError,
    FileNotReadableError,
    InvalidArgumentError,
    OutputWriteError,
    PathIsDirectoryError,
    PlagiarismCheckError,
    SourceFileMissingError,
    TextDecodingError,
)


class ExceptionHierarchyTests(unittest.TestCase):
    def test_all_errors_share_common_base(self) -> None:
        """所有自定义异常都必须继承自 PlagiarismCheckError（便于统一兜底）。"""
        for exception_type in (
            InvalidArgumentError,
            FileAccessError,
            SourceFileMissingError,
            PathIsDirectoryError,
            FileNotReadableError,
            TextDecodingError,
            OutputWriteError,
        ):
            with self.subTest(exception=exception_type.__name__):
                self.assertTrue(issubclass(exception_type, PlagiarismCheckError))

    def test_file_errors_share_file_base(self) -> None:
        """文件类异常统一继承 FileAccessError，返回码为 3。"""
        for exception_type in (
            SourceFileMissingError,
            PathIsDirectoryError,
            FileNotReadableError,
            TextDecodingError,
            OutputWriteError,
        ):
            with self.subTest(exception=exception_type.__name__):
                self.assertTrue(issubclass(exception_type, FileAccessError))
                self.assertEqual(exception_type.exit_code, 3)

    def test_argument_error_exit_code_is_two(self) -> None:
        """参数错误的返回码是 2，与文件错误（3）区分开。"""
        self.assertEqual(InvalidArgumentError.exit_code, 2)
        self.assertEqual(PlagiarismCheckError.exit_code, 1)

    def test_message_and_detail_are_kept(self) -> None:
        """异常对象保留 message 与 detail，便于 verbose 模式输出诊断信息。"""
        error = TextDecodingError("无法解码文件内容", "已尝试编码：utf-8")
        self.assertEqual(error.message, "无法解码文件内容")
        self.assertEqual(error.detail, "已尝试编码：utf-8")
        self.assertIn("已尝试编码", str(error))

    def test_detail_is_optional(self) -> None:
        """detail 缺省时字符串形式就是 message 本身。"""
        error = SourceFileMissingError("文件不存在：a.txt")
        self.assertEqual(str(error), "文件不存在：a.txt")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
