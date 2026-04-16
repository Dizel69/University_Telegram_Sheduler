FROM python:3.12-slim
WORKDIR /app

# Базовые утилиты, включая curl для запросов к Telegram API
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Копирование и установка требуемых пакетов
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование приложения
COPY . .

# Переменные окружения
ENV PYTHONUNBUFFERED=1

# Запуск bot-service
CMD ["uvicorn", "bot_service:app", "--host", "0.0.0.0", "--port", "8081"]
