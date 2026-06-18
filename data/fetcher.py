"""
数据获取模块 - 基于 akshare 获取 A 股 ETF 日线数据
支持本地 CSV 缓存，避免重复 API 调用
"""

import os
import time
import pandas as pd
import akshare as ak

from config import ETF_POOL, BENCHMARK, CACHE_DIR, START_DATE, END_DATE


def _cache_path(code: str) -> str:
    """获取本地缓存文件路径"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{code}.csv")


def fetch_etf_daily(code: str, start_date: str = "20100101", end_date: str = None,
                     use_cache: bool = True) -> pd.DataFrame:
    """
    获取单只 ETF 的日线数据（前复权）

    参数:
        code: ETF 代码 (如 "510300")
        start_date: 起始日期 YYYYMMDD
        end_date: 结束日期 YYYYMMDD
        use_cache: 是否使用本地缓存

    返回:
        DataFrame, 包含 date, open, high, low, close, volume 列
    """
    if end_date is None:
        from datetime import datetime
        end_date = datetime.now().strftime("%Y%m%d")

    cache_file = _cache_path(code)

    # 全量拉取（新浪接口返回所有历史数据）
    if not use_cache or not os.path.exists(cache_file):
        for attempt in range(3):
            try:
                df = _fetch_from_sina(code)
                if not df.empty:
                    if use_cache:
                        df.to_csv(cache_file, index=False)
                    return df
            except Exception as e:
                print(f"  [重试 {attempt+1}/3] 获取 {code} 失败: {e}")
                if attempt < 2:
                    time.sleep(2)

        print(f"  [警告] 无法获取 {code} 数据，将使用缓存或返回空数据")
        if os.path.exists(cache_file):
            return pd.read_csv(cache_file, parse_dates=["date"])
        return pd.DataFrame()

    # 使用缓存
    df = pd.read_csv(cache_file, parse_dates=["date"])
    return df


def _code_to_sina_symbol(code: str) -> str:
    """将 ETF 代码转换为新浪接口所需的 symbol 格式"""
    if code.startswith("5"):
        return f"sh{code}"
    elif code.startswith("1"):
        return f"sz{code}"
    else:
        return f"sh{code}"


def _fetch_from_sina(code: str) -> pd.DataFrame:
    """通过 akshare 新浪数据源拉取 ETF 日线数据（前复权）"""
    symbol = _code_to_sina_symbol(code)
    df = ak.fund_etf_hist_sina(symbol=symbol)

    if df.empty:
        return df

    # 标准化列名 (新浪返回的列名已经是英文 date/open/high/low/close/volume)
    # 保留需要的列
    cols = ["date", "open", "high", "low", "close", "volume"]
    df = df[[c for c in cols if c in df.columns]]

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    return df


def fetch_benchmark_daily(start_date: str = "20100101", end_date: str = None) -> pd.DataFrame:
    """
    获取沪深300指数日线数据作为基准

    返回:
        DataFrame, 包含 date, close 列
    """
    if end_date is None:
        from datetime import datetime
        end_date = datetime.now().strftime("%Y%m%d")

    cache_file = _cache_path(BENCHMARK)

    if os.path.exists(cache_file):
        df = pd.read_csv(cache_file, parse_dates=["date"])
        return df

    for attempt in range(3):
        try:
            df = ak.stock_zh_index_daily(symbol=f"sh{BENCHMARK}")
            if df.empty:
                continue
            df["date"] = pd.to_datetime(df["date"])
            df = df[["date", "close"]].sort_values("date")
            df.to_csv(cache_file, index=False)
            return df
        except Exception as e:
            print(f"  [重试 {attempt+1}/3] 获取基准指数失败: {e}")
            if attempt < 2:
                time.sleep(2)

    return pd.DataFrame()


def build_unified_dataframe(etf_codes: list = None,
                            start_date: str = None,
                            end_date: str = None,
                            use_cache: bool = True) -> dict:
    """
    构建所有 ETF 的统一数据集

    参数:
        etf_codes: ETF 代码列表，默认使用 ETF_POOL 中所有代码
        start_date: 起始日期 (YYYYMMDD 或 YYYY-MM-DD)
        end_date: 结束日期
        use_cache: 是否使用缓存

    返回:
        {
            "price": DataFrame (date × code), 收盘价矩阵
            "benchmark": DataFrame, 基准指数
            "metadata": dict, ETF 元数据
        }
    """
    if etf_codes is None:
        etf_codes = list(ETF_POOL.keys())

    if start_date is None:
        start_date = START_DATE.replace("-", "")
    else:
        start_date = start_date.replace("-", "")

    if end_date is None:
        end_date = END_DATE.replace("-", "")
    else:
        end_date = end_date.replace("-", "")

    print(f"\n{'='*60}")
    print(f"📊 数据获取: {start_date} ~ {end_date}")
    print(f"{'='*60}")

    price_dict = {}

    for code in etf_codes:
        name = ETF_POOL.get(code, {}).get("name", code)
        print(f"  获取 {code} {name} ...")
        df = fetch_etf_daily(code, start_date, end_date, use_cache)
        if not df.empty:
            price_dict[code] = df.set_index("date")["close"]

    if not price_dict:
        raise RuntimeError("未能获取任何 ETF 数据！请检查网络和 akshare 版本")

    # 构建收盘价矩阵
    price_df = pd.DataFrame(price_dict).sort_index()

    # 确保数据从 start_date 开始（转换为 pandas 日期）
    start_dt = pd.to_datetime(start_date)
    price_df = price_df[price_df.index >= start_dt]

    # 前向填充缺失值（处理不同 ETF 交易日差异）
    price_df = price_df.ffill()

    print(f"\n  ✅ 共获取 {len(price_df.columns)} 只 ETF，{len(price_df)} 个交易日")
    print(f"  📅 数据范围: {price_df.index[0].strftime('%Y-%m-%d')} ~ {price_df.index[-1].strftime('%Y-%m-%d')}")

    # 获取基准指数
    print(f"\n  获取基准指数 {BENCHMARK} ...")
    bench_df = fetch_benchmark_daily(start_date, end_date)
    if not bench_df.empty:
        bench_df = bench_df.set_index("date")["close"]
        bench_df = bench_df[bench_df.index >= start_dt]

    return {
        "price": price_df,
        "benchmark": bench_df,
        "metadata": ETF_POOL,
    }
