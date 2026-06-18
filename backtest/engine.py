"""
回测引擎 - 日频净值计算

根据周频调仓信号，模拟日频组合净值变化，考虑交易成本和动态回撤止盈。
"""

import pandas as pd
import numpy as np

CASH_ETF = "511880"


def run_backtest(price_df: pd.DataFrame,
                 signals: pd.DataFrame,
                 initial_capital: float = 1_000_000,
                 commission_rate: float = 0.00025,
                 slippage: float = 0.0001,
                 trailing_stop_pct: float = None) -> pd.DataFrame:
    """
    执行回测

    参数:
        price_df: 日频收盘价矩阵 (date × ETF代码)
        signals: 周频调仓权重矩阵 (周五 × ETF代码)
        initial_capital: 初始资金
        commission_rate: 佣金费率 (单边)
        slippage: 滑点
        trailing_stop_pct: 动态回撤止盈阈值 (None=不启用), 如 0.05 表示从最高点回落5%止盈

    返回:
        DataFrame (date × columns):
            nav, daily_return, turnover, w_{code}, stop_flag
    """
    etf_codes = list(price_df.columns)
    daily_returns = price_df.pct_change().fillna(0)

    signals = signals.sort_index()
    signal_dates = signals.index.tolist()

    # 第一步：构建原始周频权重矩阵
    raw_weights = pd.DataFrame(0.0, index=price_df.index, columns=etf_codes)

    for i, date in enumerate(signal_dates):
        target_weights = signals.loc[date]
        if i < len(signal_dates) - 1:
            end_date = signal_dates[i + 1]
        else:
            end_date = price_df.index[-1] + pd.Timedelta(days=1)
        valid_dates = price_df.index[(price_df.index > date) & (price_df.index < end_date)]
        if len(valid_dates) == 0:
            continue
        execution_date = valid_dates[0]
        mask = (raw_weights.index >= execution_date) & (raw_weights.index < end_date)
        raw_weights.loc[mask] = target_weights.values

    if len(signal_dates) > 0:
        first_exec = price_df.index[price_df.index > signal_dates[0]]
        if len(first_exec) > 0:
            mask = raw_weights.index < first_exec[0]
            if CASH_ETF in etf_codes:
                raw_weights.loc[mask, CASH_ETF] = 1.0
            else:
                raw_weights.loc[mask] = 1.0 / len(etf_codes)

    # 第二步：逐日模拟 + 动态回撤止盈
    daily_weights = pd.DataFrame(0.0, index=price_df.index, columns=etf_codes)
    stop_flags = pd.Series(0, index=price_df.index)
    stop_count = 0

    prev_weights = pd.Series(0.0, index=etf_codes)
    # 跟踪每只ETF持仓期间的最高价
    entry_highs = {c: 0.0 for c in etf_codes if c != CASH_ETF}
    # 标记哪些ETF的entry_high需要在下一天重置（当天刚被信号买入的）
    just_entered = {c: False for c in etf_codes if c != CASH_ETF}

    for i, date in enumerate(price_df.index):
        target_w = raw_weights.loc[date].copy()

        # 检测信号日（周五调仓生效日）：重置止盈跟踪
        is_signal_day = False
        for sd in signal_dates:
            if date > sd:
                valid = price_df.index[(price_df.index > sd) & (price_df.index < (signal_dates[signal_dates.index(sd)+1] if signal_dates.index(sd)+1 < len(signal_dates) else price_df.index[-1]+pd.Timedelta(days=1)))]
                if len(valid) > 0 and valid[0] == date:
                    is_signal_day = True
                    break

        # --- 动态回撤止盈 ---
        if trailing_stop_pct is not None and i > 0:
            prev_close = price_df.shift(1).loc[date]

            for code in etf_codes:
                if code == CASH_ETF:
                    continue

                had_position = prev_weights.get(code, 0) > 0

                if had_position:
                    close_val = prev_close.get(code)
                    if pd.isna(close_val):
                        continue

                    # 检测是否刚在上一期被买入（weight从0变为>0）
                    if i > 1:
                        two_days_ago_w = daily_weights.iloc[i-2].get(code, 0) if len(daily_weights) > i-1 else 0
                    else:
                        two_days_ago_w = 0

                    # 如果是信号日且权重变化了，重置entry_high
                    weight_changed = abs(target_w.get(code, 0) - prev_weights.get(code, 0)) > 0.001
                    if weight_changed or is_signal_day:
                        entry_highs[code] = close_val
                    else:
                        # 更新持仓期间最高价
                        if close_val > entry_highs[code]:
                            entry_highs[code] = close_val

                    # 检查是否从最高点回落超过阈值
                    if entry_highs[code] > 0:
                        drawdown_from_high = (entry_highs[code] - close_val) / entry_highs[code]
                        if drawdown_from_high >= trailing_stop_pct:
                            stopped_w = target_w.get(code, 0)
                            if stopped_w > 0:
                                target_w[code] = 0.0
                                if CASH_ETF in etf_codes:
                                    target_w[CASH_ETF] = target_w.get(CASH_ETF, 0) + stopped_w
                                stop_flags.loc[date] = 1
                                stop_count += 1
                                entry_highs[code] = 0.0

                # 如果从无持仓变为有持仓（通过信号买入），标记需要重置
                will_hold = target_w.get(code, 0) > 0
                if not had_position and will_hold:
                    if date in price_df.index:
                        entry_highs[code] = price_df.loc[date, code]

        # 记录
        daily_weights.loc[date] = target_w
        prev_weights = target_w

    # 第三步：收益与成本
    portfolio_return = (daily_weights * daily_returns).sum(axis=1)
    weight_changes = daily_weights.diff().abs()
    turnover = weight_changes.sum(axis=1) / 2
    cost = turnover * (commission_rate + slippage)
    portfolio_return = portfolio_return - cost
    nav = (1 + portfolio_return).cumprod() * initial_capital

    result = pd.DataFrame({
        "nav": nav,
        "daily_return": portfolio_return,
        "turnover": turnover,
        "stop_flag": stop_flags,
    }, index=price_df.index)

    for code in etf_codes:
        result[f"w_{code}"] = daily_weights[code]

    result.attrs["stop_count"] = stop_count
    return result


def run_benchmark(price_series: pd.Series,
                  initial_capital: float = 1_000_000) -> pd.Series:
    """计算基准指数净值"""
    bench_ret = price_series.pct_change().fillna(0)
    bench_nav = (1 + bench_ret).cumprod() * initial_capital
    return bench_nav
