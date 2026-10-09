# peak-shift-engine

**家庭用电时段优化引擎** · 基于真实分时电价，求解「哪台设备该在几点运行」

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://python.org)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-none-brightgreen.svg)](peak_shift/)
[![Tests](https://img.shields.io/badge/tests-15%20passed-success.svg)](tests/)

---

## 它做什么

「夜间用电更划算」这句话人人都会说，但没人能回答：**我家的热水器挪到几点？一年能省多少？值不值得折腾？**

本引擎把这个问题形式化为一个**带时间窗约束的成本最小化问题**，并给出可直接执行的排程方案：

```
电动汽车慢充    7.00 kW  4.0 h  00:00-04:00  ¥16.49 → ¥6.27   节省 ¥10.22
储水式电热水器  2.00 kW  2.0 h  00:00-02:00  ¥3.18  → ¥0.90   节省 ¥2.28
洗衣机          0.50 kW  1.5 h  07:00-08:30  ¥0.44  → ¥0.26   节省 ¥0.18
---------------------------------------------------------------------------
单次运行合计：¥21.41 → ¥8.72，节省 59.3%   预计年省 ¥4619.21 [估算]
```

> 配套项目：电价数据 [`cn-tou-tariff`](../cn-tou-tariff) · 可视化 [`peak-shift-studio`](../peak-shift-studio)

---

## 优化模型

### 目标函数

对每台柔性负荷，在允许时间窗内寻找使电费最小的运行时段分配：

$$\min_{s \in \mathcal{W}} \; \sum_{t \in \mathcal{T}(s)} P \cdot c_t \cdot \Delta t$$

| 符号 | 含义 |
|---|---|
| $P$ | 设备额定功率（kW） |
| $c_t$ | $t$ 时刻电价（元/kWh），来自分时电价曲线 |
| $\Delta t$ | 时间粒度，本引擎取 **15 分钟**（96 槽/天） |
| $\mathcal{W}$ | 允许窗口内的可行起点集合 |
| $\mathcal{T}(s)$ | 以 $s$ 为起点的运行时段集合 |

### 约束

| 约束 | 处理方式 |
|---|---|
| 时间窗完整性 | 运行必须完全落在 `[window_start, window_end]` 内 |
| 不可中断性 | 连续型负荷在窗口内**枚举全部连续片段**（15 分钟粒度下 ≤ 96 次，精确无需求解器） |
| 可中断性 | 按电价升序贪心选取所需槽位（无耦合约束时为最优解） |
| 跨天窗口 | 窗口 19:00 → 08:00 自动展开为 `[76..95] + [0..31]` |
| 固定负荷 | `fixed_start` 非空者不参与调度（如照明） |

### 基准线的定义（关键设计）

优化收益取决于与什么比。本引擎的基准线取 **`current_start`（用户当前习惯的启动时间）**，而非窗口起点：

> 若基准线错误地取窗口起点，而该时刻恰好已在谷段，就会得出「本来就最省、无需优化」的错误结论——这是同类工具常见的建模陷阱。

---

## 快速开始

**无需安装任何依赖**（Python 3.8+ 标准库即可）。

```bash
git clone https://github.com/xfnylqt/peak-shift-engine.git
cd peak-shift-engine

# 需要先准备电价数据（来自 cn-tou-tariff）
python cli.py --tariff ../cn-tou-tariff/data/zhejiang.json --preset ev_owner

# 自定义设备组合
python cli.py --tariff ../cn-tou-tariff/data/guangdong.json \
    --loads ev_charger,water_heater,washing_machine

# 季节性电价省份需指定月份
python cli.py --tariff ../cn-tou-tariff/data/shandong.json \
    --preset all_electric --month 1

# 输出格式
python cli.py --tariff zhejiang.json --preset family --format md
python cli.py --tariff zhejiang.json --preset family --format json

# 运行测试
python tests/test_optimizer.py
```

### 命令行参数

| 参数 | 说明 |
|---|---|
| `--tariff` | 电价数据 JSON 路径（**必填**） |
| `--preset` | 预置画像：`single` / `family` / `ev_owner` / `all_electric` |
| `--loads` | 逗号分隔的设备类型列表 |
| `--loads-file` | 自定义负荷 JSON |
| `--month` | 月份（1-12），用于季节性电价省份 |
| `--peak-limit` | 家庭最大同时功率（kW），超出时给出警告 |
| `--format` | `text` / `md` / `json` |

---

## 内置家电库

| 类型键 | 名称 | 功率 | 时长 | 默认窗口 | 可中断 |
|---|---|---|---|---|---|
| `ev_charger` | 电动汽车慢充 | 7.0 kW | 4.0 h | 19:00→08:00 | 否 |
| `water_heater` | 储水式电热水器 | 2.0 kW | 2.0 h | 全天 | 是 |
| `dryer` | 烘干机 | 2.5 kW | 1.5 h | 07:00-24:00 | 否 |
| `washing_machine` | 洗衣机 | 0.5 kW | 1.5 h | 07:00-24:00 | 否 |
| `dishwasher` | 洗碗机 | 0.8 kW | 1.5 h | 19:00-24:00 | 否 |
| `air_conditioner` | 空调（制冷） | 1.2 kW | 8.0 h | 全天 | 是 |
| `dehumidifier` | 除湿机 | 0.3 kW | 3.0 h | 09:00-22:00 | 是 |
| `robot_vacuum` | 扫地机器人 | 0.05 kW | 2.0 h | 09:00-18:00 | 是 |
| `rice_cooker` | 电饭煲 | 0.8 kW | 1.0 h | 05:00-07:00 | 否 |
| `air_purifier` | 空气净化器 | 0.06 kW | 8.0 h | 全天 | 是 |
| `lighting` | 照明（固定） | 0.15 kW | 6.0 h | — | 否 |

> 功率与时段为**常见缺省值**，精确测算请以设备铭牌与本人真实作息为准。

---

## 作为库使用

```python
from peak_shift import load_tariff, build_price_curve, optimize, report

tariff = load_tariff("data/zhejiang.json")
curve = build_price_curve(tariff)          # 96 个 15 分钟槽的电价曲线

from peak_shift.loads import presets, make_load
loads = [make_load(k) for k in presets()["ev_owner"]]

result = optimize(loads, curve,
                  region=tariff.region,
                  customer_type=tariff.customer_type,
                  confidence=tariff.confidence)

print(result.saving_pct)          # 节省百分比
print(result.yearly_saving)       # 年化估算
print(result.hourly_load())       # 优化后逐小时负荷（用于绘图）
print(report.render_markdown(result))
```

---

## 已知局限

诚实说明边界，避免误用：

1. **不含总功率上限的联合求解** —— 多设备同时启动可能超过家庭容量。当前仅作事后校验并给出警告，未纳入优化约束（该问题为 NP-hard，需引入求解器）
2. **不含储能与光伏** —— 未建模电池 SOC、放电策略与光伏出力
3. **负荷模型为静态** —— 未考虑设备效率随环境变化（如空调随温差变化）
4. **单日独立求解** —— 未做跨日联合优化
5. **金额为估算** —— 依赖用户提供的功率与习惯，实际节省因家庭而异

---

## 数据依赖

引擎本身不含电价数据，需配合 [`cn-tou-tariff`](../cn-tou-tariff) 使用。若电价文件中 `price` 为 `null`（未核实），相关设备将无法优化并给出警告。

---

## 许可证

[MIT](LICENSE)
