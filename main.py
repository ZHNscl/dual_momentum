#!/usr/bin/env python3
"""
双动量交易策略 - ETF池对比
固定: 1×20日动量 + 10%动态止盈 + Top2 70/30
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import numpy as np

from config import (
    ETF_POOL, MOMENTUM_UNIT, TOP_N, TOP_WEIGHTS, START_DATE, END_DATE,
    INITIAL_CAPITAL, COMMISSION_RATE, SLIPPAGE, RISK_FREE_RATE, OUTPUT_DIR,
)
from data.fetcher import build_unified_dataframe, _code_to_sina_symbol
from strategy.dual_momentum import generate_signals, compute_strategy_stats
from backtest.engine import run_backtest, run_benchmark
from utils.metrics import full_metrics
from visualization.charts import (
    plot_nav_curves, plot_drawdown, plot_annual_heatmap,
    plot_metrics_comparison, plot_holdings_distribution,
)

BEST_STOP = 0.10  # 最优止盈阈值
BEST_LB = 1       # 最优回看周期


def build_pools():
    """构建不同的ETF池"""
    base = {k: v for k, v in ETF_POOL.items()
            if k not in ("159995", "159819")}  # 原池

    pools = {
        "原池(8只)": base,
        "+半导体(9只)": {**base, "159995": ETF_POOL["159995"]},
        "+AI(9只)":     {**base, "159819": ETF_POOL["159819"]},
        "全加(10只)":   ETF_POOL,
    }
    return pools


def run_one_pool(pool_name, pool_etfs, bench_series):
    """对单个ETF池跑一次回测"""
    print(f"\n{'─'*50}")
    print(f"  🔄 {pool_name}")
    print(f"{'─'*50}")

    codes = list(pool_etfs.keys())
    data = build_unified_dataframe(
        etf_codes=codes, start_date=START_DATE, end_date=END_DATE, use_cache=True)
    price_df = data["price"]

    # 确保基准一致
    bs = bench_series if bench_series is not None else data.get("benchmark")

    signals = generate_signals(price_df, BEST_LB, TOP_N, TOP_WEIGHTS,
                               cash_etf="511880", bond_etf="511010")
    if signals.empty:
        return None

    stats = compute_strategy_stats(signals, BEST_LB)
    bt_result = run_backtest(price_df, signals, INITIAL_CAPITAL, COMMISSION_RATE, SLIPPAGE,
                             trailing_stop_pct=BEST_STOP)

    bench_nav = None
    if bs is not None and not bs.empty:
        bench_nav = run_benchmark(bs, INITIAL_CAPITAL)

    metrics = full_metrics(bt_result["daily_return"], bt_result["nav"], RISK_FREE_RATE)

    print(f"  累计收益率:    {metrics['total_return']:>10.2%}")
    print(f"  年化收益率:    {metrics['annualized_return']:>10.2%}")
    print(f"  年化波动率:    {metrics['annualized_volatility']:>10.2%}")
    print(f"  夏普比率:      {metrics['sharpe_ratio']:>10.2f}")
    print(f"  最大回撤:      {metrics['max_drawdown']:>10.2%}")
    print(f"  卡玛比率:      {metrics['calmar_ratio']:>10.2f}")
    print(f"  月度胜率:      {metrics['monthly_win_rate']:>10.2%}")
    print(f"  信号避险:      {stats.get('safe_haven_count', 0)} 次")
    print(f"  回撤止盈:      {bt_result.attrs.get('stop_count', 0)} 次")

    # 每只ETF被选中次数
    sel = stats.get("selection_count", {})
    top_etfs = sorted(sel.items(), key=lambda x: x[1], reverse=True)[:5]
    print(f"\n  📌 被选中次数 Top5:")
    for code, cnt in top_etfs:
        name = pool_etfs.get(code, {}).get("name", code)
        bar = "█" * max(1, cnt // 5)
        print(f"     {code} {name:<10} {cnt:>4}次 {bar}")

    ar = metrics.get("annual_returns", {})
    if ar:
        hdr = False
        for year in sorted(ar.keys()):
            ret = ar[year]
            if not hdr:
                print(f"\n  📅 年度收益:")
                hdr = True
            marker = "🟢" if ret > 0 else "🔴"
            print(f"     {marker} {year}: {ret:+.2%}")

    return {
        "label": pool_name,
        "metrics": metrics,
        "bt_result": bt_result,
        "nav": bt_result["nav"],
        "benchmark_nav": bench_nav,
        "daily_return": bt_result["daily_return"],
        "strategy_stats": stats,
        "annual_returns": metrics.get("annual_returns", {}),
    }


def main():
    print("""
╔══════════════════════════════════════════════════════════════╗
║     双动量策略 - ETF池对比（1×20日 + 10%止盈 + 70/30）      ║
╚══════════════════════════════════════════════════════════════╝
""")
    pools = build_pools()

    # 先获取基准
    print(f"获取基准指数...")
    from data.fetcher import fetch_benchmark_daily
    bench_df = fetch_benchmark_daily(START_DATE.replace("-", ""), END_DATE.replace("-", ""))
    bench_series = bench_df.set_index("date")["close"] if not bench_df.empty else pd.Series(dtype=float)

    print(f"\n{'='*60}")
    print(f"  回测: {BEST_LB}×{MOMENTUM_UNIT}日 | 10%回撤止盈 | Top2 70/30 | {INITIAL_CAPITAL:,}元")
    print(f"{'='*60}")

    results = {}
    for name, etfs in pools.items():
        res = run_one_pool(name, etfs, bench_series)
        if res:
            results[name] = res

    # 综合对比
    print(f"\n\n{'='*70}")
    print(f"  📊 ETF池对比")
    print(f"{'='*70}")

    headers = ["池子", "标的数", "累计收益", "年化收益", "夏普", "最大回撤", "卡玛", "胜率"]
    col_widths = [12, 6, 10, 10, 6, 10, 6, 6]
    sep = "+" + "+".join("-" * w for w in col_widths) + "+"
    print(sep)
    print("|" + "|".join(f"{h:^{w}}" for h, w in zip(headers, col_widths)) + "|")
    print(sep)

    best_sharpe = (None, -999)
    best_return = (None, -999)
    best_calmar = (None, -999)

    for name, res in results.items():
        m = res["metrics"]
        n_etfs = len(pools[name])
        row = [
            name, str(n_etfs),
            f"{m['total_return']:>8.2%}", f"{m['annualized_return']:>8.2%}",
            f"{m['sharpe_ratio']:>4.2f}", f"{m['max_drawdown']:>8.2%}",
            f"{m['calmar_ratio']:>4.2f}", f"{m['monthly_win_rate']:>4.2%}",
        ]
        print("|" + "|".join(f"{c:^{w}}" for c, w in zip(row, col_widths)) + "|")

        if m["sharpe_ratio"] > best_sharpe[1]: best_sharpe = (name, m["sharpe_ratio"])
        if m["annualized_return"] > best_return[1]: best_return = (name, m["annualized_return"])
        if m["calmar_ratio"] > best_calmar[1]: best_calmar = (name, m["calmar_ratio"])

    print(sep)
    print(f"\n  🏆 最高夏普: {best_sharpe[0]} ({best_sharpe[1]:.2f})")
    print(f"  🏆 最高年化: {best_return[0]} ({best_return[1]:.2%})")
    print(f"  🏆 最高卡玛: {best_calmar[0]} ({best_calmar[1]:.2f})")

    # 年度对比
    print(f"\n  📅 各池年度收益:")
    all_years = set()
    for res in results.values():
        all_years.update(res["annual_returns"].keys())
    all_years = sorted(all_years)
    names = list(results.keys())

    print(f"    {'年份':<6}", end="")
    for n in names:
        print(f" {n:>14}", end="")
    print()
    print(f"    {'-' * (6 + 15 * len(names))}")
    for year in all_years:
        print(f"    {year:<6}", end="")
        for n in names:
            ret = results[n]["annual_returns"].get(year, 0)
            print(f" {ret:>+13.2%}", end="")
        print()

    # 图表
    print(f"\n{'='*60}")
    print(f"  生成图表...")
    print(f"{'='*60}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    chart_data = {}
    for name, res in results.items():
        chart_data[name] = {
            "nav": res["nav"], "label": name,
            "benchmark_nav": res.get("benchmark_nav"),
            "annual_returns": res["annual_returns"],
        }

    f = plot_nav_curves(chart_data, save_path=os.path.join(OUTPUT_DIR, "nav_comparison.png"))
    print(f"  ✅ 净值曲线: {f}")
    dd = {k: {"nav": v["nav"], "label": v["label"]} for k, v in chart_data.items()}
    f = plot_drawdown(dd, save_path=os.path.join(OUTPUT_DIR, "drawdown.png"))
    print(f"  ✅ 回撤曲线: {f}")
    f = plot_annual_heatmap(chart_data, save_path=os.path.join(OUTPUT_DIR, "annual_heatmap.png"))
    print(f"  ✅ 年度热力图: {f}")

    df_rows = []
    for name, res in results.items():
        m = res["metrics"]
        df_rows.append({"参数": name, "累计收益率": m["total_return"],
                         "年化收益率": m["annualized_return"], "年化波动率": m["annualized_volatility"],
                         "夏普比率": m["sharpe_ratio"], "最大回撤": m["max_drawdown"],
                         "卡玛比率": m["calmar_ratio"], "月度胜率": m["monthly_win_rate"]})
    metrics_df = pd.DataFrame(df_rows).set_index("参数")
    f = plot_metrics_comparison(metrics_df, save_path=os.path.join(OUTPUT_DIR, "metrics_comparison.png"))
    if f: print(f"  ✅ 指标对比: {f}")
    csv_path = os.path.join(OUTPUT_DIR, "metrics_summary.csv")
    metrics_df.to_csv(csv_path, float_format="%.6f")
    print(f"  ✅ 指标汇总: {csv_path}")

    print(f"\n{'='*60}")
    print(f"  🎉 完成！")
    print(f"{'='*60}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
