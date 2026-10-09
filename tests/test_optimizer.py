#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""引擎核心逻辑的单元测试（纯标准库 unittest）。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from peak_shift.loads import Load, make_load  # noqa: E402
from peak_shift.optimizer import _baseline_slots, _needed_slots, optimize  # noqa: E402
from peak_shift.tariff_model import (  # noqa: E402
    SLOTS_PER_DAY, Tariff, build_price_curve, to_minutes,
)


def make_curve(spec):
    """用 {(start,end): (name, price)} 构造 96 槽曲线，未覆盖处为 None。"""
    curve = [("unknown", None)] * SLOTS_PER_DAY
    for (start, end), (name, price) in spec.items():
        s, e = to_minutes(start), to_minutes(end)
        idxs = range(s, e) if s < e else list(range(s, 1440)) + list(range(0, e))
        for m in idxs:
            curve[m // 15] = (name, price)
    return curve


def make_tariff(periods, seasonal=None):
    return Tariff(
        region="测试省", customer_type="居民", confidence="official",
        effective_date="2026-01-01", source={"name": "t", "url": "t"},
        periods=periods, seasonal=seasonal or [],
    )


PEAK = ("08:00", "22:00")
VALLEY_NIGHT = ("22:00", "24:00")
VALLEY_MORNING = ("00:00", "08:00")


class TestTimeHelpers(unittest.TestCase):
    def test_to_minutes(self):
        self.assertEqual(to_minutes("00:00"), 0)
        self.assertEqual(to_minutes("22:00"), 1320)
        self.assertEqual(to_minutes("24:00"), 1440)

    def test_needed_slots(self):
        self.assertEqual(_needed_slots(make_load("water_heater")), 8)     # 2.0 h
        self.assertEqual(_needed_slots(make_load("washing_machine")), 6)  # 1.5 h

    def test_baseline_respects_fixed_start(self):
        load = make_load("lighting")
        self.assertEqual(_baseline_slots(load)[0], to_minutes("18:00") // 15)

    def test_baseline_respects_current_start(self):
        load = make_load("washing_machine")  # current_start = 20:00
        self.assertEqual(_baseline_slots(load)[0], to_minutes("20:00") // 15)


class TestOptimizer(unittest.TestCase):
    def setUp(self):
        self.curve = make_curve({
            VALLEY_MORNING: ("valley", 0.3),
            PEAK: ("peak", 0.9),
            VALLEY_NIGHT: ("valley", 0.3),
        })

    def test_continuous_load_moves_to_valley(self):
        # 1.5 h，窗口 07:00-24:00 → 谷段 22:00-24:00 足够容纳
        load = Load(name="洗衣机", power_kw=0.5, duration_h=1.5,
                    window_start="07:00", window_end="24:00", current_start="20:00")
        item = optimize([load], self.curve, region="测试").items[0]
        self.assertTrue(item.feasible)
        self.assertTrue(all(self.curve[s][0] == "valley" for s in item.slots))
        self.assertGreater(item.saving, 0)

    def test_interruptible_load_picks_cheapest_slots(self):
        load = make_load("water_heater")  # 2.0 h，可中断，全窗口
        item = optimize([load], self.curve, region="测试").items[0]
        self.assertTrue(all(self.curve[s][0] == "valley" for s in item.slots))

    def test_fixed_load_not_moved(self):
        load = make_load("lighting")
        item = optimize([load], self.curve, region="测试").items[0]
        self.assertEqual(item.saving, 0.0)
        self.assertIn("固定", item.note)

    def test_baseline_uses_current_start(self):
        # 基准 12:00（峰）→ 优化后谷段；1 kW × 1 h × (0.9 - 0.3) = 0.6 元
        load = Load(name="x", power_kw=1.0, duration_h=1.0,
                    window_start="00:00", window_end="24:00", current_start="12:00")
        item = optimize([load], self.curve, region="测试").items[0]
        self.assertAlmostEqual(item.baseline_cost, 0.9, places=2)
        self.assertAlmostEqual(item.cost, 0.3, places=2)
        self.assertAlmostEqual(item.saving, 0.6, places=2)

    def test_ev_charging_moves_to_late_valley(self):
        # 2 h 充电，窗口 19:00-24:00 → 最优完全落入 22:00 后的谷段
        load = Load(name="EV", power_kw=7.0, duration_h=2.0,
                    window_start="19:00", window_end="24:00", current_start="19:00")
        item = optimize([load], self.curve, region="测试").items[0]
        self.assertTrue(all(self.curve[s][0] == "valley" for s in item.slots))
        # 7 kW × 2 h × (0.9 - 0.3) = 8.4 元
        self.assertAlmostEqual(item.saving, 8.4, places=2)

    def test_missing_price_yields_warning(self):
        curve = [("unknown", None)] * SLOTS_PER_DAY
        res = optimize([make_load("washing_machine")], curve)
        self.assertTrue(res.warnings)
        self.assertEqual(res.saving, 0.0)

    def test_insufficient_window_marks_infeasible(self):
        load = Load(name="过载设备", power_kw=1.0, duration_h=5.0,
                    window_start="22:00", window_end="24:00")
        item = optimize([load], self.curve).items[0]
        self.assertFalse(item.feasible)
        self.assertIn("不足", item.note)

    def test_peak_limit_warning(self):
        loads = [make_load("ev_charger"), make_load("dryer")]
        res = optimize(loads, self.curve, peak_limit_kw=5.0)
        self.assertTrue(any("上限" in w for w in res.warnings))

    def test_yearly_saving_scales_with_frequency(self):
        load = Load(name="EV", power_kw=7.0, duration_h=2.0,
                    window_start="19:00", window_end="24:00",
                    current_start="19:00", times_per_week=3)
        item = optimize([load], self.curve).items[0]
        self.assertAlmostEqual(item.yearly_saving, 8.4 * 3 * 52, places=2)


class TestCurve(unittest.TestCase):
    def test_cross_midnight_period_wraps(self):
        t = make_tariff([
            {"name": "peak", "start": "08:00", "end": "22:00", "price": 1.0},
            {"name": "valley", "start": "22:00", "end": "08:00", "price": 0.3},
        ])
        curve = build_price_curve(t)
        self.assertEqual(len(curve), SLOTS_PER_DAY)
        self.assertEqual(curve[0][0], "valley")    # 00:00
        self.assertEqual(curve[31][0], "valley")   # 07:45
        self.assertEqual(curve[40][0], "peak")     # 10:00
        self.assertEqual(curve[87][0], "peak")     # 21:45（峰段最后一槽）
        self.assertEqual(curve[88][0], "valley")   # 22:00 整，谷段起点
        self.assertEqual(curve[95][0], "valley")   # 23:45

    def test_seasonal_selection(self):
        t = make_tariff(
            periods=[
                {"name": "peak", "start": "08:00", "end": "22:00", "price": 1.0},
                {"name": "valley", "start": "22:00", "end": "08:00", "price": 0.3},
            ],
            seasonal=[{
                "season": "采暖季", "months": [1],
                "periods": [
                    {"name": "peak", "start": "08:00", "end": "20:00", "price": 1.0},
                    {"name": "valley", "start": "20:00", "end": "08:00", "price": 0.2},
                ],
            }],
        )
        c_jan = build_price_curve(t, month=1)
        c_jul = build_price_curve(t, month=7)
        self.assertEqual(c_jan[84][0], "valley")   # 21:00 → 采暖季为谷段
        self.assertEqual(c_jul[84][0], "peak")     # 21:00 → 非采暖季为峰段
        self.assertAlmostEqual(c_jan[84][1], 0.2, places=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
