# -*- coding: utf-8 -*-
"""结果渲染：文本表格 / Markdown / JSON。"""

import json
from typing import List

from .optimizer import OptimizationResult
from .tariff_model import minutes_to_hhmm, SLOT_MINUTES


def _disp_len(s: str) -> int:
    return sum(2 if ord(c) > 127 else 1 for c in str(s))


def _pad(s, width: int) -> str:
    s = str(s)
    return s + " " * max(0, width - _disp_len(s))


def table(rows: List[List[str]]) -> str:
    if not rows:
        return ""
    widths = [max(_disp_len(r[i]) for r in rows) for i in range(len(rows[0]))]
    lines = []
    for ri, r in enumerate(rows):
        lines.append("  ".join(_pad(c, widths[i]) for i, c in enumerate(r)))
        if ri == 0:
            lines.append("  ".join("-" * w for w in widths))
    return "\n".join(lines)


def render_text(result: OptimizationResult, yearly: bool = True) -> str:
    out = []
    out.append("=" * 74)
    title = "用电时段优化结果"
    if result.region:
        title += "  ·  %s" % result.region
    out.append(title)
    out.append("=" * 74)

    if result.customer_type:
        out.append("用户类型：%s" % result.customer_type)
    if result.confidence:
        out.append("数据可信度：%s" % result.confidence)
    out.append("")

    rows = [["设备", "功率", "时长", "建议时段", "优化前", "优化后", "单次节省"]]
    for item in result.items:
        rows.append([
            item.load.name,
            "%.2f kW" % item.load.power_kw,
            "%.1f h" % item.load.duration_h,
            "%s-%s" % (item.start_hhmm, item.end_hhmm) if item.slots else "-",
            "¥%.2f" % item.baseline_cost,
            "¥%.2f" % item.cost,
            ("¥%.2f" % item.saving) + ("" if item.feasible else " (未优化)"),
        ])
    out.append(table(rows))
    out.append("")

    out.append("单次运行合计：优化前 ¥%.2f → 优化后 ¥%.2f，节省 ¥%.2f（%.1f%%）"
               % (result.baseline_total, result.optimized_total,
                  result.saving, result.saving_pct))
    if yearly:
        out.append("按各设备每周使用频次年化：预计年省 ¥%.2f  [估算]" % result.yearly_saving)

    peak = result.peak_concurrent_kw()
    if peak:
        out.append("优化后最大同时功率：%.2f kW" % peak)

    if result.warnings:
        out.append("")
        out.append("注意事项：")
        for w in result.warnings:
            out.append("  - %s" % w)

    out.append("")
    out.append("金额为基于给定电价与设备参数的估算，实际节省取决于真实使用模式。")
    return "\n".join(out)


def render_markdown(result: OptimizationResult) -> str:
    out = []
    out.append("# 用电时段优化报告\n")
    if result.region:
        out.append("**地区**：%s  \n**用户类型**：%s  \n**数据可信度**：%s\n"
                   % (result.region, result.customer_type, result.confidence))

    out.append("## 优化方案\n")
    out.append("| 设备 | 功率 | 时长 | 建议时段 | 优化前 | 优化后 | 单次节省 |")
    out.append("|---|---|---|---|---|---|---|")
    for item in result.items:
        out.append("| %s | %.2f kW | %.1f h | %s-%s | ¥%.2f | ¥%.2f | ¥%.2f |" % (
            item.load.name, item.load.power_kw, item.load.duration_h,
            item.start_hhmm, item.end_hhmm,
            item.baseline_cost, item.cost, item.saving))

    out.append("")
    out.append("## 汇总\n")
    out.append("- 单次合计：¥%.2f → ¥%.2f" % (result.baseline_total, result.optimized_total))
    out.append("- **单次节省**：¥%.2f（%.1f%%）" % (result.saving, result.saving_pct))
    out.append("- **预计年省**：¥%.2f（估算）" % result.yearly_saving)
    out.append("- 优化后最大同时功率：%.2f kW" % result.peak_concurrent_kw())

    if result.warnings:
        out.append("\n## 注意事项\n")
        for w in result.warnings:
            out.append("- %s" % w)

    return "\n".join(out)


def render_json(result: OptimizationResult) -> str:
    payload = {
        "region": result.region,
        "customer_type": result.customer_type,
        "confidence": result.confidence,
        "baseline_total": round(result.baseline_total, 4),
        "optimized_total": round(result.optimized_total, 4),
        "saving": round(result.saving, 4),
        "saving_pct": round(result.saving_pct, 2),
        "yearly_saving": round(result.yearly_saving, 2),
        "peak_concurrent_kw": round(result.peak_concurrent_kw(), 3),
        "hourly_load_optimized": [round(v, 3) for v in result.hourly_load()],
        "hourly_load_baseline": [round(v, 3) for v in result.baseline_hourly_load()],
        "hourly_price": [p for _, p in result.curve],
        "hourly_periods": [n for n, _ in result.curve],
        "items": [
            {
                "name": i.load.name,
                "power_kw": i.load.power_kw,
                "duration_h": i.load.duration_h,
                "start": i.start_hhmm,
                "end": i.end_hhmm,
                "slots": i.slots,
                "segments": ["%s-%s" % (
                    minutes_to_hhmm(s[0] * SLOT_MINUTES),
                    minutes_to_hhmm((s[-1] + 1) * SLOT_MINUTES)) for s in i.segments],
                "cost_before": round(i.baseline_cost, 4),
                "cost_after": round(i.cost, 4),
                "saving": round(i.saving, 4),
                "yearly_saving": round(i.yearly_saving, 2),
                "feasible": i.feasible,
                "note": i.note,
            }
            for i in result.items
        ],
        "warnings": result.warnings,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
