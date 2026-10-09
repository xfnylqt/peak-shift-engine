#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
peak-shift-engine 命令行入口。

用法示例::

    # 使用预置家庭画像
    python cli.py --tariff ../cn-tou-tariff/data/zhejiang.json --preset family

    # 自定义设备组合
    python cli.py --tariff data/guangdong.json \\
        --loads ev_charger,water_heater,washing_machine

    # 指定月份（用于季节性电价省份）
    python cli.py --tariff data/shandong.json --preset all_electric --month 1

    # 输出 Markdown / JSON
    python cli.py --tariff data/jiangsu.json --preset ev_owner --format md
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from peak_shift import build_price_curve, load_tariff, optimize, report  # noqa: E402
from peak_shift.loads import DEFAULT_LOADS, load_from_dict, make_load, presets  # noqa: E402


def build_loads(args):
    if args.loads_file:
        spec = json.loads(Path(args.loads_file).read_text(encoding="utf-8"))
        return [load_from_dict(d) for d in spec["loads"]]
    if args.loads:
        keys = [k.strip() for k in args.loads.split(",") if k.strip()]
        return [make_load(k) for k in keys]
    key = args.preset or "family"
    return [make_load(k) for k in presets()[key]]


def main():
    ap = argparse.ArgumentParser(
        description="家庭用电时段优化引擎",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="可用设备类型：\n  " + "\n  ".join(sorted(DEFAULT_LOADS)),
    )
    ap.add_argument("--tariff", required=True, help="电价数据 JSON 路径")
    ap.add_argument("--preset", choices=list(presets()), help="预置家庭画像")
    ap.add_argument("--loads", help="逗号分隔的设备类型列表")
    ap.add_argument("--loads-file", help="自定义负荷 JSON 文件")
    ap.add_argument("--month", type=int, choices=range(1, 13), help="月份（季节性电价）")
    ap.add_argument("--peak-limit", type=float, help="家庭最大同时功率上限（kW）")
    ap.add_argument("--format", choices=["text", "md", "json"], default="text")
    ap.add_argument("--no-yearly", action="store_true", help="不输出年化估算")
    args = ap.parse_args()

    try:
        tariff = load_tariff(args.tariff)
    except FileNotFoundError:
        print("错误：找不到电价文件 %s" % args.tariff, file=sys.stderr)
        return 2
    except json.JSONDecodeError as e:
        print("错误：电价文件不是合法 JSON：%s" % e, file=sys.stderr)
        return 2

    if not tariff.has_prices():
        print("警告：该电价方案中存在未核实的价格（null），相关设备将无法优化。",
              file=sys.stderr)

    loads = build_loads(args)
    curve = build_price_curve(tariff, month=args.month)

    result = optimize(
        loads, curve,
        region=tariff.region,
        customer_type=tariff.customer_type,
        confidence=tariff.confidence,
        peak_limit_kw=args.peak_limit,
    )

    if args.format == "json":
        print(report.render_json(result))
    elif args.format == "md":
        print(report.render_markdown(result))
    else:
        print(report.render_text(result, yearly=not args.no_yearly))

    return 0


if __name__ == "__main__":
    sys.exit(main())
