# -*- coding: utf-8 -*-
"""电价模型：加载分时电价数据并构建 24 小时离散电价曲线。"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SLOT_MINUTES = 15
SLOTS_PER_DAY = 24 * 60 // SLOT_MINUTES  # 96

# 各时段类型的缺省权重，用于数据不完整时的降级处理
PERIOD_ORDER = ["deep_valley", "valley", "flat", "peak", "sharp"]


def to_minutes(hhmm: str) -> int:
    """'22:00' -> 1320；'24:00' -> 1440。"""
    if hhmm == "24:00":
        return 24 * 60
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def minutes_to_hhmm(m: int) -> str:
    m = m % (24 * 60)
    return "%02d:%02d" % (m // 60, m % 60)


@dataclass
class Tariff:
    """一个地区、一类用户的电价方案。"""

    region: str
    customer_type: str
    confidence: str
    effective_date: str
    source: Dict
    periods: List[Dict]
    seasonal: List[Dict] = field(default_factory=list)
    tiers: List[Dict] = field(default_factory=list)
    notes: str = ""
    raw: Dict = field(default_factory=dict)

    def periods_for(self, month: Optional[int] = None) -> List[Dict]:
        """按月选择适用的时段定义（优先季节性，其次通用）。"""
        if month is not None and self.seasonal:
            for s in self.seasonal:
                if month in (s.get("months") or []):
                    return s["periods"]
        return self.periods

    def prices_by_type(self) -> Dict[str, float]:
        """时段类型 -> 代表电价（取该类型下首个非空值）。"""
        out: Dict[str, float] = {}
        for p in self.periods:
            price = p.get("price")
            if price is not None and p["name"] not in out:
                out[p["name"]] = float(price)
        return out

    def has_prices(self) -> bool:
        return all(p.get("price") is not None for p in self.periods)


def load_tariff(path) -> Tariff:
    """从 JSON 文件加载电价方案。"""
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    src = data.get("source") or {}
    return Tariff(
        region=data.get("region", path.stem),
        customer_type=data.get("customer_type", ""),
        confidence=data.get("confidence", "unknown"),
        effective_date=data.get("effective_date", ""),
        source=src if isinstance(src, dict) else {"name": str(src)},
        periods=data.get("periods", []),
        seasonal=data.get("seasonal", []),
        tiers=data.get("tiers", []),
        notes=data.get("notes", ""),
        raw=data,
    )


def build_price_curve(tariff: Tariff, month: Optional[int] = None) -> List[Tuple[str, Optional[float]]]:
    """
    构建 96 个 15 分钟槽的电价曲线。

    返回 ``[(period_name, price_or_None), ...]``，长度恒为 96。

    跨天时段（start > end，如 22:00 → 08:00）会被正确填充。
    未覆盖到的槽位标记为 ``("unknown", None)``。
    """
    curve: List[Optional[Tuple[str, Optional[float]]]] = [None] * SLOTS_PER_DAY
    periods = tariff.periods_for(month)

    for p in periods:
        start = to_minutes(p["start"])
        end = to_minutes(p["end"])
        price = p.get("price")
        price = None if price is None else float(price)

        if start < end:
            idxs = range(start, end)
        else:  # 跨天
            idxs = list(range(start, 24 * 60)) + list(range(0, end))

        for minute in idxs:
            slot = minute // SLOT_MINUTES
            if 0 <= slot < SLOTS_PER_DAY:
                # 后定义者覆盖先定义者，便于顺序覆盖语义
                curve[slot] = (p["name"], price)

    return [c if c is not None else ("unknown", None) for c in curve]


def curve_stats(curve: List[Tuple[str, Optional[float]]]) -> Dict[str, float]:
    """统计曲线中各时段类型占据的小时数。"""
    counts: Dict[str, int] = {}
    for name, _ in curve:
        counts[name] = counts.get(name, 0) + 1
    return {k: v * SLOT_MINUTES / 60.0 for k, v in counts.items()}


def peak_valley(curve: List[Tuple[str, Optional[float]]]) -> Tuple[Optional[float], Optional[float]]:
    """返回曲线上的最高价与最低价（忽略 None）。"""
    prices = [p for _, p in curve if p is not None]
    if not prices:
        return None, None
    return max(prices), min(prices)
