FROM python:3.12-slim
WORKDIR /app

# Копирование и установка требуемых пакетов
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование приложения
COPY . .

# Переменные окружения
ENV PYTHONUNBUFFERED=1

# Запуск worker
CMD ["python", "worker.py"]
