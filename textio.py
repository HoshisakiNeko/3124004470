"""文本读取与归一化模块。

这一层负责把"磁盘上的任意字节流"变成"干净的字符序列"，为后面的
相似度计算提供统一的输入：

1. ``read_text``   —— 自动尝试多种编码（UTF-8 / UTF-16 / GB18030 / Big5），
                     并把路径错误、权限错误、解码失败翻译成自定义异常。
2. ``normalize_text`` —— 全角转半角、统一大小写、去掉空白与标点，
                     使"格式差异"不会被误判为"内容差异"。

归一化只使用标准库（``unicodedata`` + ``re``），两者底层均由 C 实现，
比在 Python 层逐字符判断快一个数量级。
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Tuple

from .errors import (
    FileNotReadableError,
    PathIsDirectoryError,
    SourceFileMissingError,
    TextDecodingError,
)

#: 候选编码列表，按"实际出现概率"从高到低排列。
#: * ``utf-8-sig`` 同时兼容带 BOM 与不带 BOM 的 UTF-8；
#: * ``utf-16`` 依赖 BOM，没有 BOM 时会直接解码失败，不会误判；
#: * ``gb18030`` 是 GB2312/GBK 的超集，覆盖简体中文常见编码；
#: * ``big5`` 覆盖繁体中文常见编码。
ENCODING_CANDIDATES: Tuple[str, ...] = ("utf-8-sig", "utf-16", "gb18030", "big5")

#: 保留"字母、数字、汉字等文字类字符"，删除其余字符（空白、标点、下划线）。
#: ``\w`` 在 Python 3 中默认按 Unicode 语义匹配，汉字属于 ``\w``。
_NOISE_PATTERN = re.compile(r"[\W_]+", re.UNICODE)


def read_text(path: str) -> Tuple[str, str]:
    """读取文本文件并返回 ``(文本, 实际使用的编码)``。

    抛出 :class:`SourceFileMissingError`、:class:`PathIsDirectoryError`、
    :class:`FileNotReadableError` 或 :class:`TextDecodingError`。
    """
    file_path = Path(path)
    if file_path.is_dir():
        raise PathIsDirectoryError(f"路径是一个目录而不是文件：{path}")
    if not file_path.exists():
        raise SourceFileMissingError(f"文件不存在：{path}")

    try:
        data = file_path.read_bytes()
    except PermissionError as exc:  # 权限不足
        raise FileNotReadableError(f"没有读取权限：{path}", str(exc)) from exc
    except OSError as exc:  # 磁盘错误、文件被占用等
        raise FileNotReadableError(f"读取文件失败：{path}", str(exc)) from exc

    if not data:  # 空文件：视为空文本，由调用方决定语义
        return "", "empty"

    for encoding in ENCODING_CANDIDATES:
        try:
            return data.decode(encoding), encoding
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise TextDecodingError(
        f"无法解码文件内容：{path}",
        "已尝试编码：" + "、".join(ENCODING_CANDIDATES),
    )


def normalize_text(raw_text: str) -> str:
    """把原始文本归一化为"只含文字字符"的紧凑字符串。

    处理步骤：

    1. ``NFKC`` 兼容性归一化：全角字符转半角（"Ａ"→"A"、"１"→"1"）；
    2. ``casefold`` 统一大小写（"Windows"→"windows"）；
    3. 删除所有非文字字符：空格、换行、制表符、中英文标点、下划线等。

    空白与标点的差异不应影响查重结论，因此在这里一次性剔除。
    """
    if not raw_text:
        return ""
    normalized = unicodedata.normalize("NFKC", raw_text).casefold()
    return _NOISE_PATTERN.sub("", normalized)

