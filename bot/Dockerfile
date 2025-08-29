FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# системные зависимости для pandas, numpy, cryptography и т.п.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# каталог для состояния (SQLite)
RUN mkdir -p /state
ENV BOT_STATE_DIR=/state

CMD ["python", "-m", "app.main"]
