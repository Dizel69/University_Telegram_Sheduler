FROM python:3.12-slim
WORKDIR /app

# Копирование и установка требуемых пакетов
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование приложения
COPY . .

# Переменные окружения
ENV PYTHONUNBUFFERED=1

# Запуск bot-service
CMD ["uvicorn", "bot_service:app", "--host", "0.0.0.0", "--port", "8081"]
