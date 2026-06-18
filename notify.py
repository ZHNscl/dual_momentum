#!/usr/bin/env python3
"""
双动量策略 - 周五调仓微信通知

用法:
  python3 notify.py                          # 打印信号
  python3 notify.py --send                   # 发送微信通知
  python3 notify.py --send --method=wecom    # 企业微信机器人

微信推送支持三种方式（选一种即可）：
  1. 企业微信机器人 - 推荐，免费无限制
  2. Server酱 - https://sct.ftqq.com 注册获取 SendKey
  3. PushPlus - https://pushplus.hxtrip.com 注册获取 Token

配置方式：
  创建 ~/.dual_momentum_push.conf
  [wecom]
  webhook = https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx
  [serverchan]
  sendkey = SCT123456xxx
  [pushplus]
  token = abc123xxx
"""

import sys, os, json, textwrap, argparse
from datetime import datetime
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import numpy as np
from config import (
    ETF_POOL, MOMENTUM_UNIT, TOP_N, TOP_WEIGHTS, START_DATE, END_DATE,
    INITIAL_CAPITAL, COMMISSION_RATE, SLIPPAGE, RISK_FREE_RATE, OUTPUT_DIR,
)
from data.fetcher import build_unified_dataframe
from strategy.dual_momentum import (
    generate_signals, calculate_momentum_returns,
    absolute_momentum_filter, relative_momentum_rank,
)

CONFIG_PATH = os.path.expanduser("~/.dual_momentum_push.conf")
LOOKBACK = 1  # 1×20日
BOND_ETF = "511010"
CASH_ETF = "511880"


def load_push_config(method):
    """加载推送配置（配置文件 + 环境变量兜底）"""
    cfg = {}
    # 配置文件
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                if line.startswith("["): section = line.strip("[]")
                else: cfg.setdefault(section, {})[line.split("=",1)[0].strip()] = line.split("=",1)[1].strip()
    # 环境变量优先
    if method == "wecom":
        cfg.setdefault("wecom", {})
        if os.environ.get("WECOM_WEBHOOK"):
            cfg["wecom"]["webhook"] = os.environ["WECOM_WEBHOOK"]
    elif method == "serverchan":
        cfg.setdefault("serverchan", {})
        if os.environ.get("SERVERCHAN_KEY"):
            cfg["serverchan"]["sendkey"] = os.environ["SERVERCHAN_KEY"]
    elif method == "pushplus":
        cfg.setdefault("pushplus", {})
        if os.environ.get("PUSHPLUS_TOKEN"):
            cfg["pushplus"]["token"] = os.environ["PUSHPLUS_TOKEN"]
    return cfg


def generate_report(price_df):
    """生成周五调仓报告文本"""
    # 计算最新动量
    momentum = calculate_momentum_returns(price_df, LOOKBACK)
    if momentum.empty:
        return "❌ 数据不足，无法生成报告"

    latest_date = momentum.index[-1]
    latest = momentum.iloc[-1].dropna()

    # 国债基准
    hurdle = latest.get(BOND_ETF, 0)

    # 绝对动量过滤（排除现金、国债）
    risk_etfs = {k: v for k, v in latest.items()
                 if k not in (CASH_ETF, BOND_ETF)}
    passed = {k: v for k, v in risk_etfs.items() if v > hurdle}
    failed = {k: v for k, v in risk_etfs.items() if v <= hurdle}

    # 排名
    ranked = sorted(passed.items(), key=lambda x: x[1], reverse=True)
    top_etfs = ranked[:TOP_N]

    # 生成信号
    signals = generate_signals(price_df, LOOKBACK, TOP_N, TOP_WEIGHTS,
                               cash_etf=CASH_ETF, bond_etf=BOND_ETF)
    latest_signal = signals.iloc[-1] if not signals.empty else None

    # 上一期信号
    prev_signal = signals.iloc[-2] if len(signals) > 1 else None

    # 构建报告
    dt_str = latest_date.strftime("%Y-%m-%d")
    lines = []
    lines.append(f"📊 双动量调仓报告")
    lines.append(f"📅 信号日期: {dt_str}（周五）")
    lines.append(f"📐 参数: 1×20日动量 | Top2 70/30 | 国债基准")
    lines.append(f"")

    # 动量全景
    lines.append(f"📈 动量涨幅排行（基准国债={hurdle:+.2%}）：")
    lines.append(f"   {'代码':<7} {'名称':<10} {'涨幅':>8} {'通过':>4}")
    lines.append(f"   {'-'*33}")
    all_ranked = sorted(risk_etfs.items(), key=lambda x: x[1], reverse=True)
    for code, ret in all_ranked:
        name = ETF_POOL.get(code, {}).get("name", code)
        flag = "✅" if ret > hurdle else "❌"
        lines.append(f"   {code:<7} {name:<10} {ret:>+7.2%} {flag:>4}")
    lines.append(f"")

    if len(passed) == 0:
        lines.append(f"⚠️ 全部标的未跑赢国债 → 本周持有 100% 银华日利(现金)")
    else:
        lines.append(f"🎯 本周持仓:")
        lines.append(f"   {'排名':<4} {'代码':<7} {'名称':<10} {'权重':>6}")
        lines.append(f"   {'-'*30}")
        for i, (code, ret) in enumerate(top_etfs):
            name = ETF_POOL.get(code, {}).get("name", code)
            w = TOP_WEIGHTS[i] if i < len(TOP_WEIGHTS) else 1.0
            lines.append(f"   #{i+1:<3} {code:<7} {name:<10} {w:>5.0%}")
    lines.append(f"")

    # 调仓对比
    if prev_signal is not None and latest_signal is not None:
        prev_holds = set(prev_signal[prev_signal > 0].index) - {CASH_ETF}
        cur_holds = set(latest_signal[latest_signal > 0].index) - {CASH_ETF}
        added = cur_holds - prev_holds
        removed = prev_holds - cur_holds
        if added or removed:
            lines.append(f"🔄 调仓变化:")
            if added:
                names = [ETF_POOL.get(c, {}).get("name", c) for c in added]
                lines.append(f"   ➕ 买入: {', '.join(names)}")
            if removed:
                names = [ETF_POOL.get(c, {}).get("name", c) for c in removed]
                lines.append(f"   ➖ 卖出: {', '.join(names)}")
            if not added and not removed:
                lines.append(f"   ➡️  持仓不变")

    lines.append(f"")
    lines.append(f"---")
    lines.append(f"🤖 自动生成 | {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    return "\n".join(lines)


def send_wecom(text, webhook):
    """企业微信机器人推送"""
    # 企业微信 markdown 消息有长度限制，切成 markdown 格式
    payload = {
        "msgtype": "text",
        "text": {"content": text}
    }
    r = requests.post(webhook, json=payload, timeout=10)
    return r.status_code == 200 and r.json().get("errcode") == 0


def send_serverchan(text, sendkey):
    """Server酱推送"""
    url = f"https://sctapi.ftqq.com/{sendkey}.send"
    # 提取标题
    first_line = text.split("\n")[0] if text else "调仓报告"
    payload = {"title": first_line, "desp": text}
    r = requests.post(url, data=payload, timeout=10)
    return r.status_code == 200


def send_pushplus(text, token):
    """PushPlus推送"""
    url = "https://www.pushplus.plus/send"
    first_line = text.split("\n")[0] if text else "调仓报告"
    payload = {"token": token, "title": first_line, "content": text, "template": "txt"}
    r = requests.post(url, json=payload, timeout=10)
    return r.status_code == 200


def main():
    parser = argparse.ArgumentParser(description="双动量周五调仓通知")
    parser.add_argument("--send", action="store_true", help="发送微信推送（否则仅打印）")
    parser.add_argument("--method", choices=["wecom", "serverchan", "pushplus"],
                        default="wecom", help="推送方式")
    args = parser.parse_args()

    # 获取数据
    print("📡 获取最新行情...")
    data = build_unified_dataframe(
        etf_codes=list(ETF_POOL.keys()),
        start_date=START_DATE, end_date=END_DATE, use_cache=False)
    price_df = data["price"]

    # 生成报告
    report = generate_report(price_df)
    print(report)

    # 发送推送
    if args.send:
        cfg = load_push_config(args.method)
        method_cfg = cfg.get(args.method, {})
        print(f"\n📤 正在通过 {args.method} 推送...")

        if args.method == "wecom":
            webhook = method_cfg.get("webhook", "")
            if not webhook:
                print("❌ 未配置企业微信 webhook")
                print("   请在 ~/.dual_momentum_push.conf 中配置 [wecom] 段")
                return 1
            ok = send_wecom(report, webhook)

        elif args.method == "serverchan":
            sendkey = method_cfg.get("sendkey", "")
            if not sendkey:
                print("❌ 未配置 Server酱 sendkey")
                return 1
            ok = send_serverchan(report, sendkey)

        elif args.method == "pushplus":
            token = method_cfg.get("token", "")
            if not token:
                print("❌ 未配置 PushPlus token")
                return 1
            ok = send_pushplus(report, token)

        if ok:
            print("✅ 推送成功！")
        else:
            print("❌ 推送失败，请检查配置")

    return 0


if __name__ == "__main__":
    sys.exit(main())
