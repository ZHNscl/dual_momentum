"""
可视化模块 - 生成策略分析图表
"""

import os
import matplotlib
matplotlib.use("Agg")  # 非交互式后端
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import seaborn as sns
import pandas as pd
import numpy as np

from config import PLT_STYLE, OUTPUT_DIR

# 应用样式
for key, val in PLT_STYLE.items():
    try:
        plt.rcParams[key] = val
    except Exception:
        pass

# 设置中文字体
import matplotlib.font_manager as fm
_chinese_fonts = [f.name for f in fm.fontManager.ttflist if
                  any(k in f.name for k in ['WenQuanYi', 'WenQuanYi Micro Hei', 'SimHei'])]
if not _chinese_fonts:
    # fallback: try fuzzy match
    _chinese_fonts = [f.name for f in fm.fontManager.ttflist if 'CJK' in f.name]
if _chinese_fonts:
    plt.rcParams["font.sans-serif"] = [_chinese_fonts[0]] + ["DejaVu Sans"]
    plt.rcParams["font.family"] = "sans-serif"


def _ensure_output_dir():
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def plot_nav_curves(results: dict, save_path: str = None):
    """
    绘制多周期策略净值 vs 基准对比图

    参数:
        results: {lookback_months: {"nav": Series, "label": str, "benchmark_nav": Series or None}}
    """
    _ensure_output_dir()
    fig, ax = plt.subplots(figsize=(14, 7))

    colors = plt.cm.tab10(np.linspace(0, 1, len(results) + 1))

    bench_nav = None
    for i, (lb, res) in enumerate(sorted(results.items())):
        nav_series = res["nav"]
        # 归一化到 1.0
        nav_norm = nav_series / nav_series.iloc[0]
        ax.plot(nav_norm.index, nav_norm, color=colors[i], linewidth=1.5,
                label=res.get("label", f"{lb}个月动量"), alpha=0.85)
        if bench_nav is None and res.get("benchmark_nav") is not None:
            bench_nav = res["benchmark_nav"]

    if bench_nav is not None and not bench_nav.empty:
        bench_norm = bench_nav / bench_nav.iloc[0]
        ax.plot(bench_norm.index, bench_norm, color="gray", linewidth=1.2,
                linestyle="--", label="沪深300基准", alpha=0.7)

    ax.axhline(y=1.0, color="black", linewidth=0.5, linestyle=":")

    ax.set_title("双动量策略 - 多周期参数净值对比", fontsize=14, fontweight="bold")
    ax.set_xlabel("日期")
    ax.set_ylabel("净值 (初始=1.0)")
    ax.legend(loc="upper left", fontsize=9)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter('%.2f'))
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    if save_path is None:
        save_path = os.path.join(OUTPUT_DIR, "nav_comparison.png")
    fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return save_path


def plot_drawdown(results: dict, save_path: str = None):
    """
    绘制回撤曲线

    参数:
        results: {lookback_months: {"nav": Series, "label": str}}
    """
    _ensure_output_dir()
    fig, ax = plt.subplots(figsize=(14, 7))

    colors = plt.cm.tab10(np.linspace(0, 1, len(results)))

    for i, (lb, res) in enumerate(sorted(results.items())):
        nav = res["nav"]
        cumulative_max = nav.cummax()
        drawdown = (nav - cumulative_max) / cumulative_max * 100
        ax.fill_between(drawdown.index, drawdown, 0, color=colors[i], alpha=0.3)
        ax.plot(drawdown.index, drawdown, color=colors[i], linewidth=1,
                label=res.get("label", f"{lb}个月"), alpha=0.85)

    ax.set_title("双动量策略 - 回撤曲线", fontsize=14, fontweight="bold")
    ax.set_xlabel("日期")
    ax.set_ylabel("回撤 (%)")
    ax.legend(loc="lower left", fontsize=9)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter('%.0f%%'))
    ax.grid(True, alpha=0.3)
    ax.axhline(y=0, color="black", linewidth=0.5)

    plt.tight_layout()
    if save_path is None:
        save_path = os.path.join(OUTPUT_DIR, "drawdown.png")
    fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return save_path


def plot_annual_heatmap(results: dict, save_path: str = None):
    """
    绘制各周期年度收益热力图

    参数:
        results: {lookback_months: {"annual_returns": {year: return}, "label": str}}
    """
    _ensure_output_dir()

    # 构建数据矩阵
    all_years = set()
    for res in results.values():
        all_years.update(res.get("annual_returns", {}).keys())
    all_years = sorted(all_years)
    labels = [res.get("label", str(lb)) for lb, res in sorted(results.items())]
    lbs = sorted(results.keys())

    data = []
    for lb in lbs:
        ar = results[lb].get("annual_returns", {})
        data.append([ar.get(y, np.nan) * 100 for y in all_years])

    df_heatmap = pd.DataFrame(data, index=labels, columns=all_years)

    fig, ax = plt.subplots(figsize=(12, max(4, len(labels) * 0.8)))

    cmap = sns.diverging_palette(10, 130, as_cmap=True)
    sns.heatmap(df_heatmap, annot=True, fmt=".1f", cmap=cmap, center=0,
                linewidths=0.5, cbar_kws={"label": "年度收益 (%)"}, ax=ax)

    ax.set_title("双动量策略 - 年度收益热力图 (%)", fontsize=14, fontweight="bold")
    ax.set_xlabel("年份")
    ax.set_ylabel("策略参数")

    plt.tight_layout()
    if save_path is None:
        save_path = os.path.join(OUTPUT_DIR, "annual_heatmap.png")
    fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return save_path


def plot_metrics_comparison(metrics_summary: pd.DataFrame, save_path: str = None):
    """
    绘制多周期绩效指标对比图

    参数:
        metrics_summary: DataFrame, index=参数描述, columns=指标
    """
    _ensure_output_dir()

    # 选取关键指标
    key_metrics = ["累计收益率", "年化收益率", "夏普比率",
                   "最大回撤", "卡玛比率", "月度胜率"]

    available = [m for m in key_metrics if m in metrics_summary.columns]
    if not available:
        return None

    n = len(available)
    fig, axes = plt.subplots(1, n, figsize=(4 * n, 5))
    if n == 1:
        axes = [axes]

    colors = plt.cm.Set2(np.linspace(0, 1, len(metrics_summary)))

    metric_names = {
        "累计收益率": "累计收益率",
        "年化收益率": "年化收益率",
        "夏普比率": "夏普比率",
        "最大回撤": "最大回撤",
        "卡玛比率": "卡玛比率",
        "月度胜率": "月度胜率",
    }

    for i, metric in enumerate(available):
        ax = axes[i]
        values = metrics_summary[metric]
        labels = metrics_summary.index.tolist()

        bars = ax.bar(range(len(labels)), values, color=colors, edgecolor="white")
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=9)
        ax.set_title(metric_names.get(metric, metric), fontsize=12, fontweight="bold")

        # 数值标注
        for bar, val in zip(bars, values):
            if pd.notna(val):
                is_pct = any(kw in metric for kw in ["收益", "回撤", "胜率"])
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                        f"{val:.2%}" if is_pct else f"{val:.2f}",
                        ha="center", va="bottom", fontsize=8)

        ax.grid(axis="y", alpha=0.3)

    fig.suptitle("双动量策略 - 多周期绩效对比", fontsize=14, fontweight="bold")
    plt.tight_layout()
    if save_path is None:
        save_path = os.path.join(OUTPUT_DIR, "metrics_comparison.png")
    fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return save_path


def plot_holdings_distribution(strategy_stats: dict, save_path: str = None):
    """
    绘制 ETF 被选中频次分布

    参数:
        strategy_stats: {lookback_months: {"selection_count": {code: count}}}
    """
    _ensure_output_dir()

    n_lookbacks = len(strategy_stats)
    if n_lookbacks == 0:
        return None

    fig, axes = plt.subplots(1, n_lookbacks, figsize=(5 * n_lookbacks, 5))
    if n_lookbacks == 1:
        axes = [axes]

    for ax, (lb, stats) in zip(axes, sorted(strategy_stats.items())):
        sel = stats.get("selection_count", {})
        if not sel:
            continue
        codes = list(sel.keys())
        counts = [sel[c] for c in codes]

        colors = plt.cm.Set3(np.linspace(0, 1, len(codes)))
        wedges, texts, autotexts = ax.pie(counts, labels=codes, autopct="%1.1f%%",
                                          colors=colors, startangle=90)
        ax.set_title(f"{lb}个月动量 - ETF选中分布", fontsize=11, fontweight="bold")

    fig.suptitle("双动量策略 - ETF 持仓分布分析", fontsize=14, fontweight="bold")
    plt.tight_layout()
    if save_path is None:
        save_path = os.path.join(OUTPUT_DIR, "holdings_distribution.png")
    fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return save_path
