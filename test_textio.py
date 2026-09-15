"""文本读取与归一化模块的单元测试。

测试思路（白盒为主）：

* 覆盖 :func:`plagiarism.textio.read_text` 的每条分支：目录、文件不存在、
  空文件、UTF-8(BOM)、UTF-16、GB18030、全部编码失败；
* 覆盖 :func:`plagiarism.textio.normalize_text` 的全角转半角、
  大小写统一、标点与空白剔除。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from plagiarism.errors import (
    FileNotReadableError,
    PathIsDirectoryError,
    SourceFileMissingError,
    TextDecodingError,
)
from plagiarism.textio import normalize_text, read_text


class TempFileTestCase(unittest.TestCase):
    """提供临时目录与"按指定编码写文件"的辅助方法。"""

    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        self.temp_path = Path(self._temp_dir.name)

    def write_file(self, name: str, data: bytes) -> str:
        path = self.temp_path / name
        with open(path, "wb") as handle:
            handle.write(data)
        return str(path)


class ReadTextTests(TempFileTestCase):
    def test_read_utf8_with_bom(self) -> None:
        """带 BOM 的 UTF-8 文件应能正确读取，并报告 utf-8-sig 编码。"""
        path = self.write_file("bom.txt", "我的论文".encode("utf-8-sig"))
        text, encoding = read_text(path)
        self.assertEqual(text, "我的论文")
        self.assertEqual(encoding, "utf-8-sig")

    def test_read_gbk_file(self) -> None:
        """GB18030(GBK 超集) 编码的中文文件应能正确读取，不出现乱码。"""
        path = self.write_file("gbk.txt", "论文查重实验".encode("gb18030"))
        text, encoding = read_text(path)
        self.assertEqual(text, "论文查重实验")
        self.assertEqual(encoding, "gb18030")

    def test_read_utf16_file(self) -> None:
        """UTF-16(带 BOM) 文件应能在 UTF-8 解码失败后自动回退成功。"""
        path = self.write_file("utf16.txt", "编码自动识别".encode("utf-16"))
        text, encoding = read_text(path)
        self.assertEqual(text, "编码自动识别")
        self.assertEqual(encoding, "utf-16")

    def test_read_empty_file_returns_empty_text(self) -> None:
        """空文件不算错误：返回空文本，由上层决定重复率为 0。"""
        path = self.write_file("empty.txt", b"")
        text, encoding = read_text(path)
        self.assertEqual(text, "")
        self.assertEqual(encoding, "empty")

    def test_read_missing_file_raises(self) -> None:
        """文件不存在时抛出 SourceFileMissingError（对应退出码 3）。"""
        missing = str(self.temp_path / "not-exists.txt")
        with self.assertRaises(SourceFileMissingError):
            read_text(missing)

    def test_read_directory_raises(self) -> None:
        """路径是目录时抛出 PathIsDirectoryError，而不是把目录当文件打开。"""
        with self.assertRaises(PathIsDirectoryError):
            read_text(str(self.temp_path))

    def test_read_undecodable_bytes_raises(self) -> None:
        """四种候选编码都失败时抛出 TextDecodingError，避免输出乱码文本。"""
        path = self.write_file("binary.bin", b"\xff\xff\xff")
        with self.assertRaises(TextDecodingError):
            read_text(path)

    def test_read_permission_denied_is_translated(self) -> None:
        """权限不足时翻译成 FileNotReadableError（用 mock 触发该分支）。"""
        path = self.write_file("locked.txt", "论文查重".encode("utf-8"))
        with mock.patch.object(
            Path, "read_bytes", side_effect=PermissionError("拒绝访问")
        ):
            with self.assertRaises(FileNotReadableError) as context:
                read_text(path)
        self.assertIn("没有读取权限", context.exception.message)

    def test_read_os_error_is_translated(self) -> None:
        """其他磁盘错误同样翻译成 FileNotReadableError，避免异常退出。"""
        path = self.write_file("broken.txt", "论文查重".encode("utf-8"))
        with mock.patch.object(Path, "read_bytes", side_effect=OSError("设备不可用")):
            with self.assertRaises(FileNotReadableError) as context:
                read_text(path)
        self.assertIn("读取文件失败", context.exception.message)


class NormalizeTextTests(unittest.TestCase):
    def test_normalize_removes_punctuation_and_whitespace(self) -> None:
        """中英文标点、空格、换行都应被剔除，只留下文字字符。"""
        self.assertEqual(
            normalize_text("今天 是星期天，\n天气晴。\t"),
            "今天是星期天天气晴",
        )

    def test_normalize_converts_fullwidth_and_case(self) -> None:
        """全角字符转半角、大小写统一，使格式差异不影响查重结论。"""
        self.assertEqual(normalize_text("Ｗｉｎｄｏｗｓ１０"), "windows10")
        self.assertEqual(normalize_text("Hello WORLD"), "helloworld")

    def test_normalize_keeps_digits_and_chinese(self) -> None:
        """汉字与数字都应保留，保证相似度计算有充分的特征。"""
        self.assertEqual(normalize_text("图 3-1 所示"), "图31所示")

    def test_normalize_empty_input(self) -> None:
        """空串应返回空串，不抛异常（空文本是合法的输入）。"""
        self.assertEqual(normalize_text(""), "")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
