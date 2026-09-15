"""命令行入口模块：解析参数 → 计算重复率 → 写出答案文件。

调用形式（与作业要求一致）：:

    python main.py <原文文件绝对路径> <抄袭版文件绝对路径> <答案文件绝对路径>

可选参数（不传时使用默认值，不影响作业的评测调用方式）：

* ``-n/--ngram``     n-gram 长度，默认 2；
* ``-m/--metric``    相似度指标：cosine（默认）/ jaccard / containment；
* ``--percent``      以百分数形式输出（例如 85.32 而不是 0.85）；
* ``-v/--verbose``  在标准错误流打印运行明细；
* ``-q/--quiet``    不打印结果摘要。

返回码：``0`` 正常，``2`` 参数错误，``3`` 文件错误，``1`` 其他未预期错误。
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass

from .errors import InvalidArgumentError, OutputWriteError, PlagiarismCheckError
from .similarity import DEFAULT_NGRAM, METRICS, compare_texts
from .textio import normalize_text, read_text

USAGE = "python main.py <原文文件> <抄袭版论文文件> <答案文件>"

#: 答案的默认格式开关：
#: ``False`` → 输出 0.00 ~ 1.00 的小数（本作业按"浮点型重复率"理解）；
#: ``True``  → 输出 0.00 ~ 100.00 的百分数。
#: 如果课堂说明答案要写成百分数，只需把这一行改成 True（或运行时加
#: ``--percent``），程序的其余部分不需要任何改动。
DEFAULT_PERCENT = False


@dataclass(frozen=True)
class Settings:
    """一次查重运行的全部输入参数。"""

    original_path: str
    suspect_path: str
    answer_path: str
    ngram: int = DEFAULT_NGRAM
    metric: str = "cosine"
    percent: bool = DEFAULT_PERCENT
    verbose: bool = False
    quiet: bool = False


@dataclass(frozen=True)
class Report:
    """一次查重运行的统计结果（用于 verbose 输出与单元测试断言）。"""

    score: float
    original_chars: int
    suspect_chars: int
    original_encoding: str
    suspect_encoding: str
    elapsed_seconds: float


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="论文查重：计算抄袭版论文与原文的重复率。",
        add_help=False,
        usage=USAGE,
    )
    parser.add_argument("original", nargs="?", help="原文文件路径")
    parser.add_argument("suspect", nargs="?", help="抄袭版论文文件路径")
    parser.add_argument("answer", nargs="?", help="答案文件路径")
    parser.add_argument("-n", "--ngram", type=int, default=DEFAULT_NGRAM)
    parser.add_argument("-m", "--metric", choices=sorted(METRICS), default="cosine")
    parser.add_argument("--percent", action="store_true", default=DEFAULT_PERCENT)
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("-q", "--quiet", action="store_true")
    parser.add_argument("-h", "--help", action="store_true")
    return parser


def parse_args(argv: list[str]) -> Settings:
    """把命令行参数解析成 :class:`Settings`。

    参数不足、多余、路径为空或答案文件与输入文件重合时，
    统一抛出 :class:`InvalidArgumentError`。
    """
    parser = _build_parser()
    try:
        namespace = parser.parse_args(argv)
    except SystemExit as exc:  # argparse 在参数非法时会直接退出
        raise InvalidArgumentError(f"命令行参数无法识别：{' '.join(argv)}") from exc

    if namespace.help:
        raise InvalidArgumentError("使用说明", USAGE)
    if not namespace.original or not namespace.suspect or not namespace.answer:
        raise InvalidArgumentError(
            "必须提供三个文件路径：原文文件、抄袭版论文文件、答案文件",
            USAGE,
        )
    if namespace.ngram < 1:
        raise InvalidArgumentError("--ngram 必须是不小于 1 的整数")

    # 答案文件若与输入文件相同，会破坏输入数据，这里提前拦截。
    if namespace.answer in (namespace.original, namespace.suspect):
        raise InvalidArgumentError("答案文件路径不能与输入文件路径相同")

    return Settings(
        original_path=namespace.original,
        suspect_path=namespace.suspect,
        answer_path=namespace.answer,
        ngram=namespace.ngram,
        metric=namespace.metric,
        percent=namespace.percent,
        verbose=namespace.verbose,
        quiet=namespace.quiet,
    )


def format_score(score: float, percent: bool = False) -> str:
    """把重复率格式化成"精确到小数点后两位"的浮点数字符串。"""
    return f"{score * 100:.2f}" if percent else f"{score:.2f}"


def configure_console() -> None:
    """让标准输出/错误流在无法表示中文的控制台上也不会抛异常。

    某些 IDE 或重定向场景下 ``sys.stdout.encoding`` 会是 ASCII，此时
    打印中文提示会抛出 ``UnicodeEncodeError``，导致程序"异常退出"。
    把错误处理策略改为 ``replace`` 之后，提示信息退化成问号，
    但**答案文件仍然正确写出**，返回码保持 0。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:  # pragma: no cover - 例如 io.StringIO
            continue
        try:
            reconfigure(errors="replace")
        except (ValueError, OSError):  # pragma: no cover - 极端环境
            continue


def write_answer(answer_path: str, score: float, percent: bool = False) -> None:
    """把结果写入答案文件；任何写入失败都转换成 :class:`OutputWriteError`。"""
    text = format_score(score, percent) + "\n"
    try:
        with open(answer_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    except OSError as exc:
        raise OutputWriteError(f"答案文件写入失败：{answer_path}", str(exc)) from exc


def run(settings: Settings) -> Report:
    """执行一次完整的查重流程，把答案写入文件并返回统计报告。"""
    started = time.perf_counter()
    original_raw, original_encoding = read_text(settings.original_path)
    suspect_raw, suspect_encoding = read_text(settings.suspect_path)

    original = normalize_text(original_raw)
    suspect = normalize_text(suspect_raw)
    score = compare_texts(original, suspect, settings.ngram, settings.metric)

    write_answer(settings.answer_path, score, settings.percent)
    return Report(
        score=score,
        original_chars=len(original),
        suspect_chars=len(suspect),
        original_encoding=original_encoding,
        suspect_encoding=suspect_encoding,
        elapsed_seconds=time.perf_counter() - started,
    )


def main(argv: list[str] | None = None) -> int:
    """程序主入口，返回进程退出码（便于单元测试直接调用）。"""
    arguments = list(sys.argv[1:] if argv is None else argv)
    configure_console()

    # -h / --help 属于正常请求：打印用法并以 0 退出（而不是当成参数错误）。
    if "-h" in arguments or "--help" in arguments:
        print(USAGE)
        return 0

    try:
        settings = parse_args(arguments)
    except InvalidArgumentError as exc:
        print(f"参数错误：{exc}", file=sys.stderr)
        print(f"用法：{exc.detail or USAGE}", file=sys.stderr)
        return exc.exit_code

    try:
        report = run(settings)
    except PlagiarismCheckError as exc:
        print(f"运行失败：{exc}", file=sys.stderr)
        return exc.exit_code
    except Exception as exc:  # pragma: no cover - 最后一道防线
        print(f"未预期的内部错误：{exc}", file=sys.stderr)
        return 1

    if not settings.quiet:
        print(f"重复率：{format_score(report.score, settings.percent)}")
    if settings.verbose:
        print(
            "明细：原文 {0} 字（{1}）/ 抄袭版 {2} 字（{3}）/ ngram={4} / "
            "指标={5} / 耗时 {6:.3f}s".format(
                report.original_chars,
                report.original_encoding,
                report.suspect_chars,
                report.suspect_encoding,
                settings.ngram,
                settings.metric,
                report.elapsed_seconds,
            ),
            file=sys.stderr,
        )
    return 0
