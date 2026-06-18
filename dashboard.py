#!/usr/bin/env python3
"""
双动量策略 - Web 可视化仪表盘（实时刷新版）

用法:
  cd /workspace/dual_momentum && python3 dashboard.py
  浏览器访问 http://localhost:5000

功能:
  - 实时动量排名 | 本周调仓信号 | 交互式图表
  - 手动刷新按钮 + 每5分钟自动刷新
  - Top1 100% 持仓 + 10% 回撤止盈
"""

import sys, os, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import numpy as np
from datetime import datetime

from flask import Flask, render_template_string, jsonify, request

import plotly.graph_objects as go
import plotly.utils
import json

from config import (
    ETF_POOL, MOMENTUM_UNIT, START_DATE, END_DATE,
    INITIAL_CAPITAL, COMMISSION_RATE, SLIPPAGE, RISK_FREE_RATE,
)
from data.fetcher import build_unified_dataframe, fetch_benchmark_daily
from strategy.dual_momentum import (
    generate_signals, calculate_momentum_returns, compute_strategy_stats,
)
from backtest.engine import run_backtest, run_benchmark
from utils.metrics import full_metrics, annual_returns as calc_annual_returns

BOND_ETF = "511010"
CASH_ETF = "511880"
LOOKBACK = 1
TRAILING_STOP = 0.10
TOP_WEIGHTS = [1.0]
TOP_N = 1
POOL_FILE = os.path.join(os.path.dirname(__file__), "etf_pool.json")

app = Flask(__name__)

# 从文件加载ETF池，不存在则用config默认
def _load_pool():
    if os.path.exists(POOL_FILE):
        with open(POOL_FILE) as f:
            return json.loads(f.read())
    return {k: {"name": v["name"], "category": v["category"], "type": v["type"]}
            for k, v in ETF_POOL.items()}

def _save_pool(pool):
    with open(POOL_FILE, "w") as f:
        json.dump(pool, f, ensure_ascii=False, indent=2)

_etf_pool = _load_pool()

_cache = {}
_cache_lock = threading.Lock()
_last_refresh = None


def _pool():
    return _etf_pool


def get_data(force_refresh=False):
    """获取数据，force_refresh=True 时跳过缓存重新拉取"""
    global _last_refresh

    with _cache_lock:
        if not force_refresh and _cache.get("price_df") is not None:
            return _cache

        p = _pool()
        use_cache_val = not force_refresh
        data = build_unified_dataframe(
            etf_codes=list(p.keys()),
            start_date=START_DATE, end_date=END_DATE,
            use_cache=use_cache_val)
        price_df = data["price"]

        bench_df = fetch_benchmark_daily(START_DATE.replace("-", ""), END_DATE.replace("-", ""))
        bench_series = bench_df.set_index("date")["close"] if not bench_df.empty else None

        signals = generate_signals(price_df, LOOKBACK, TOP_N, TOP_WEIGHTS,
                                   cash_etf=CASH_ETF, bond_etf=BOND_ETF)
        bt_result = run_backtest(price_df, signals, INITIAL_CAPITAL, COMMISSION_RATE, SLIPPAGE,
                                 trailing_stop_pct=TRAILING_STOP)
        bench_nav = run_benchmark(bench_series, INITIAL_CAPITAL) if bench_series is not None else None
        momentum = calculate_momentum_returns(price_df, LOOKBACK)
        stats = compute_strategy_stats(signals, LOOKBACK)
        metrics = full_metrics(bt_result["daily_return"], bt_result["nav"], RISK_FREE_RATE)

        _cache.update({
            "price_df": price_df, "signals": signals, "bt_result": bt_result,
            "bench_nav": bench_nav, "momentum": momentum,
            "stats": stats, "metrics": metrics,
        })
        _last_refresh = datetime.now()
        return _cache


def build_signal_data(d):
    """根据缓存数据生成信号 JSON（所有值转为原生Python类型）"""
    momentum = d["momentum"]
    signals = d["signals"]
    stats = d["stats"]
    bt_result = d["bt_result"]

    if momentum.empty:
        return {"error": "数据不足"}

    latest_date = momentum.index[-1]
    latest = momentum.iloc[-1].dropna()
    hurdle = float(latest.get(BOND_ETF, 0))

    # 动量排名
    risk_etfs = {k: float(v) for k, v in latest.items() if k not in (CASH_ETF, BOND_ETF)}
    ranking = []
    for code, ret in sorted(risk_etfs.items(), key=lambda x: x[1], reverse=True):
        ranking.append({
            "code": code, "name": _pool().get(code, {}).get("name", code),
            "ret": f"{ret:+.2%}", "ret_val": round(ret, 4),
            "passed": bool(ret > hurdle), "hurdle": round(hurdle, 4),
        })

    # 当前持仓
    holds = []
    is_cash = True
    if not signals.empty:
        latest_sig = signals.iloc[-1]
        for code in latest_sig[latest_sig > 0].index:
            if code == CASH_ETF: continue
            ret = float(latest.get(code, 0))
            w = float(latest_sig[code])
            holds.append({
                "rank": len(holds) + 1,
                "code": code,
                "name": _pool().get(code, {}).get("name", code),
                "ret": f"{ret:+.2%}",
                "weight": f"{w:.0%}",
            })
            is_cash = False

    # 调仓变化
    added_list = []
    removed_list = []
    unchanged = bool(is_cash)
    if len(signals) > 1 and not is_cash:
        prev = set(signals.iloc[-2][signals.iloc[-2] > 0].index) - {CASH_ETF, BOND_ETF}
        cur = set(latest_sig[latest_sig > 0].index) - {CASH_ETF, BOND_ETF}
        for c in cur - prev:
            added_list.append({"code": str(c), "name": _pool().get(c, {}).get("name", str(c))})
        for c in prev - cur:
            removed_list.append({"code": str(c), "name": _pool().get(c, {}).get("name", str(c))})
        unchanged = bool(not added_list and not removed_list)

    # 近一月有实际变动的调仓日
    recent_signals = []
    one_month_ago = latest_date - pd.Timedelta(days=35)
    if len(signals) > 1 and not signals.empty:
        recent_idx = signals.index[signals.index >= one_month_ago]
        for i, si in enumerate(recent_idx):
            srow = signals.loc[si]
            cur_holds = set(srow[srow > 0].index) - {CASH_ETF}
            # 找上一期
            pos = signals.index.get_loc(si)
            if pos > 0:
                prev_row = signals.iloc[pos - 1]
                prev_holds = set(prev_row[prev_row > 0].index) - {CASH_ETF}
            else:
                prev_holds = set()
            added = cur_holds - prev_holds
            removed = prev_holds - cur_holds
            if added or removed:
                recent_signals.append({
                    "date": si.strftime("%m-%d"),
                    "date_full": si.strftime("%Y-%m-%d"),
                    "added": [_pool().get(c, {}).get("name", str(c)) for c in added],
                    "removed": [_pool().get(c, {}).get("name", str(c)) for c in removed],
                })

    return {
        "date": latest_date.strftime("%Y-%m-%d"),
        "hurdle": f"{hurdle:+.2%}",
        "ranking": ranking,
        "holds": holds,
        "is_cash": is_cash,
        "position_amount": float(bt_result["nav"].iloc[-1]),
        "changes": {"added": added_list, "removed": removed_list, "unchanged": unchanged},
        "safe_haven": int(stats.get("safe_haven_count", 0)),
        "stop_count": int(bt_result.attrs.get("stop_count", 0)),
        "current_nav": float(bt_result["nav"].iloc[-1]),
        "recent_signals": recent_signals,
        "refresh_time": _last_refresh.strftime("%H:%M:%S") if _last_refresh else "N/A",
    }


# ── 路由 ──

@app.route("/")
def index():
    d = get_data()
    sd = build_signal_data(d)
    m = d["metrics"]

    return render_template_string(HTML_TEMPLATE,
        signal_json=json.dumps(sd, ensure_ascii=False),
        metrics=m,
        safe_haven=d["stats"].get("safe_haven_count", 0),
        stop_count=d["bt_result"].attrs.get("stop_count", 0),
        current_nav=float(d["bt_result"]["nav"].iloc[-1]),
        update_time=datetime.now().strftime("%Y-%m-%d %H:%M"),
        nav_json=fig_nav(),
        recent_json=fig_recent(),
        dd_json=fig_drawdown(),
        annual_json=fig_annual(),
        hold_json=fig_holdings(),
    )


@app.route("/api/signal")
def api_signal():
    d = get_data()
    return jsonify(build_signal_data(d))


@app.route("/api/refresh")
def api_refresh():
    """强制刷新数据"""
    try:
        d = get_data(force_refresh=True)
        sd = build_signal_data(d)
        return jsonify({"status": "ok", "signal": sd})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/metrics")
def api_metrics():
    d = get_data()
    m = d["metrics"]
    return jsonify({
        "total_return": round(m["total_return"], 4),
        "annualized_return": round(m["annualized_return"], 4),
        "annualized_volatility": round(m["annualized_volatility"], 4),
        "sharpe_ratio": round(m["sharpe_ratio"], 2),
        "max_drawdown": round(m["max_drawdown"], 4),
        "calmar_ratio": round(m["calmar_ratio"], 2),
        "monthly_win_rate": round(m["monthly_win_rate"], 4),
    })


# ── ETF 管理 API ──

@app.route("/api/etfs")
def api_etfs():
    d = get_data()
    return jsonify({
        "etfs": [{"code": str(k), "name": str(v["name"]), "category": str(v["category"])}
                 for k, v in sorted(_etf_pool.items())],
        "count": len(_etf_pool),
    })


@app.route("/api/etfs/add", methods=["POST"])
def api_etf_add():
    data = request.get_json()
    code = str(data.get("code", "")).strip()
    name = str(data.get("name", "")).strip()
    category = str(data.get("category", "自定义")).strip()
    if not code or not name:
        return jsonify({"status": "error", "message": "代码和名称不能为空"}), 400
    _etf_pool[code] = {"name": name, "category": category, "type": "stock"}
    _save_pool(_etf_pool)
    with _cache_lock: _cache.clear()
    return jsonify({"status": "ok", "count": len(_etf_pool)})


@app.route("/api/etfs/remove", methods=["POST"])
def api_etf_remove():
    data = request.get_json()
    code = str(data.get("code", "")).strip()
    if not code: return jsonify({"status": "error", "message": "请指定代码"}), 400
    if code in (BOND_ETF, CASH_ETF):
        return jsonify({"status": "error", "message": "国债和货币ETF不可删除"}), 400
    if code in _etf_pool:
        del _etf_pool[code]
        _save_pool(_etf_pool)
        with _cache_lock: _cache.clear()
    return jsonify({"status": "ok", "count": len(_etf_pool)})


@app.route("/api/etfs/reset", methods=["POST"])
def api_etf_reset():
    global _etf_pool
    _etf_pool = {k: {"name": v["name"], "category": v["category"], "type": v["type"]}
                 for k, v in ETF_POOL.items()}
    _save_pool(_etf_pool)
    with _cache_lock: _cache.clear()
    return jsonify({"status": "ok", "count": len(_etf_pool)})


# ── 图表 ──

def fig_nav():
    d = get_data()
    nav = d["bt_result"]["nav"]
    bench = d["bench_nav"]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=nav.index, y=nav.values, mode="lines", name="双动量",
                             line=dict(color="#FF6B6B", width=2)))
    if bench is not None and not bench.empty:
        ci = bench.index.intersection(nav.index)
        fig.add_trace(go.Scatter(x=ci, y=bench.loc[ci], mode="lines", name="沪深300",
                                 line=dict(color="#9B9B9B", width=1.5, dash="dash")))
    fig.update_layout(title="净值走势（初始5万）", hovermode="x unified",
                      legend=dict(orientation="h", y=1.12),
                      margin=dict(l=20, r=20, t=40, b=20), height=380, template="plotly_white")
    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)


def fig_drawdown():
    d = get_data()
    nav = d["bt_result"]["nav"]
    dd = (nav - nav.cummax()) / nav.cummax() * 100
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=dd.index, y=dd.values, mode="lines", fill="tozeroy",
                             line=dict(color="#E74C3C", width=1),
                             fillcolor="rgba(231,76,60,0.15)", name="回撤"))
    fig.update_layout(title="回撤曲线", yaxis_title="回撤(%)", hovermode="x unified",
                      margin=dict(l=20, r=20, t=40, b=20), height=300, template="plotly_white")
    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)


def fig_annual():
    d = get_data()
    ar = calc_annual_returns(d["bt_result"]["daily_return"])
    if ar.empty: return json.dumps({})
    years, vals = [str(y) for y in ar.index], [v * 100 for v in ar.values]
    colors = ["#FF6B6B" if v > 0 else "#4ECDC4" for v in ar.values]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=years, y=vals, marker_color=colors,
                         text=[f"{v:+.1f}%" for v in vals], textposition="outside"))
    fig.update_layout(title="年度收益", yaxis_title="收益率(%)",
                      margin=dict(l=20, r=20, t=40, b=20), height=300, template="plotly_white")
    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)


def fig_recent():
    """近一月净值 + 有变动的调仓标注"""
    d = get_data()
    nav = d["bt_result"]["nav"]
    signals = d["signals"]
    now = nav.index[-1]
    start = now - pd.Timedelta(days=35)
    recent = nav[nav.index >= start]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=recent.index, y=recent.values, mode="lines",
        name="净值", line=dict(color="#6366f1", width=2.5),
        hovertemplate="%{x|%m-%d}<br>¥%{y:,.0f}<extra></extra>"
    ))

    # 只标有变动的调仓日
    if len(signals) > 1 and not signals.empty:
        sig_recent = signals.index[signals.index >= start]
        for i, sdate in enumerate(sig_recent):
            if sdate not in nav.index:
                continue
            pos = signals.index.get_loc(sdate)
            cur = set(signals.iloc[pos][signals.iloc[pos] > 0].index) - {CASH_ETF}
            prev = set(signals.iloc[pos-1][signals.iloc[pos-1] > 0].index) - {CASH_ETF} if pos > 0 else set()
            added = cur - prev
            removed = prev - cur
            if not added and not removed:
                continue
            label_parts = []
            if added:
                label_parts.append("+" + ",".join([_pool().get(c, {}).get("name", str(c)) for c in added]))
            if removed:
                label_parts.append("−" + ",".join([_pool().get(c, {}).get("name", str(c)) for c in removed]))
            label = " ".join(label_parts)
            val = nav.loc[sdate]
            fig.add_trace(go.Scatter(
                x=[sdate], y=[val], mode="markers+text",
                text=[label], textposition="top center",
                marker=dict(color="#f59e0b", size=14, symbol="diamond", line=dict(color="#fff", width=2)),
                textfont=dict(size=11, color="#92400e"),
                showlegend=False,
                hovertext=label,
                hovertemplate="<b>%{hovertext}</b><br>%{x|%m-%d} ¥%{y:,.0f}<extra></extra>"
            ))

    fig.update_layout(
        title="", margin=dict(l=20, r=20, t=10, b=20),
        height=240, template="plotly_white",
        xaxis=dict(tickformat="%m/%d", showgrid=True, gridcolor="#f0f0f5"),
        yaxis=dict(showgrid=True, gridcolor="#f0f0f5", tickprefix="¥"),
        hovermode="x unified",
        showlegend=False,
    )
    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)


def fig_holdings():
    d = get_data()
    sel = d["stats"].get("selection_count", {})
    risk = {k: v for k, v in sel.items() if k not in (CASH_ETF, BOND_ETF)}
    if not risk: return json.dumps({})
    sort = sorted(risk.items(), key=lambda x: x[1], reverse=True)
    names = [_pool().get(c, {}).get("name", c) for c, _ in sort]
    counts = [cnt for _, cnt in sort]
    fig = go.Figure()
    fig.add_trace(go.Bar(y=names, x=counts, orientation="h", marker_color="#4ECDC4",
                         text=counts, textposition="outside"))
    fig.update_layout(title="ETF 被选中频次", xaxis_title="次数",
                      margin=dict(l=20, r=20, t=40, b=20), height=300, template="plotly_white",
                      yaxis=dict(autorange="reversed"))
    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)


# ── HTML ──

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<title>双动量策略</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
:root{
  --bg:#f8f9fb;--card:#fff;--text:#1a1a2e;--sub:#8e8e9a;
  --green:#10b981;--red:#ef4444;--blue:#6366f1;--amber:#f59e0b;
  --border:#eaeaef;--radius:14px;--shadow:0 1px 2px rgba(0,0,0,.04),0 2px 8px rgba(0,0,0,.04);
}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display","PingFang SC","Microsoft YaHei",sans-serif;
background:var(--bg);color:var(--text);-webkit-font-smoothing:antialiased;line-height:1.5}

/* ── 顶部 ── */
.topbar{background:var(--card);border-bottom:1px solid var(--border);padding:14px 20px;
display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;z-index:10}
.topbar-left h1{font-size:18px;font-weight:700;letter-spacing:-.3px}
.topbar-left .tag{font-size:11px;color:var(--sub);margin-top:2px}
.btn{height:34px;padding:0 16px;border:none;border-radius:8px;font-size:13px;font-weight:600;
cursor:pointer;transition:all .15s;display:inline-flex;align-items:center;gap:6px}
.btn-outline{background:var(--card);color:var(--text);border:1px solid var(--border)}
.btn-outline:hover{background:var(--bg);border-color:#d0d0d8}
.btn-outline:disabled{opacity:.4;cursor:not-allowed}
.live-dot{width:7px;height:7px;border-radius:50%;background:var(--green);display:inline-block;
animation:pulse 2s infinite;margin-right:4px}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}

/* ── 布局 ── */
.main{max-width:1200px;margin:0 auto;padding:16px 20px 40px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px}
.grid1{display:grid;grid-template-columns:1fr;gap:14px;margin-bottom:14px}
@media(max-width:768px){.grid2{grid-template-columns:1fr};.topbar{padding:12px 14px};.main{padding:10px 12px 30px}}

/* ── 卡片 ── */
.card{background:var(--card);border-radius:var(--radius);padding:18px 20px;
box-shadow:var(--shadow);border:1px solid var(--border)}
.card-sm{padding:14px 16px}
.card-title{font-size:13px;font-weight:600;color:var(--sub);text-transform:uppercase;
letter-spacing:.5px;margin-bottom:14px;display:flex;align-items:center;gap:8px}
.card-title .icon{font-size:15px}

/* ── 指标行 ── */
.kpi-row{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:14px}
@media(max-width:768px){.kpi-row{grid-template-columns:repeat(3,1fr);gap:8px}}
.kpi{text-align:center;padding:10px 0}
.kpi-val{font-size:28px;font-weight:700;letter-spacing:-.5px}
.kpi-lbl{font-size:11px;color:var(--sub);margin-top:2px}
.kpi .up{color:var(--green)}.kpi .down{color:var(--red)}

/* ── 信号卡 ── */
.signal-hero{display:flex;align-items:center;gap:16px;padding:8px 0}
.signal-hero .rank-num{font-size:48px;font-weight:800;color:var(--blue);line-height:1;
min-width:52px;text-align:center}
.signal-hero .info{flex:1}
.signal-hero .name{font-size:20px;font-weight:700}
.signal-hero .code{font-size:13px;color:var(--sub);margin-top:2px}
.signal-hero .metrics{display:flex;gap:20px;margin-top:8px}
.signal-hero .metric-item{font-size:13px}
.signal-hero .metric-item span{color:var(--sub);margin-right:4px}
.pill{display:inline-block;padding:3px 10px;border-radius:20px;font-size:12px;font-weight:600}
.pill-long{background:#eef2ff;color:var(--blue)}
.pill-cash{background:#fef3c7;color:var(--amber)}
.cash-alert{display:flex;align-items:center;gap:10px;padding:14px 16px;
background:#fef3c7;border-radius:10px;font-size:14px;font-weight:600;color:var(--amber)}

/* ── 表格 ── */
.tbl{width:100%;border-collapse:collapse;font-size:13px}
.tbl th{text-align:left;padding:8px 12px;font-size:11px;font-weight:600;color:var(--sub);
text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid var(--border)}
.tbl td{padding:10px 12px;border-bottom:1px solid #f5f5f8}
.tbl tr:last-child td{border-bottom:none}
.tbl .up{color:var(--green);font-weight:600}
.tbl .dn{color:var(--red)}
.tbl .tag-pass{display:inline-block;width:20px;height:20px;border-radius:50%;text-align:center;
line-height:20px;font-size:11px;background:#ecfdf5;color:var(--green)}
.tbl .tag-fail{display:inline-block;width:20px;height:20px;border-radius:50%;text-align:center;
line-height:20px;font-size:11px;background:#fef2f2;color:var(--red)}
.tbl .highlight td{background:#f8f9ff}

/* ── 图表 ── */
.chart-wrap{width:100%}
.chart-wrap .js-plotly-plot .plotly .main-svg{background:transparent!important}

/* ── 底栏 ── */
.foot{text-align:center;color:var(--sub);font-size:11px;padding:10px 0 30px}
.foot span{color:var(--text)}

/* ── 变更日志 ── */
.changes{margin-top:12px;display:flex;gap:6px;flex-wrap:wrap}
.changes .chg{padding:3px 10px;border-radius:6px;font-size:12px;font-weight:500}
.chg-buy{background:#ecfdf5;color:var(--green)}
.chg-sell{background:#fef2f2;color:var(--red)}
.chg-hold{background:#f5f5f8;color:var(--sub)}

/* ── 信息表 ── */
.info-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px 16px;font-size:13px}
.info-grid .ik{color:var(--sub)}.info-grid .iv{font-weight:500}

/* ── 加载态 ── */
.spin{display:inline-block;width:14px;height:14px;border:2px solid var(--border);
border-top-color:var(--blue);border-radius:50%;animation:spin .6s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
</style>
</head>
<body>

<!-- 顶栏 -->
<div class="topbar">
  <div class="topbar-left">
    <h1>双动量策略</h1>
    <div class="tag">Top1 · 1×20日 · 国债基准 · 周五调仓</div>
  </div>
  <div style="display:flex;align-items:center;gap:10px">
    <span style="font-size:11px;color:var(--sub)" id="refresh-hint">每5分钟刷新</span>
    <button class="btn btn-outline" id="btn-refresh" onclick="doRefresh()">
      <span id="btn-icon">↻</span> <span id="btn-label">刷新</span>
    </button>
  </div>
</div>

<div class="main">

<!-- 指标 -->
<div class="kpi-row">
  <div class="kpi"><div class="kpi-val up">{{ "%.1f"|format(metrics.annualized_return*100) }}%</div><div class="kpi-lbl">年化收益</div></div>
  <div class="kpi"><div class="kpi-val">{{ "%.2f"|format(metrics.sharpe_ratio) }}</div><div class="kpi-lbl">夏普比率</div></div>
  <div class="kpi"><div class="kpi-val down">{{ "%.1f"|format(metrics.max_drawdown*100) }}%</div><div class="kpi-lbl">最大回撤</div></div>
  <div class="kpi"><div class="kpi-val up">{{ "%.0f"|format(metrics.total_return*100) }}%</div><div class="kpi-lbl">累计收益</div></div>
  <div class="kpi"><div class="kpi-val">{{ "%.2f"|format(metrics.calmar_ratio) }}</div><div class="kpi-lbl">卡玛比率</div></div>
  <div class="kpi"><div class="kpi-val">{{ "%.1f"|format(metrics.monthly_win_rate*100) }}%</div><div class="kpi-lbl">月度胜率</div></div>
</div>

<!-- 信号 + 排名 -->
<div class="grid2">
  <div class="card">
    <div class="card-title"><span class="live-dot"></span> 本周持仓 · <span id="sig-date" style="font-weight:400;text-transform:none;letter-spacing:0"></span></div>
    <div id="holds-area"></div>
    <div class="changes" id="change-log"></div>
    <div class="chart-wrap" id="chart-recent" style="margin-top:16px"></div>
  </div>
  <div class="card">
    <div class="card-title">📈 动量排名 · <span id="hurdle-text" style="font-weight:400;text-transform:none;letter-spacing:0"></span></div>
    <table class="tbl"><thead><tr><th>代码</th><th>名称</th><th style="text-align:right">20日涨幅</th><th style="text-align:center">通过</th></tr></thead><tbody id="rank-tbody"></tbody></table>
  </div>
</div>

<!-- 净值 -->
<div class="grid1">
  <div class="card">
    <div class="card-title">净值走势</div>
    <div class="chart-wrap" id="chart-nav"></div>
  </div>
</div>

<!-- 年度 + 回撤 -->
<div class="grid2">
  <div class="card"><div class="card-title">年度收益</div><div class="chart-wrap" id="chart-annual"></div></div>
  <div class="card"><div class="card-title">回撤曲线</div><div class="chart-wrap" id="chart-dd"></div></div>
</div>

<!-- ETF频次 + 管理 -->
<div class="grid2">
  <div class="card"><div class="card-title">ETF 选中频次</div><div class="chart-wrap" id="chart-hold"></div></div>
  <div class="card">
    <div class="card-title">📋 标的池管理 <span style="font-weight:400;font-size:11px;color:var(--sub)" id="etf-count"></span></div>
    <div style="display:flex;gap:6px;margin-bottom:10px;flex-wrap:wrap">
      <input id="etf-code" placeholder="代码 如510300" style="width:100px;padding:6px 8px;border:1px solid var(--border);border-radius:6px;font-size:12px">
      <input id="etf-name" placeholder="名称" style="flex:1;min-width:80px;padding:6px 8px;border:1px solid var(--border);border-radius:6px;font-size:12px">
      <button class="btn btn-outline" onclick="addEtf()" style="height:30px;font-size:11px">+ 添加</button>
    </div>
    <div id="etf-list" style="max-height:200px;overflow-y:auto;font-size:12px"></div>
    <div style="margin-top:10px">
      <button class="btn btn-outline" onclick="resetEtfs()" style="height:28px;font-size:11px;color:var(--red)">↺ 恢复默认</button>
    </div>
  </div>
</div>

<!-- 策略参数 -->
    <div class="info-grid">
      <div class="ik">调仓</div><div class="iv">每周五收盘</div>
      <div class="ik">动量</div><div class="iv">1×20日涨幅</div>
      <div class="ik">门槛</div><div class="iv">涨幅 > 国债(511010)</div>
      <div class="ik">仓位</div><div class="iv">Top1 100%</div>
      <div class="ik">止损</div><div class="iv">最高点回落 10%</div>
      <div class="ik">本金</div><div class="iv">50,000 元</div>
      <div class="ik">避险</div><div class="iv" id="sig-safe">{{ safe_haven }} 次</div>
      <div class="ik">止盈触发</div><div class="iv" id="sig-stop">{{ stop_count }} 次</div>
      <div class="ik">当前净值</div><div class="iv" id="cur-nav" style="font-weight:700;color:var(--blue)">{{ "%.0f"|format(current_nav) }} 元</div>
    </div>
  </div>
</div>

<!-- 策略参数 -->
<div class="grid1">
  <div class="card">
    <div class="card-title">策略参数</div>
    <div class="info-grid">
      <div class="ik">调仓</div><div class="iv">每周五收盘</div>
      <div class="ik">动量</div><div class="iv">1×20日涨幅</div>
      <div class="ik">门槛</div><div class="iv">涨幅 > 国债(511010)</div>
      <div class="ik">仓位</div><div class="iv">Top1 100%</div>
      <div class="ik">止损</div><div class="iv">最高点回落 10%</div>
      <div class="ik">本金</div><div class="iv">50,000 元</div>
      <div class="ik">避险</div><div class="iv" id="sig-safe">{{ safe_haven }} 次</div>
      <div class="ik">止盈触发</div><div class="iv" id="sig-stop">{{ stop_count }} 次</div>
      <div class="ik">当前净值</div><div class="iv" id="cur-nav" style="font-weight:700;color:var(--blue)">{{ "%.0f"|format(current_nav) }} 元</div>
    </div>
  </div>
</div>

</div>
<div class="foot">数据更新于 <span id="update-label">{{ update_time }}</span></div>

<script>
const signalData = {{ signal_json | safe }};
const navJSON = {{ nav_json | safe }};
const recentJSON = {{ recent_json | safe }};
const ddJSON = {{ dd_json | safe }};
const annualJSON = {{ annual_json | safe }};
const holdJSON = {{ hold_json | safe }};
const REFRESH_MS = 5 * 60 * 1000;

function renderSignal(sd){
  document.getElementById("sig-date").textContent = sd.date;
  document.getElementById("hurdle-text").textContent = "(国债基准 "+sd.hurdle+")";
  var h = document.getElementById("holds-area");
  if(sd.is_cash){
    h.innerHTML = '<div class="cash-alert">⚠ 全部标的未跑赢国债 — 持有银华日利(现金)</div>';
  } else {
    var html = "";
    sd.holds.forEach(function(o,i){
      var retCls = o.ret.charAt(0)==='+'?'up':'dn';
      html += '<div class="signal-hero">'+
        '<div class="rank-num">#'+(i+1)+'</div>'+
        '<div class="info"><div class="name">'+o.name+'</div>'+
        '<div class="code">'+o.code+'</div>'+
        '<div class="metrics"><div class="metric-item"><span>20日涨幅</span><b class="'+retCls+'">'+o.ret+'</b></div>'+
        '<div class="metric-item"><span>仓位</span><b>'+o.weight+'</b></div>'+
        '<div class="metric-item"><span>金额</span><b>¥'+sd.position_amount.toLocaleString()+'</b></div></div></div>'+
        '<span class="pill pill-long">持仓中</span></div>';
    });
    h.innerHTML = html;
  }

  var clog = document.getElementById("change-log");
  var ch = sd.changes;
  var parts = [];
  if(ch.unchanged && !sd.is_cash) parts.push('<span class="chg chg-hold">持仓不变</span>');
  if(ch.added.length) parts.push('<span class="chg chg-buy">+ 买入 '+ch.added.map(function(a){return a.name}).join('、')+'</span>');
  if(ch.removed.length) parts.push('<span class="chg chg-sell">− 卖出 '+ch.removed.map(function(r){return r.name}).join('、')+'</span>');
  clog.innerHTML = parts.join(' ');

  var rbody = document.getElementById("rank-tbody");
  var rhtml = "";
  sd.ranking.forEach(function(r){
    var cls = r.passed ? "up" : "dn";
    rhtml += '<tr'+(r.passed?' class="highlight"':'')+'>'+
      '<td>'+r.code+'</td><td>'+r.name+'</td>'+
      '<td style="text-align:right" class="'+cls+'">'+r.ret+'</td>'+
      '<td style="text-align:center"><span class="'+(r.passed?'tag-pass':'tag-fail')+'">'+(r.passed?'✓':'✗')+'</span></td></tr>';
  });
  rbody.innerHTML = rhtml;

  document.getElementById("refresh-hint").textContent = '更新 '+sd.refresh_time;
  document.getElementById("update-label").textContent = sd.date + ' ' + sd.refresh_time;
}

function doRefresh(){
  var btn = document.getElementById("btn-refresh");
  btn.disabled = true;
  document.getElementById("btn-icon").innerHTML = '<span class="spin"></span>';
  document.getElementById("btn-label").textContent = '刷新中';
  fetch("/api/refresh").then(function(r){return r.json()}).then(function(d){
    if(d.status==="ok" && d.signal){
      renderSignal(d.signal);
      document.getElementById("cur-nav").textContent = Math.round(d.signal.current_nav).toLocaleString()+' 元';
    }
  })["catch"](function(e){console.error(e)}).finally(function(){
    btn.disabled = false;
    document.getElementById("btn-icon").textContent = '↻';
    document.getElementById("btn-label").textContent = '刷新';
  });
}

function autoRefresh(){
  fetch("/api/signal").then(function(r){return r.json()}).then(function(sd){
    if(!sd.error) renderSignal(sd);
  })["catch"](function(){});
}

renderSignal(signalData);
if(navJSON.data)Plotly.newPlot("chart-nav",navJSON.data,navJSON.layout,{responsive:true,displayModeBar:false});
if(recentJSON.data)Plotly.newPlot("chart-recent",recentJSON.data,recentJSON.layout,{responsive:true,displayModeBar:false});
if(ddJSON.data)Plotly.newPlot("chart-dd",ddJSON.data,ddJSON.layout,{responsive:true,displayModeBar:false});
if(annualJSON.data)Plotly.newPlot("chart-annual",annualJSON.data,annualJSON.layout,{responsive:true,displayModeBar:false});
if(holdJSON.data)Plotly.newPlot("chart-hold",holdJSON.data,holdJSON.layout,{responsive:true,displayModeBar:false});
setInterval(autoRefresh,REFRESH_MS);

// ── ETF 管理 ──
function loadEtfs(){fetch("/api/etfs").then(r=>r.json()).then(d=>{document.getElementById("etf-count").textContent="("+d.count+"只)";var h="";d.etfs.forEach(function(e){var p=(e.code==="511880"||e.code==="511010");h+='<div style="display:flex;align-items:center;padding:4px 0;border-bottom:1px solid #f5f5f8"><span style="width:70px;font-weight:600">'+e.code+'</span><span style="flex:1">'+e.name+'</span><span style="font-size:10px;color:var(--sub);width:60px">'+e.category+'</span>'+(p?'<span style="font-size:10px;color:var(--sub)">🔒</span>':'<button onclick=\"removeEtf(\\''+e.code+'\\')\" style=\"border:none;background:none;color:var(--red);cursor:pointer;font-size:16px;padding:0 4px\">✕</button>')+'</div>'});document.getElementById("etf-list").innerHTML=h})}
function addEtf(){var c=document.getElementById("etf-code").value.trim(),n=document.getElementById("etf-name").value.trim();if(!c||!n){alert("请填代码和名称");return}fetch("/api/etfs/add",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({code:c,name:n,category:"自定义"})}).then(r=>r.json()).then(d=>{if(d.status==="ok"){document.getElementById("etf-code").value="";document.getElementById("etf-name").value="";loadEtfs();doRefresh()}})}
function removeEtf(code){if(!confirm("删除 "+code+"？"))return;fetch("/api/etfs/remove",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({code:code})}).then(r=>r.json()).then(d=>{if(d.status==="ok"){loadEtfs();doRefresh()}})}
function resetEtfs(){if(!confirm("恢复默认ETF池？"))return;fetch("/api/etfs/reset",{method:"POST"}).then(r=>r.json()).then(d=>{if(d.status==="ok"){loadEtfs();doRefresh()}})}
loadEtfs();
</script>
</body>
</html>
"""


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    # 预热缓存
    print("⏳ 加载数据...")
    get_data()
    print("✅ 数据就绪")

    print(f"""
╔═══════════════════════════════════════════════════╗
║  双动量策略 · 实时仪表盘                          ║
║  Top1 100% · 每5分钟自动刷新                      ║
║  访问: http://{args.host}:{args.port}                       ║
╚═══════════════════════════════════════════════════╝
""")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
