"""异常定义模块。

本模块集中定义论文查重程序可能抛出的全部异常，它们都继承自
``PlagiarismCheckError``，因此调用方既可以选择"逐个异常精确处理"
（例如给出一句面向用户的提示），也可以在 ``main`` 里统一兜底，
避免程序因为未捕获异常而"异常退出"（评测规则中每条 -2 分）。

每个异常类都通过 ``exit_code`` 声明自己对应的进程返回码：

* ``0``  正常结束（不抛异常）
* ``1``  未预期的内部错误
* ``2``  命令行参数错误
* ``3``  文件读写/解码错误

这样做的好处是：``main`` 函数不需要写一长串 ``except`` 分支，
只依靠多态即可得到正确的返回码。
"""

from __future__ import annotations


class PlagiarismCheckError(Exception):
    """查重程序所有自定义异常的基类。

    :param message: 面向用户的错误描述。
    :param detail:  可选的补充信息（例如底层异常的文本），
                    用于在 ``--verbose`` 模式下打印更详细的诊断信息。
    """

    exit_code = 1

    def __init__(self, message: str, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail

    def __str__(self) -> str:  # pragma: no cover - 仅影响展示
        if self.detail:
            return f"{self.message}（{self.detail}）"
        return self.message


class InvalidArgumentError(PlagiarismCheckError):
    """命令行参数不合法。

    设计目标：把"参数个数不对""路径为空""答案文件与输入文件相同"
    等用法错误与文件系统错误区分开，便于用户快速定位问题。
    """

    exit_code = 2


class FileAccessError(PlagiarismCheckError):
    """文件相关错误的基类（读取、解码、写出）。"""

    exit_code = 3


class SourceFileMissingError(FileAccessError):
    """传入的文件路径不存在。"""


class PathIsDirectoryError(FileAccessError):
    """传入的路径是一个目录，而不是文件。"""


class FileNotReadableError(FileAccessError):
    """文件存在但无法读取（权限不足、被独占锁定等）。"""


class TextDecodingError(FileAccessError):
    """所有候选编码都无法解码文件内容。

    设计目标：避免"用错误编码强行解码"得到乱码文本，从而算出
    一个看似合理却完全错误的重复率。
    """


class OutputWriteError(FileAccessError):
    """答案文件无法写出（目录不存在、无写权限、目标被占用等）。"""

