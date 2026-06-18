# 双动量交易策略 — A股ETF 分析模型

## 快速开始

### 1. 安装 Python（3.10+）

下载安装：https://www.python.org/downloads/

安装时勾选 "Add Python to PATH"

### 2. 安装依赖

打开终端/命令行，进入本项目目录：

```bash
cd dual_momentum
pip install -r requirements.txt
```

### 3. 启动仪表盘

```bash
python dashboard.py
```

浏览器访问 http://localhost:5000

仪表盘功能：
- 实时动量排名（所有ETF 20日涨幅）
- 本周持仓信号（Top1 100%）
- 净值走势、年度收益、回撤曲线（交互式）
- 右上角"刷新数据"按钮 + 每5分钟自动刷新

### 4. 周五微信通知（可选）

测试消息：
```bash
python notify.py
```

配置微信推送（三选一）：

**企业微信机器人（推荐）**：
1. 企业微信 → 群聊 → 群设置 → 群机器人 → 添加
2. 复制 Webhook 地址
3. 创建配置文件：
```bash
cat > ~/.dual_momentum_push.conf << 'EOF'
[wecom]
webhook = https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的key
EOF
```
4. 测试：`python notify.py --send`

**设置每周五 17:00 自动推送：**
```bash
crontab -e
# 添加一行：
0 17 * * 5 cd /path/to/dual_momentum && python notify.py --send
```

### 5. 回测对比

```bash
python main.py
```

## 策略说明

| 参数 | 值 | 说明 |
|------|-----|------|
| 动量 | 1×20日涨幅 | 过去20个交易日收益率 |
| 绝对动量 | >国债(511010) | 必须跑赢国债才有资格 |
| 相对动量 | Top1 | 选涨幅最高的 |
| 仓位 | 100% | 集中持仓 |
| 调仓 | 每周五 | 周五收盘后计算信号 |
| 止盈 | 回落10% | 从持仓最高点回落10%止损 |

## ETF 池

| 代码 | 名称 | 类别 |
|------|------|------|
| 510300 | 沪深300ETF | 宽基大盘 |
| 510500 | 中证500ETF | 宽基中盘 |
| 159915 | 创业板ETF | 宽基成长 |
| 588000 | 科创50ETF | 宽基科技 |
| 159819 | 人工智能ETF | 行业科技 |
| 513100 | 纳指ETF | 海外QDII |
| 518880 | 黄金ETF | 商品避险 |
| 511010 | 国债ETF | 绝对动量基准 |
| 511880 | 银华日利 | 现金避险 |

## 项目结构

```
dual_momentum/
├── dashboard.py          ← Web仪表盘
├── notify.py             ← 微信通知
├── main.py               ← 回测对比
├── config.py             ← 参数配置
├── requirements.txt      ← 依赖
├── strategy/dual_momentum.py  ← 策略核心
├── backtest/engine.py         ← 回测引擎
├── data/fetcher.py            ← 数据获取
├── utils/metrics.py           ← 绩效指标
└── visualization/charts.py    ← 图表
```
