# 第一次个人编程作业：论文查重

用 Python 3 实现的论文查重程序：读入一篇**原文**和一篇在此基础上增删改
得到的**抄袭版论文**，计算两者的重复率，并把结果写入**答案文件**。

* 只使用 Python 标准库，**不需要安装任何第三方依赖**（`requirements.txt` 为空操作）；
* 只读取命令行给出的三个文件，不联网、不创建额外文件；
* 处理 100 KB 级文本耗时通常在 0.1 秒以内，处理 1 MB × 2 的中文长文本约 1.2 秒
  （评测限制为 5 秒 / 2048 MB）。

## 一、运行方式

与作业要求完全一致（三个参数都是绝对路径，参数之间用空格分隔）：

```bash
python main.py C:\tests\orig.txt C:\tests\orig_add.txt C:\tests\ans.txt
```

运行后 `ans.txt` 的内容形如 `0.87`——一个精确到小数点后两位、取值范围
`0.00 ~ 1.00` 的浮点数（**越大表示重复率越高**）。

> 如果课堂说明里要求答案写成百分数（`87.32`），只需要把
> `plagiarism/cli.py` 里的 `DEFAULT_PERCENT` 改成 `True`，
> 或者运行时加一个 `--percent` 参数，其余代码无需改动。

可选参数（不传即使用默认值，不影响评测调用方式）：

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| `-n, --ngram N` | n-gram 长度 | `2`（字符二元组） |
| `-m, --metric NAME` | 相似度指标：`cosine` / `jaccard` / `containment` | `cosine` |
| `--percent` | 以百分数输出（如 `87.32`） | 关闭 |
| `-v, --verbose` | 在标准错误流打印字数、编码、耗时等明细 | 关闭 |
| `-q, --quiet` | 不打印结果摘要 | 关闭 |

返回码：`0` 成功；`2` 参数错误；`3` 文件读写或解码错误；`1` 未预期的内部错误。

## 二、目录结构

```
main.py                    入口文件（评测调用的就是它）
plagiarism/
    __init__.py            包说明与版本号
    cli.py                 命令行解析、流程编排、答案文件写出
    similarity.py          核心计算模块：n-gram 切分 + 词频向量 + 相似度
    textio.py              文件读取（多编码自动识别）与文本归一化
    errors.py              自定义异常体系
tests/                     65 个单元测试用例（覆盖功能、异常、边界、性能）
tools/                     开发期工具（覆盖率、性能分析、基准对比、样例批量运行）
sample_data/               自建样例：原文与 4 种抄袭版论文
docs/                      博客草稿与各工具生成的报告
requirements.txt           说明"无需第三方依赖"
```

## 三、算法概要

1. **读取**：按 `utf-8-sig → utf-16 → gb18030 → big5` 的顺序尝试解码，
   避免乱码影响结论；
2. **归一化**：`NFKC` 全角转半角 + `casefold` 统一大小写 + 删除所有
   空白与标点，只留下文字字符；
3. **特征**：切成重叠的字符 n-gram（默认二元组），统计词频得到稀疏向量；
4. **度量**：默认计算两个词频向量的**余弦相似度**，输出保留两位小数。

中文没有天然词边界，采用字符二元组可以完全避开分词词典，既减少依赖，
也避免了字典覆盖率带来的误差；余弦相似度对文本长度不敏感，对局部的
增删改只有平缓惩罚，正好匹配"抄袭版 = 原文 + 增删改"的场景。

详细的设计说明、性能改进记录与覆盖率数据见
[docs/第一次个人编程作业-博客.md](docs/第一次个人编程作业-博客.md)。

## 四、样例结果

`sample_data/orig.txt` 为自建原文（360 字），四种抄袭版的结果如下
（由 `python tools/run_samples.py` 生成，见 `docs/samples_report.txt`）：

| 抄袭版 | 改动方式 | 重复率 |
| --- | --- | --- |
| `orig_add.txt` | 原文 + 新增一段 | 0.87 |
| `orig_del.txt` | 原文 - 删除一段 | 0.85 |
| `orig_edit.txt` | 原文 + 逐句换词改写 | 0.95 |
| `orig_rewrite.txt` | 完全不同主题 | 0.10 |

题目样例句
（`今天是星期天，天气晴，今天晚上我要去看电影。` 与
`今天是周天，天气晴朗，我晚上要去看电影。`）
的重复率为 `0.61`，符合"改了词、调了序，但仍是同一句话"的直觉。

## 五、开发期工具与复现命令

```bash
# 1. 单元测试（65 个用例，覆盖正常、异常、边界、性能场景）
python -m unittest discover -s tests -t . -v

# 2. 语句覆盖率（标准库 trace，输出到 docs/coverage/ 与 docs/coverage_report.txt）
python tools/coverage_report.py

# 3. 性能分析（cProfile，生成 docs/profile_stats.txt、profile_chart.svg /
#    profile_chart.png 与 profile_data.json）
python tools/profile_report.py 1000000

# 4. 三代实现的耗时/内存对比（docs/benchmark.txt）
python tools/benchmark.py 1000000

# 5. 批量运行 sample_data 下的样例（docs/samples_report.txt）
python tools/run_samples.py
```

## 六、PSP 表格（预估与实际）

| PSP2.1 | 预估耗时（分钟） | 实际耗时（分钟） |
| --- | --- | --- |
| Planning 计划 | 30 | 25 |
| · Estimate 估计这个任务需要多少时间 | 30 | 25 |
| Development 开发 | 610 | 655 |
| · Analysis 需求分析（包括学习新技术） | 60 | 50 |
| · Design Spec 生成设计文档 | 45 | 40 |
| · Design Review 设计复审 | 30 | 25 |
| · Coding Standard 代码规范 | 20 | 15 |
| · Design 具体设计 | 60 | 70 |
| · Coding 具体编码 | 180 | 200 |
| · Code Review 代码复审 | 45 | 50 |
| · Test 测试（自我测试、修改代码、提交修改） | 170 | 205 |
| Reporting 报告 | 90 | 95 |
| · Test Report 测试报告 | 40 | 45 |
| · Size Measurement 计算工作量 | 15 | 10 |
| · Postmortem & Process Improvement Plan 事后总结与改进计划 | 35 | 40 |
| **合计** | **730** | **775** |

## 七、作业要求对照

| 作业要求 | 本项目的落实方式 |
| --- | --- |
| 命令行给出三个绝对路径 | `main.py` → `plagiarism/cli.py:parse_args` |
| 答案精确到小数点后两位 | `plagiarism/cli.py:format_score`（`0.00 ~ 1.00`） |
| 代码质量分析、消除警告 | 无未使用导入/超长行/行尾空白，全部函数与模块均有文档字符串 |
| 性能分析与改进 | `tools/profile_report.py`、`tools/benchmark.py`，报告见 `docs/` |
| 至少 10 个单元测试 | `tests/` 下 65 个用例，语句覆盖率 100% |
| 异常处理 | `plagiarism/errors.py` 中 6 类异常，均有对应单元测试 |
