"""
绩效指标计算模块

计算各类量化投资绩效指标：
- 年化收益率、年化波动率
- 夏普比率、卡玛比率
- 最大回撤、回撤持续时间
- 月度胜率
- 年度收益汇总
"""

import pandas as pd
import numpy as np

TRADING_DAYS_PER_YEAR = 252


def annualized_return(daily_returns: pd.Series) -> float:
    """年化收益率"""
    if daily_returns.empty:
        return 0.0
    cumulative = (1 + daily_returns).prod()
    years = len(daily_returns) / TRADING_DAYS_PER_YEAR
    if years <= 0:
        return 0.0
    return cumulative ** (1 / years) - 1


def annualized_volatility(daily_returns: pd.Series) -> float:
    """年化波动率"""
    if daily_returns.empty:
        return 0.0
    return daily_returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR)


def sharpe_ratio(daily_returns: pd.Series, risk_free_rate: float = 0.02) -> float:
    """夏普比率"""
    ann_ret = annualized_return(daily_returns)
    ann_vol = annualized_volatility(daily_returns)
    if ann_vol == 0:
        return 0.0
    return (ann_ret - risk_free_rate) / ann_vol


def max_drawdown(nav: pd.Series) -> dict:
    """
    最大回撤分析

    返回:
        {
            "max_dd": float, 最大回撤比例
            "peak_date": datetime, 峰值日期
            "trough_date": datetime, 谷底日期
            "recovery_date": datetime or None, 恢复日期
            "dd_duration": int, 回撤持续天数
        }
    """
    if nav.empty:
        return {"max_dd": 0.0}

    cumulative_max = nav.cummax()
    drawdown = (nav - cumulative_max) / cumulative_max

    max_dd_val = drawdown.min()
    trough_date = drawdown.idxmin()

    # 峰日期：谷底之前的历史最高点
    peak_date = nav.loc[:trough_date].idxmax()

    # 恢复日期：回撤后首次超过之前峰值
    recovery_date = None
    if peak_date in nav.index:
        peak_level = nav.loc[peak_date]
        after_trough = nav.loc[trough_date:]
        recovered = after_trough[after_trough >= peak_level]
        if not recovered.empty:
            recovery_date = recovered.index[0]

    dd_duration = (trough_date - peak_date).days

    return {
        "max_dd": max_dd_val,
        "peak_date": peak_date,
        "trough_date": trough_date,
        "recovery_date": recovery_date,
        "dd_duration": dd_duration,
    }


def calmar_ratio(daily_returns: pd.Series, nav: pd.Series) -> float:
    """卡玛比率 = 年化收益率 / |最大回撤|"""
    ann_ret = annualized_return(daily_returns)
    dd = max_drawdown(nav)
    max_dd_val = dd["max_dd"]
    if max_dd_val == 0 or np.isnan(max_dd_val):
        return 0.0
    return ann_ret / abs(max_dd_val)


def monthly_win_rate(daily_returns: pd.Series) -> float:
    """月度胜率"""
    if daily_returns.empty:
        return 0.0
    monthly_returns = daily_returns.resample("ME").apply(lambda x: (1 + x).prod() - 1)
    wins = (monthly_returns > 0).sum()
    total = len(monthly_returns)
    return wins / total if total > 0 else 0.0


def annual_returns(daily_returns: pd.Series) -> pd.Series:
    """年度收益汇总"""
    if daily_returns.empty:
        return pd.Series(dtype=float)
    yearly = daily_returns.resample("YE").apply(lambda x: (1 + x).prod() - 1)
    yearly.index = yearly.index.year
    return yearly


def total_return(daily_returns: pd.Series) -> float:
    """累计总收益率"""
    if daily_returns.empty:
        return 0.0
    return (1 + daily_returns).prod() - 1


def full_metrics(daily_returns: pd.Series, nav: pd.Series, risk_free_rate: float = 0.02) -> dict:
    """
    计算完整绩效指标

    返回:
        dict, 包含所有关键指标
    """
    ann_ret = annualized_return(daily_returns)
    ann_vol = annualized_volatility(daily_returns)
    sharpe = sharpe_ratio(daily_returns, risk_free_rate)
    dd_info = max_drawdown(nav)
    calmar = calmar_ratio(daily_returns, nav)
    win_rate = monthly_win_rate(daily_returns)
    total_ret = total_return(daily_returns)
    yearly = annual_returns(daily_returns)

    return {
        "total_return": total_ret,
        "annualized_return": ann_ret,
        "annualized_volatility": ann_vol,
        "sharpe_ratio": sharpe,
        "max_drawdown": dd_info["max_dd"],
        "max_dd_duration_days": dd_info["dd_duration"],
        "peak_date": dd_info["peak_date"],
        "trough_date": dd_info["trough_date"],
        "calmar_ratio": calmar,
        "monthly_win_rate": win_rate,
        "annual_returns": yearly.to_dict(),
    }
