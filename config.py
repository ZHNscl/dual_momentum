"""
双动量交易策略 - 配置文件
"""

from datetime import datetime

# ============================================================
# ETF 投资池
# ============================================================
ETF_POOL = {
    "510300": {"name": "沪深300ETF", "category": "宽基大盘", "type": "stock"},
    "510500": {"name": "中证500ETF", "category": "宽基中盘", "type": "stock"},
    "159915": {"name": "创业板ETF", "category": "宽基成长", "type": "stock"},
    "588000": {"name": "科创50ETF", "category": "宽基科技", "type": "stock"},
    "159995": {"name": "半导体ETF",  "category": "行业科技", "type": "stock"},
    "159819": {"name": "人工智能ETF","category": "行业科技", "type": "stock"},
    "159516": {"name": "半导体设备ETF","category": "行业科技", "type": "stock"},
    "513100": {"name": "纳指ETF",   "category": "海外QDII", "type": "stock"},
    "518880": {"name": "黄金ETF",   "category": "商品避险", "type": "commodity"},
    "511010": {"name": "国债ETF",   "category": "债券避险", "type": "bond"},
    "511880": {"name": "银华日利",   "category": "货币现金", "type": "cash"},
}

# ============================================================
# 策略参数（最优配置）
# ============================================================
LOOKBACK_PERIODS = [1, 3, 6, 12]       # 回看周期（×20个交易日）
MOMENTUM_UNIT = 20                     # 动量基础单位（交易日）
TOP_N = 1                              # 每期持有 Top 1 ETF
TOP_WEIGHTS = [1.0]                    # Top1 100% 仓位
REBALANCE_FREQ = "W-FRI"              # 调仓频率 W-FRI=每周五

# ============================================================
# 回测参数
# ============================================================
START_DATE = "2018-01-01"              # 回测起始日期
END_DATE   = datetime.now().strftime("%Y-%m-%d")  # 回测结束日期（今天）

COMMISSION_RATE = 0.00025              # ETF 单边佣金 万2.5
SLIPPAGE = 0.0001                      # 滑点 万1

INITIAL_CAPITAL = 20_000               # 初始资金 2万

RISK_FREE_RATE = 0.02                  # 无风险利率 (用于夏普比率)

# ============================================================
# 基准
# ============================================================
BENCHMARK = "000300"                   # 沪深300指数代码
BENCHMARK_NAME = "沪深300"

# ============================================================
# 输出
# ============================================================
OUTPUT_DIR = "output"
CACHE_DIR = "output/cache"

# 中文字体设置
PLT_STYLE = {
    "font.sans-serif": ["WenQuanYi Micro Hei", "SimHei", "DejaVu Sans"],
    "axes.unicode_minus": False,
    "figure.dpi": 150,
}
