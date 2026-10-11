FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
# --retries/--timeout：跨架构构建（QEMU 模拟）时下载较慢，避免 PyPI 偶发超时导致构建失败
RUN pip install --no-cache-dir --retries 5 --timeout 60 -r /app/requirements.txt

COPY . /app

CMD ["python", "-m", "collector.main"]


