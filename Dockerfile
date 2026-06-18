FROM python:3.11-slim

# 安装系统依赖（matplotlib/akshare 可能需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先复制依赖文件并安装（利用 Docker 缓存层）
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 复制全部项目文件
COPY . ./

# 创建运行时需要的目录
RUN mkdir -p output/cache

# Render 通过 PORT 环境变量分配端口
ENV PORT=10000
EXPOSE $PORT

CMD ["sh", "-c", "python dashboard.py --host 0.0.0.0 --port ${PORT}"]
