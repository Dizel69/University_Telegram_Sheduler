FROM python:3.12-slim

WORKDIR /app

# Копирование и установка требуемых пакетов
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование приложения
COPY . .

# Открытие порта
EXPOSE 8090

# Запуск парсера
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8090"]
