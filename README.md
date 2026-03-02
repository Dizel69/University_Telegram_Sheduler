# M15 Telegram Scheduler — skeleton проекта (MVP)

Ниже — минимальный skeleton микросервисного проекта, который я только что подготовил. В репозитории будут следующие сервисы:

* `backend` — FastAPI (CRUD событий, public calendar, endpoint для получения напоминаний)
* `bot` — сервис, принимающий HTTP-запросы от backend и отправляющий сообщения в Telegram
* `worker` — простой scheduler (APScheduler), который по таймеру запрашивает у backend события, требующие отправки напоминаний, и вызывает bot
* `frontend` — React‑приложение, показывающее:
  * публичный календарь с событиями,
  * (для админов) панель создания/списка событий,
  * доступную без авторизации вкладку «Домашка», где выводятся только события типа `homework`.
  
  Настройка текущего семестра сохраняется в `localStorage` и доступна через скрытую страницу `#semester`.
* `postgres`, `redis` — инфраструктура (docker-compose)

---

## Структура (файлы, которые я положил в skeleton)

```
m15-telegram-skeleton/
├─ backend/
│  ├─ app/
│  │  ├─ main.py
│  │  ├─ models.py
│  │  ├─ schemas.py
│  │  ├─ crud.py
│  │  └─ database.py
│  ├─ Dockerfile
│  └─ requirements.txt
├─ bot/
│  ├─ app.py
│  ├─ Dockerfile
│  └─ requirements.txt
├─ worker/
│  ├─ worker.py
│  ├─ Dockerfile
│  └─ requirements.txt
├─ frontend/
│  └─ README.md (заглушка, инструкция для React + FullCalendar)
├─ docker-compose.yml
└─ README.md
```

---

> **Важно:** это skeleton — минимально рабочая основа. Я использовал подход с HTTP-вызовом backend -> bot для отправки сообщений (так проще для микросервисной архитектуры и отладки в контейнерах). Worker использует APScheduler и периодически обращается к backend, чтобы найти события с напоминаниями.

---

## Как запустить (локально, dev)

1. Создать `.env` в корне с переменными:

```env
BOT_TOKEN=токен_вашего_бота
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=m15db
DATABASE_URL=postgresql://postgres:postgres@postgres:5432/m15db
REDIS_URL=redis://redis:6379/0
FRONTEND_URL=http://{HOST}:3000
```

2. Запустить:

```bash
docker-compose up --build
```

3. Backend доступен на `http://<HOST>:8000` (Swagger UI — `http://<HOST>:8000/docs`) — установите `HOST` в `.env` или используйте `FRONTEND_URL`/`DEPLOY` конфигурацию.
  Bot-service слушает `http://bot:8080` внутри сети (и `http://127.0.0.1:8081` локально, если проброшено).
   Worker запускается и каждые 60 секунд проверяет напоминания.

---

## Ключевые файлы — кратко

### backend/app/main.py

* Роуты:

  * `POST /events/send` — создать событие и сразу отправить сообщение через bot-service; возвращает объект события с `sent=true` и `sent_message_id`.
  * `GET /events` — список событий (публичный, для календаря)
  * `GET /events/due_reminders` — внутренний endpoint для worker: возвращает события, у которых `reminder_sent=false` и `date - reminder_offset <= now + tolerance`.

### backend/app/models.py

* SQLAlchemy-модели: `Subject`, `Topic`, `Event`, `Admin`.
* Поля события: `id, type, subject_id, title, body, date, time, created_at, sent, sent_message_id, chat_id, topic_thread_id, reminder_offset, reminder_sent, source`

### bot/app.py

* FastAPI-приложение с endpoint `POST /send`:

  * Debug: принимает `chat_id, thread_id, text` и вызывает `bot.send_message(chat_id=..., message_thread_id=..., text=...)`.
  * Возвращает `message_id`.

### worker/worker.py

* APScheduler job, выполняющий запрос к `GET /events/due_reminders` и для каждого результата вызывает `POST bot/send` с подготовленным текстом напоминания.

---