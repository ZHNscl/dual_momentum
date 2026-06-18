"""
离线演示数据模块 - 当 akshare 无法访问时生成模拟价格数据
这样网站在 Render 等境外服务器上也能正常显示
"""

import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta


def generate_mock_price_data(etf_codes, start_date="2018-01-01", end_date=None):
    """
    生成模拟 ETF 日线价格数据（布朗运动 + 趋势）
    返回 {code: DataFrame} 字典，格式与 akshare 返回的一致
    """
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")

    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)
    dates = pd.bdate_range(start=start, end=end)  # 仅工作日

    np.random.seed(42)  # 固定随机种子，保证每次生成结果一致

    result = {}
    base_prices = {
        "510300": 4.50,   # 沪深300ETF
        "510500": 7.20,   # 中证500ETF
        "159915": 2.80,   # 创业板ETF
        "588000": 1.20,   # 科创50ETF
        "159995": 2.50,   # 半导体ETF
        "159819": 1.80,   # 人工智能ETF
        "159516": 3.10,   # 半导体设备ETF
        "513100": 25.00,  # 纳指ETF
        "518880": 15.00,  # 黄金ETF
        "511010": 105.00, # 国债ETF
        "511880": 100.00, # 银华日利
    }

    trend_map = {
        "510300": 0.0003,   # 沪深300 温和上涨
        "510500": 0.0004,
        "159915": 0.0005,
        "588000": 0.0006,
        "159995": 0.0007,
        "159819": 0.0006,
        "159516": 0.0005,
        "513100": 0.0004,
        "518880": 0.0002,
        "511010": 0.0001,
        "511880": 0.00005,
    }

    vol_map = {
        "510300": 0.012,
        "510500": 0.015,
        "159915": 0.018,
        "588000": 0.020,
        "159995": 0.022,
        "159819": 0.020,
        "159516": 0.019,
        "513100": 0.015,
        "518880": 0.010,
        "511010": 0.003,
        "511880": 0.001,
    }

    for code in etf_codes:
        base = base_prices.get(code, 3.00)
        trend = trend_map.get(code, 0.0003)
        vol = vol_map.get(code, 0.015)

        n = len(dates)
        returns = np.random.normal(trend, vol, n)
        # 加入周期性波动（模拟市场周期）
        for i in range(n):
            cycle = 0.002 * np.sin(2 * np.pi * i / 504)  # 约2年周期
            returns[i] += cycle

        prices = [base]
        for r in returns[1:]:
            prices.append(prices[-1] * (1 + r))

        df = pd.DataFrame({
            "date": dates,
            "open": [p * (1 + np.random.normal(0, 0.002)) for p in prices],
            "high": [p * (1 + abs(np.random.normal(0, 0.005))) for p in prices],
            "low":  [p * (1 - abs(np.random.normal(0, 0.005))) for p in prices],
            "close": prices,
            "volume": [int(np.random.normal(50000000, 20000000)) for _ in prices],
        })
        df["date"] = pd.to_datetime(df["date"])
        df.loc[df["volume"] < 0, "volume"] = 0
        result[code] = df

    return result


def generate_mock_benchmark(start_date="2018-01-01", end_date=None):
    """生成模拟沪深300指数数据"""
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")

    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)
    dates = pd.bdate_range(start=start, end=end)

    np.random.seed(99)
    n = len(dates)
    base = 3800
    returns = np.random.normal(0.0002, 0.012, n)
    closes = [base]
    for r in returns[1:]:
        closes.append(closes[-1] * (1 + r))

    return pd.DataFrame({"date": dates, "close": closes})


def build_mock_dataframe(etf_codes, start_date="2018-01-01", end_date=None):
    """生成完整的模拟数据集，接口与 build_unified_dataframe 一致"""
    mock_prices = generate_mock_price_data(etf_codes, start_date, end_date)
    bench_df = generate_mock_benchmark(start_date, end_date)

    price_dict = {}
    for code, df in mock_prices.items():
        price_dict[code] = df.set_index("date")["close"]

    price_df = pd.DataFrame(price_dict).sort_index()
    price_df = price_df[price_df.index >= pd.to_datetime(start_date)]
    price_df = price_df.ffill()

    bench_series = bench_df.set_index("date")["close"]
    bench_series = bench_series[bench_series.index >= pd.to_datetime(start_date)]

    print(f"\n  ✅ 使用模拟数据（离线模式），共 {len(price_df.columns)} 只 ETF")
    print(f"  📅 数据范围: {price_df.index[0].strftime('%Y-%m-%d')} ~ {price_df.index[-1].strftime('%Y-%m-%d')}")

    return {
        "price": price_df,
        "benchmark": bench_series,
        "metadata": None,
    }
