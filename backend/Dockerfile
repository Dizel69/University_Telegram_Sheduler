FROM python:3.11-slim
WORKDIR /app

# Установка необходимых системных зависимостей
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc libpq-dev libssl-dev libffi-dev pkg-config curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Обновление pip и инструментов
RUN pip install --upgrade pip setuptools wheel

# Копирование зависимостей
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Копирование кода приложения
COPY app /app/app

# Переменные окружения
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Запуск приложения
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
