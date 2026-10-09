# -*- coding: utf-8 -*-
"""
peak-shift-engine
=================

家庭用电时段优化引擎。

把「夜间用电更划算」这种模糊认知，变成「洗衣机 22:15 启动，年省 X 元」这种
可执行方案。

模块结构：

- ``tariff_model`` : 电价数据加载与 24 小时电价曲线构建
- ``loads``        : 柔性负荷建模与内置家电库
- ``optimizer``    : 时段分配优化求解
- ``report``       : 结果渲染（文本 / Markdown / JSON）

设计原则：零外部依赖，仅使用 Python 标准库。
"""

from .tariff_model import Tariff, load_tariff, build_price_curve
from .loads import Load, default_loads, load_from_dict
from .optimizer import optimize, OptimizationResult, ScheduleItem

__version__ = "0.1.0"
__all__ = [
    "Tariff",
    "load_tariff",
    "build_price_curve",
    "Load",
    "default_loads",
    "load_from_dict",
    "optimize",
    "OptimizationResult",
    "ScheduleItem",
]
