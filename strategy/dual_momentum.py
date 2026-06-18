"""
双动量交易策略 - 核心算法

策略逻辑:
  1. 绝对动量（趋势过滤）: N×20日涨幅 > 0 才入选
  2. 相对动量（截面比较）: 在通过筛选的 ETF 中按涨幅排名
  3. 持仓: Top1 70% + Top2 30%（仅1只通过则100%）
  4. 避险: 无 ETF 通过筛选时 → 全部持有货币 ETF（511880）
  5. 调仓: 每周五收盘
"""

import pandas as pd
import numpy as np
from config import MOMENTUM_UNIT, TOP_WEIGHTS

# 货币 ETF（现金替代）
CASH_ETF = "511880"
# 国债 ETF（用作绝对动量的无风险基准/门槛）
BOND_ETF = "511010"


def calculate_momentum_returns(price_df: pd.DataFrame, lookback_periods: int) -> pd.DataFrame:
    """
    计算各 ETF 在每周五的 N×20 日涨幅动量

    参数:
        price_df: 收盘价矩阵, index=date, columns=ETF代码
        lookback_periods: 回看周期数（每个周期 = MOMENTUM_UNIT 个交易日）

    返回:
        DataFrame, 每行为一个调仓日(周五)，每列为一个 ETF 的动量涨幅(小数)
    """
    lookback_days = lookback_periods * MOMENTUM_UNIT
    if price_df.empty:
        return pd.DataFrame()

    # 获取每周五
    fridays = price_df.resample("W-FRI").last().index

    momentum_rows = {}
    for fri_date in fridays:
        if fri_date not in price_df.index:
            # 找最近交易日（如周五是假期则取前一个交易日）
            nearby = price_df.index[price_df.index <= fri_date]
            if len(nearby) == 0:
                continue
            fri_date = nearby[-1]

        # 回看 N×20 个交易日前的价格
        iloc_cur = price_df.index.get_loc(fri_date)
        iloc_lookback = iloc_cur - lookback_days

        if iloc_lookback < 0:
            continue  # 数据不足，跳过

        lookback_date = price_df.index[iloc_lookback]
        price_now = price_df.loc[fri_date]
        price_past = price_df.loc[lookback_date]

        momentum = (price_now / price_past) - 1
        momentum_rows[fri_date] = momentum

    if not momentum_rows:
        return pd.DataFrame()

    momentum_df = pd.DataFrame(momentum_rows).T
    momentum_df.index.name = "date"
    return momentum_df.dropna(how="all")


def absolute_momentum_filter(momentum: pd.Series, hurdle: float = 0.0) -> pd.Series:
    """
    绝对动量过滤器: 涨幅 > 国债同期涨幅 才入选（经典双动量做法）

    参数:
        momentum: 某期各 ETF 的动量收益
        hurdle: 门槛收益率（国债 ETF 同期涨幅），默认 0

    返回:
        bool Series, True = 通过筛选
    """
    return momentum > hurdle


def relative_momentum_rank(momentum: pd.Series, filtered_mask: pd.Series = None) -> pd.Series:
    """
    相对动量排名: 按收益降序排名（数值越大排名越前）

    参数:
        momentum: 各 ETF 动量收益
        filtered_mask: 绝对动量筛选结果，None=全部参与排名

    返回:
        Series, 排名 (1=最高收益)
    """
    if filtered_mask is not None:
        # 未通过的排到后面
        filtered = momentum.copy()
        filtered[~filtered_mask] = -np.inf
        return filtered.rank(ascending=False, method="first")
    return momentum.rank(ascending=False, method="first")


def generate_signals(price_df: pd.DataFrame,
                     lookback_periods: int,
                     top_n: int = 2,
                     top_weights: list = None,
                     cash_etf: str = CASH_ETF,
                     bond_etf: str = BOND_ETF) -> pd.DataFrame:
    """
    生成完整交易信号（每周五调仓）

    双动量逻辑:
      绝对动量 = 涨幅 > 国债同期涨幅 → 决定「参不参与」
      相对动量 = 按涨幅排名取 Top2 → 决定「选哪个」

    参数:
        price_df: 收盘价矩阵
        lookback_periods: 回看周期数（×20日）
        top_n: 每期持有数量
        top_weights: 权重列表 [0.7, 0.3], 仅1只通过时自动给100%
        cash_etf: 避险 ETF 代码（货币ETF）
        bond_etf: 国债 ETF 代码（绝对动量基准）

    返回:
        DataFrame, index=调仓日(周五), columns=ETF代码, values=权重
    """
    if top_weights is None:
        top_weights = TOP_WEIGHTS

    if price_df.empty:
        return pd.DataFrame()

    etf_codes = list(price_df.columns)

    # 计算动量收益
    momentum = calculate_momentum_returns(price_df, lookback_periods)
    if momentum.empty:
        return pd.DataFrame()

    # 逐期生成信号
    signals = pd.DataFrame(0.0, index=momentum.index, columns=etf_codes)

    for date_idx, row in momentum.iterrows():
        # 排除 NaN (数据不足)
        valid = row.dropna()
        if valid.empty:
            if cash_etf in etf_codes:
                signals.loc[date_idx, cash_etf] = 1.0
            continue

        # 国债 ETF 同期涨幅作为绝对动量门槛
        hurdle = valid.get(bond_etf, 0.0) if bond_etf in valid.index else 0.0

        # 绝对动量过滤: 涨幅必须 > 国债涨幅
        abs_filter = absolute_momentum_filter(valid, hurdle)

        if abs_filter.sum() == 0:
            # 无 ETF 通过 → 100% 现金
            if cash_etf in etf_codes:
                signals.loc[date_idx, cash_etf] = 1.0
            continue

        # 筛选后的 ETF
        filtered_momentum = valid[abs_filter]

        # 相对动量排名
        rank = relative_momentum_rank(filtered_momentum)

        # 取 Top N
        top_codes = rank.sort_values().head(top_n).index.tolist()
        n_selected = len(top_codes)

        # 分配权重
        if n_selected == 1:
            signals.loc[date_idx, top_codes[0]] = 1.0
        else:
            for i, code in enumerate(top_codes):
                signals.loc[date_idx, code] = top_weights[i]

    return signals


def compute_strategy_stats(signals: pd.DataFrame, lookback_periods: int) -> dict:
    """
    计算策略基本统计信息

    返回:
        dict, 包含调仓次数、平均持仓数、避险频率等
    """
    n_rebalance = len(signals)
    if n_rebalance == 0:
        return {}

    # 每期持仓 ETF 数量
    holdings_count = (signals > 0).sum(axis=1)

    # 避险次数（只持有 CASH_ETF）
    other_etfs = [c for c in signals.columns if c != CASH_ETF]
    if other_etfs:
        is_safe_haven = (signals[other_etfs].sum(axis=1) == 0)
    else:
        is_safe_haven = pd.Series(False, index=signals.index)

    # 每只 ETF 被选中的次数
    selection_count = (signals > 0).sum()

    return {
        "lookback_periods": lookback_periods,
        "n_rebalance": n_rebalance,
        "avg_holdings": holdings_count.mean(),
        "safe_haven_ratio": is_safe_haven.mean(),
        "safe_haven_count": is_safe_haven.sum(),
        "selection_count": selection_count.to_dict(),
    }
