# -*- coding: utf-8 -*-
"""柔性负荷建模与内置家电库。"""

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class Load:
    """
    一台用电设备。

    Attributes
    ----------
    name : 设备名称
    power_kw : 运行功率（千瓦）
    duration_h : 单次运行时长（小时）
    window_start / window_end : 允许运行的时间窗（HH:MM），不跨天
    current_start : 用户当前习惯的启动时间（HH:MM）。**用于计算优化前的基准成本**；
        若为空则回退到 window_start。基准线反映真实习惯，优化收益才有意义。
    interruptible : 是否可中断（可分多段运行）
    fixed_start : 若非 None，表示设备不可调度，只能在此时刻启动
    times_per_week : 每周使用频次（用于年化估算）
    standby_kw : 非运行时段的基础功耗，可选
    category : 分类标签
    """

    name: str
    power_kw: float
    duration_h: float
    window_start: str = "00:00"
    window_end: str = "24:00"
    current_start: Optional[str] = None
    interruptible: bool = False
    fixed_start: Optional[str] = None
    times_per_week: float = 7.0
    standby_kw: float = 0.0
    category: str = "general"

    def is_schedulable(self) -> bool:
        return self.fixed_start is None

    def energy_kwh(self) -> float:
        return self.power_kw * self.duration_h


# ---------------------------------------------------------------------------
# 典型家电参数库
#
# power_kw 取常见中位值，current_start 取常见使用习惯，仅作缺省参考——
# 精确计算应使用设备铭牌参数与本人真实作息。
# ---------------------------------------------------------------------------
DEFAULT_LOADS: Dict[str, Dict] = {
    "washing_machine": {
        "label": "洗衣机", "power_kw": 0.5, "duration_h": 1.5,
        "window_start": "07:00", "window_end": "24:00",
        "current_start": "20:00", "interruptible": False,
    },
    "dishwasher": {
        "label": "洗碗机", "power_kw": 0.8, "duration_h": 1.5,
        "window_start": "19:00", "window_end": "24:00",
        "current_start": "20:00", "interruptible": False,
    },
    "water_heater": {
        "label": "储水式电热水器", "power_kw": 2.0, "duration_h": 2.0,
        "window_start": "00:00", "window_end": "24:00",
        "current_start": "18:00", "interruptible": True,
    },
    "ev_charger": {
        "label": "电动汽车慢充", "power_kw": 7.0, "duration_h": 4.0,
        # 跨天窗口：晚上插枪 → 次日早上拔枪，以覆盖广东/上海等地的凌晨谷段
        "window_start": "19:00", "window_end": "08:00",
        "current_start": "19:00", "interruptible": False,
    },
    "dryer": {
        "label": "烘干机", "power_kw": 2.5, "duration_h": 1.5,
        "window_start": "07:00", "window_end": "24:00",
        "current_start": "20:00", "interruptible": False,
    },
    "dehumidifier": {
        "label": "除湿机", "power_kw": 0.3, "duration_h": 3.0,
        "window_start": "09:00", "window_end": "22:00",
        "current_start": "14:00", "interruptible": True,
    },
    "robot_vacuum": {
        "label": "扫地机器人", "power_kw": 0.05, "duration_h": 2.0,
        "window_start": "09:00", "window_end": "18:00",
        "current_start": "10:00", "interruptible": True,
    },
    "rice_cooker": {
        "label": "电饭煲", "power_kw": 0.8, "duration_h": 1.0,
        "window_start": "05:00", "window_end": "07:00",
        "current_start": "05:30", "interruptible": False,
    },
    "air_conditioner": {
        "label": "空调（制冷）", "power_kw": 1.2, "duration_h": 8.0,
        "window_start": "00:00", "window_end": "24:00",
        "current_start": "18:00", "interruptible": True,
    },
    "air_purifier": {
        "label": "空气净化器", "power_kw": 0.06, "duration_h": 8.0,
        "window_start": "00:00", "window_end": "24:00",
        "current_start": "18:00", "interruptible": True,
    },
    "lighting": {
        "label": "照明（固定）", "power_kw": 0.15, "duration_h": 6.0,
        "fixed_start": "18:00", "interruptible": False,
    },
}


def make_load(key: str, **overrides) -> Load:
    """按内置参数库创建负荷，可覆盖任意字段。"""
    if key not in DEFAULT_LOADS:
        raise KeyError("未知设备类型：%s。可用：%s" % (key, ", ".join(DEFAULT_LOADS)))
    spec = dict(DEFAULT_LOADS[key])
    spec.update(overrides)
    label = spec.pop("label", None)
    if "name" not in spec:
        spec["name"] = label or key
    return Load(**spec)


def default_loads(keys: List[str]) -> List[Load]:
    return [make_load(k) for k in keys]


def load_from_dict(d: Dict) -> Load:
    """从字典构建（用于读取示例 JSON）。支持用 ``type`` 引用内置参数库。"""
    data = dict(d)
    if "type" in data:
        base = dict(DEFAULT_LOADS.get(data.pop("type"), {}))
        base.pop("label", None)
        data = {**base, **data}
    return Load(**data)


def presets() -> Dict[str, List[str]]:
    """预置家庭画像。"""
    return {
        "single": ["washing_machine", "water_heater", "rice_cooker", "lighting"],
        "family": [
            "washing_machine", "dishwasher", "water_heater", "dryer",
            "robot_vacuum", "rice_cooker", "lighting",
        ],
        "ev_owner": [
            "ev_charger", "washing_machine", "water_heater", "dishwasher", "lighting",
        ],
        "all_electric": [
            "ev_charger", "water_heater", "dryer", "washing_machine",
            "dishwasher", "air_conditioner", "robot_vacuum", "rice_cooker", "lighting",
        ],
    }
