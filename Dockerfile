FROM python:3.11-slim

# 安装系统依赖（matplotlib/akshare 可能需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 10000
CMD ["sh", "-c", "python dashboard.py --host 0.0.0.0 --port ${PORT:-10000}"]
