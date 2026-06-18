# 双动量策略 · 手机使用指南

## 一、仪表盘（手机浏览器随时看）

### 部署到 Render.com（免费，3分钟）

1. 打开 https://render.com → 用 GitHub 注册
2. 点 **New +** → **Web Service**
3. 上传 `dual_momentum.zip`（或先解压推到 GitHub 仓库）
4. 填三个字段：

| 字段 | 填这个 |
|------|--------|
| Name | `dual-momentum`（随便填） |
| Build Command | `pip install -r requirements.txt` |
| Start Command | 留空（自动用 Procfile）或填 `python dashboard.py --host 0.0.0.0 --port $PORT` |

5. 选 **Free** 计划 → 点 **Create Web Service**
6. ⚠️ 关键：**Branch 必须是 `main`**，**Root Directory 留空**（不要填子目录），Start Command 留空让它用 Procfile
7. 等 2-3 分钟，部署完成后你会得到一个网址：
   ```
   https://dual-momentum.onrender.com
   ```
7. 手机浏览器打开这个网址 → 就是仪表盘

> ⚠️ 免费版 15 分钟无人访问会休眠，下次打开等 30 秒唤醒。想不休眠？用 Render 的 Cron Job 每 10 分钟 ping 一次自己。

---

## 二、周五调仓微信通知

### 用企业微信机器人（推荐，免费无限制）

**1. 创建机器人：**
- 手机打开「企业微信」App
- 随便建一个群（拉一个同事/家人即可）
- 群设置 → 群机器人 → 添加 → 复制 Webhook 地址

**2. 在 Render 上配置：**
- 进入 Render Dashboard → 你的 Web Service
- 左侧点 **Environment** → 添加环境变量：

| Key | Value |
|-----|-------|
| `WECOM_WEBHOOK` | `https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的key` |

**3. 在 Render 上设置定时任务：**
- Render Dashboard → **Cron Jobs** → **New Cron Job**
- Command: `python notify.py --send --method=wecom`
- Schedule: `0 9 * * 5`（每周五早上9点）
- 完成 ✅

---

## 三、如果没有企业微信

改用 Server酱，直接推送到个人微信：

1. 打开 https://sct.ftqq.com → 微信扫码登录 → 获取 SendKey
2. Render 环境变量填 `SERVERCHAN_KEY=你的SendKey`
3. Cron Job 命令改为 `python notify.py --send --method=serverchan`

---

## 四、本地也跑一份（双保险）

电脑上保持运行也可以：

```bash
# 仪表盘
cd dual_momentum && python dashboard.py

# 手动发一次通知测试
python notify.py --send
```

---

## 最终效果

| 方式 | 用途 |
|------|------|
| 📱 手机浏览器打开 Render 网址 | 随时看数据 |
| 📱 企业微信/微信消息 | 每周五自动收到调仓通知 |
