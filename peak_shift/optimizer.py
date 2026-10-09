# -*- coding: utf-8 -*-
"""
时段分配优化求解。

模型
----
对每台柔性负荷，在允许时间窗内寻找使电费最小的运行时段分配：

.. math::

    \\min_{s} \\sum_{t \\in \\mathcal{T}(s)} P \\cdot c_t \\cdot \\Delta t

其中 :math:`P` 为功率，:math:`c_t` 为 t 时刻电价，:math:`\\Delta t` 为时间粒度，
:math:`\\mathcal{T}(s)` 为以 s 为起点的运行时段集合。

求解策略
--------
- **不可中断负荷**：在窗口内枚举全部可行起点，取成本最低者（24 小时 / 15 分钟
  粒度下最多约 96 次枚举，精确且无需求解器）
- **可中断负荷**：在窗口内按电价升序选取所需槽位（贪心，在无耦合约束时最优）

约束当前覆盖：时间窗完整性、可中断性。家庭总功率上限（多设备耦合）尚未纳入
求解，仅作为事后校验指标输出。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .loads import Load
from .tariff_model import SLOT_MINUTES, SLOTS_PER_DAY, minutes_to_hhmm, to_minutes

SLOT_HOURS = SLOT_MINUTES / 60.0


@dataclass
class ScheduleItem:
    load: Load
    slots: List[int]
    cost: float
    baseline_cost: float
    feasible: bool = True
    note: str = ""

    @property
    def saving(self) -> float:
        return self.baseline_cost - self.cost

    @property
    def start_hhmm(self) -> str:
        return minutes_to_hhmm(min(self.slots) * SLOT_MINUTES) if self.slots else "-"

    @property
    def end_hhmm(self) -> str:
        if not self.slots:
            return "-"
        return minutes_to_hhmm((max(self.slots) + 1) * SLOT_MINUTES)

    @property
    def yearly_saving(self) -> float:
        return self.saving * self.load.times_per_week * 52

    @property
    def segments(self) -> List[List[int]]:
        """把槽位列表切成连续段。"""
        if not self.slots:
            return []
        segs, cur = [], [self.slots[0]]
        for s in self.slots[1:]:
            if s == cur[-1] + 1:
                cur.append(s)
            else:
                segs.append(cur)
                cur = [s]
        segs.append(cur)
        return segs


@dataclass
class OptimizationResult:
    region: str
    customer_type: str
    confidence: str
    curve: List[Tuple[str, Optional[float]]]
    items: List[ScheduleItem] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    peak_limit_kw: Optional[float] = None

    @property
    def baseline_total(self) -> float:
        return sum(i.baseline_cost for i in self.items)

    @property
    def optimized_total(self) -> float:
        return sum(i.cost for i in self.items)

    @property
    def saving(self) -> float:
        return self.baseline_total - self.optimized_total

    @property
    def saving_pct(self) -> float:
        if self.baseline_total <= 0:
            return 0.0
        return self.saving / self.baseline_total * 100.0

    @property
    def yearly_saving(self) -> float:
        return sum(i.yearly_saving for i in self.items)

    def hourly_load(self) -> List[float]:
        """
        优化后逐小时等效功率（kW）。

        每个 15 分钟槽对所属小时的贡献为 ``power_kw × 0.25``；若某小时内 4 个槽
        全部运行，等效功率恰为额定功率。
        """
        hourly = [0.0] * 24
        for item in self.items:
            for slot in item.slots:
                hourly[slot // 4] += item.load.power_kw * SLOT_HOURS
        return hourly

    def baseline_hourly_load(self) -> List[float]:
        """优化前逐小时等效功率（kW）。"""
        hourly = [0.0] * 24
        for item in self.items:
            for slot in _baseline_slots(item.load):
                hourly[slot // 4] += item.load.power_kw * SLOT_HOURS
        return hourly

    def peak_concurrent_kw(self) -> float:
        return max(self.hourly_load()) if self.items else 0.0


def _window_slot_list(load: Load) -> List[int]:
    """
    返回允许窗口内的槽位列表（按时间先后排列）。

    支持**跨天窗口**：如 19:00 → 08:00 返回 ``[76..95] + [0..31]``，
    以覆盖广东、上海等「凌晨谷段」省份的夜间接入场景。

    当 ``window_start == window_end`` 时视为全天可用。
    """
    s = to_minutes(load.window_start) // SLOT_MINUTES
    e = to_minutes(load.window_end) // SLOT_MINUTES
    if s == e:
        return list(range(0, SLOTS_PER_DAY))
    if s < e:
        return list(range(s, min(e, SLOTS_PER_DAY)))
    return list(range(s, SLOTS_PER_DAY)) + list(range(0, min(e, SLOTS_PER_DAY)))


def _baseline_start_slot(load: Load) -> int:
    """
    优化前的启动槽位。

    优先级：fixed_start（固定负荷）> current_start（用户当前习惯）> window_start。

    基准线必须反映用户的**真实习惯**。若简单沿用 window_start，而该时刻恰好
    已位于谷段，就会得出「本来就最省、无需优化」的错误结论。
    """
    anchor = load.fixed_start or load.current_start or load.window_start
    return min(to_minutes(anchor) // SLOT_MINUTES, SLOTS_PER_DAY - 1)


def _baseline_slots(load: Load) -> List[int]:
    n = max(1, int(round(load.duration_h * 60 / SLOT_MINUTES)))
    start = _baseline_start_slot(load)
    return [(start + i) % SLOTS_PER_DAY for i in range(n)]


def _cost_of(slots: List[int], curve, power_kw: float) -> Optional[float]:
    total = 0.0
    for s in slots:
        if not (0 <= s < SLOTS_PER_DAY):
            return None
        _, price = curve[s]
        if price is None:
            return None
        total += price * power_kw * SLOT_HOURS
    return total


def _needed_slots(load: Load) -> int:
    return max(1, int(round(load.duration_h * 60 / SLOT_MINUTES)))


def _solve_continuous(load: Load, curve, n: int) -> Tuple[Optional[List[int]], Optional[float], str]:
    """
    不可中断负荷：在窗口内枚举全部**物理连续**的片段起点，取成本最低者。

    片段不得跨越午夜回绕（23:45 的下一槽不会被视为 00:00），以保证排程在
    现实时间轴上是连续的一次运行。
    """
    window = _window_slot_list(load)
    if len(window) < n:
        return None, None, "时间窗不足以容纳运行时长"
    best_slots, best_cost = None, None
    for i in range(len(window) - n + 1):
        seg = window[i:i + n]
        if any(seg[j + 1] != seg[j] + 1 for j in range(len(seg) - 1)):
            continue
        c = _cost_of(seg, curve, load.power_kw)
        if c is None:
            continue
        if best_cost is None or c < best_cost:
            best_slots, best_cost = list(seg), c
    if best_slots is None:
        return None, None, "窗口内无可用连续时段，或电价数据缺失"
    return best_slots, best_cost, ""


def _solve_interruptible(load: Load, curve, n: int) -> Tuple[Optional[List[int]], Optional[float], str]:
    """可中断负荷：在窗口内按电价升序选取所需槽位（无耦合约束时为最优解）。"""
    window = _window_slot_list(load)
    cand = []
    for slot in window:
        _, price = curve[slot]
        if price is not None:
            cand.append((price, slot))
    if len(cand) < n:
        return None, None, "窗口内可用时段不足"
    chosen = sorted(slot for _, slot in sorted(cand)[:n])
    c = _cost_of(chosen, curve, load.power_kw)
    if c is None:
        return None, None, "电价数据缺失"
    return chosen, c, ""


def optimize(
    loads: List[Load],
    curve: List[Tuple[str, Optional[float]]],
    region: str = "",
    customer_type: str = "",
    confidence: str = "",
    peak_limit_kw: Optional[float] = None,
) -> OptimizationResult:
    """对一组负荷求解最优时段分配。"""
    result = OptimizationResult(
        region=region,
        customer_type=customer_type,
        confidence=confidence,
        curve=curve,
        peak_limit_kw=peak_limit_kw,
    )

    if not any(p is not None for _, p in curve):
        result.warnings.append("电价曲线中不含任何有效电价，无法进行优化。请检查数据是否已核实。")
        return result

    for load in loads:
        n = _needed_slots(load)
        base_slots = _baseline_slots(load)
        base_cost = _cost_of(base_slots, curve, load.power_kw)
        if base_cost is None:
            base_cost = 0.0
            result.warnings.append("「%s」的原始时段电价数据缺失，基准成本按 0 计。" % load.name)

        if not load.is_schedulable():
            result.items.append(ScheduleItem(
                load=load, slots=base_slots, cost=base_cost,
                baseline_cost=base_cost, feasible=True,
                note="固定负荷，不可调度",
            ))
            continue

        if load.interruptible:
            slots, cost, err = _solve_interruptible(load, curve, n)
        else:
            slots, cost, err = _solve_continuous(load, curve, n)

        if slots is None:
            result.items.append(ScheduleItem(
                load=load, slots=base_slots, cost=base_cost,
                baseline_cost=base_cost, feasible=False, note=err,
            ))
            result.warnings.append("「%s」未能优化：%s" % (load.name, err))
            continue

        result.items.append(ScheduleItem(
            load=load, slots=slots, cost=cost, baseline_cost=base_cost,
        ))

    if peak_limit_kw is not None:
        peak = result.peak_concurrent_kw()
        if peak > peak_limit_kw:
            result.warnings.append(
                "优化后最大同时功率 %.1f kW 超过给定上限 %.1f kW。"
                "建议错开大功率设备，或启用总功率约束求解（尚未实现）。"
                % (peak, peak_limit_kw)
            )

    return result
