FROM node:20

WORKDIR /app

# Установка зависимостей (использует package-lock, если присутствует)
COPY package.json package-lock.json* ./
# Использование npm install для избежания неполадок с lockfile при итеративных build
RUN npm install --no-audit --no-fund

# Копирование исходных файлов приложения
COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
