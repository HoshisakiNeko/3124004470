#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""论文查重程序入口。

用法::

    python main.py <原文文件绝对路径> <抄袭版论文文件绝对路径> <答案文件绝对路径>

例如::

    python main.py C:\\tests\\orig.txt C:\\tests\\orig_add.txt C:\\tests\\ans.txt

答案文件内容为精确到小数点后两位的浮点数（0.00 ~ 1.00）。
"""

from __future__ import annotations

import sys

from plagiarism.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

