# University Telegram Scheduler (M15)

Микросервисный проект для ведения **календаря событий** (расписание/домашка/объявления/экзамены) и **отправки сообщений/напоминаний в Telegram**.

## Что в репозитории

- **`backend`**: FastAPI API + БД событий (SQLModel), формирует текст сообщений и дергает bot-service.
- **`bot`**: FastAPI сервис-обёртка над Telegram Bot API (отправка сообщений, создание тем/топиков).
- **`worker`**: APScheduler-воркер, периодически опрашивает backend на “пора напоминать” и отправляет напоминания через bot-service.
- **`frontend`**: React + Vite UI (публичный календарь и админ-панель).
- **`postgres`**: база данных (через `docker-compose.yml`).
- **`redis`**: сейчас поднимается в `docker-compose.yml`, но в коде core-флоу не завязан на Redis.

> В репозитории также есть папка `parser` (FastAPI + pdfplumber для парсинга PDF), **но в текущем `docker-compose.yml` она не подключена**.

## Быстрый старт (Docker)

### Предусловия

- Docker + Docker Compose
- Токен Telegram-бота (через `@BotFather`)
- (Опционально) `chat_id` нужного чата/супергруппы и `message_thread_id` темы (если используете форумные темы)

### 1) Создай `.env` в корне

Минимально необходимое:

```env
# Telegram
BOT_TOKEN=123456:ABCDEF...

# Backend auth (для админских действий с фронта)
ADMIN_TOKEN=change-me

# Database (backend читает DATABASE_URL)
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=m15db
DATABASE_URL=postgresql://postgres:postgres@postgres:5432/m15db

# URLs для связи сервисов (можно оставить дефолты)
BACKEND_URL=http://backend:8000
BOT_SERVICE_URL=http://bot:8081

# Если у сервера IPv4 до Telegram не работает, можно зафиксировать IPv6
# для bot-контейнера через docker-compose extra_hosts.
TELEGRAM_API_IPV6=2001:67c:4e8:f004::9

# Для ссылок в Telegram на карточку события в UI
# Если FRONTEND_URL не задан, backend попробует собрать его из HOST:3000
HOST=127.0.0.1
FRONTEND_URL=http://127.0.0.1:3000

# Дефолтный чат для отправки, если у события не задан chat_id
DEFAULT_CHAT_ID=-1001234567890

# Опционально: маршрутизация по типам событий (переопределяет DEFAULT_CHAT_ID)
CHAT_ID_SCHEDULE=-1001234567890
CHAT_ID_HOMEWORK=-1001234567890
CHAT_ID_ANNOUNCEMENTS=-1001234567890

# Опционально: темы/топики по типам (message_thread_id)
THREAD_ID_SCHEDULE=1
THREAD_ID_HOMEWORK=2
THREAD_ID_ANNOUNCEMENTS=3

# Worker
WORKER_POLL_INTERVAL=60
```

### 2) Запусти сервисы

```bash
docker compose up --build
```

### 3) Полезные адреса

- **Frontend (UI)**: `http://localhost:3000` (внутри контейнера Vite на `5173`, наружу проброшено на `3000`)
- **Backend API**: `http://localhost:8000`
  - Swagger: `http://localhost:8000/docs`
- **Backend метрики (Prometheus format)**: `http://localhost:8000/metrics`
- **Bot-service API**: `http://localhost:8081`
- **Prometheus**: `http://localhost:9090`
- **Grafana**: `http://localhost:3001` (по умолчанию `admin` / `admin`)

## Мониторинг (Prometheus + Grafana)

### Проверить, что backend отдаёт метрики

```bash
curl -s http://localhost:8000/metrics | head
```

### Проверить, что Prometheus видит backend (target UP)

Открой Prometheus → `Status` → `Targets` и убедись, что job `backend` в состоянии **UP**.

## Как это работает (в двух словах)

- **Создание/отправка поста**: frontend вызывает backend (админские эндпоинты требуют `X-ADMIN-TOKEN`), backend сохраняет событие и отправляет текст в `bot` (HTTP), `bot` шлёт сообщение в Telegram.
- **Напоминания**: `worker` раз в `WORKER_POLL_INTERVAL` секунд вызывает `GET /events/due_reminders`, для каждого события отправляет напоминание через `bot`, затем помечает событие как `reminder_sent=true`.
- **Маршрутизация**: chat/thread выбираются так:
  - если у события указаны `chat_id` / `topic_thread_id` — они приоритетны;
  - иначе используются переменные окружения `CHAT_ID_*` / `THREAD_ID_*`;
  - иначе fallback на `DEFAULT_CHAT_ID`.

## Типы событий

Backend нормализует типы в каноничные токены:

- **`schedule`** — расписание (в текущей логике при создании через `/events/send` напоминания не шлются)
- **`homework`** — домашнее задание (обычно с напоминаниями)
- **`exam_control`** — контрольная/экзамен (формат сообщения/напоминания чуть другой, поддерживает `lesson_type=exam|control`)
- **`announcement`** — объявление
- **`transfer`** — перенос/перемещение (может выставляться автоматически, если в тексте есть “перенос/перенес…”)

## Backend API (основное)

Адрес: `http://localhost:8000`

- **`GET /events`**: публичный список событий (для UI).
- **`GET /calendar?start=YYYY-MM-DD&end=YYYY-MM-DD&type=homework`**: календарная выдача с фильтрами.
- **`POST /events/send`**: создать событие и попытаться сразу отправить пост в Telegram (через bot-service). Требует `X-ADMIN-TOKEN`.
- **`POST /events`**: создать событие **без отправки** (помечается `source=manual`). Требует `X-ADMIN-TOKEN`.
- **`PUT /events/{event_id}?apply_to_series=false`**: обновить событие (и опционально всю серию).
- **`DELETE /events/{event_id}`**, **`DELETE /events/day?date=YYYY-MM-DD`**, **`DELETE /events/month?year=YYYY&month=M`**: удаление.
- **`GET /events/due_reminders`**: список “пора напоминать” (использует worker).
- **`POST /events/{event_id}/mark_reminder_sent`**: пометить напоминание отправленным (использует worker).
- **`POST /events/{event_id}/send_now`**: принудительно отправить уже существующее событие в Telegram. Требует `X-ADMIN-TOKEN`.
- **`GET /admin/validate`**: проверка админ-токена (для UI логина).

## Bot-service API

Адрес: `http://localhost:8081`

- **`POST /send`**: отправить сообщение (`chat_id`, `thread_id` опционально, `text`).
- **`POST /create_topic`**: создать тему в супергруппе (бот должен быть админом с правом управления темами).

## Frontend

- Vite dev-сервер запускается внутри контейнера и доступен снаружи на `:3000`.
- В dev-режиме настроен прокси на backend для путей `/api` и `/events`.

## CI/CD (GitHub Actions)

В `.github/workflows/ci-cd.yml` настроен простой деплой:

- на пуш в `main` код копируется на сервер по SCP,
- затем по SSH выполняется `docker compose down` и `docker compose up --build -d`.

Ожидаемые секреты репозитория:

- `DEPLOY_HOST`
- `DEPLOY_USER`
- `DEPLOY_KEY`
- `DEPLOY_PATH`

## Troubleshooting (частые проблемы)

- **Бот не отправляет в тему**: проверь `thread_id` (message_thread_id) и что чат — супергруппа с включёнными темами.
- **401/403 с фронта**: проверь `ADMIN_TOKEN` и заголовок `X-ADMIN-TOKEN`.
- **Ссылки в Telegram ведут не туда**: выставь `FRONTEND_URL` (или `HOST`, чтобы backend собрал `http://{HOST}:3000`).
- **Telegram доступен только по IPv6**: в `.env` задай `TELEGRAM_API_IPV6`, затем пересоздай `bot`. `docker-compose.yml` зафиксирует `api.telegram.org` на этот IPv6 через `extra_hosts`. Если контейнер всё равно не выходит по IPv6, нужно включить IPv6 в Docker на сервере или использовать VPN/proxy.

## Схема взаимодействия контейнеров

```mermaid
flowchart LR
    U[Пользователь / Браузер]
    TG[Telegram API]

    FE[frontend\n:3000->5173]
    BE[backend\n:8000]
    BOT[bot\n:8081]
    WRK[worker]
    PG[(postgres)]
    RD[(redis)]

    PR[prometheus\n:9090]
    GF[grafana\n:3001->3000]
    CAD[cadvisor\n:8082->8080]
    NE[node-exporter\n:9100]

    U -->|HTTP(S): UI, действия пользователя\n(логин, расписание, запросы)| FE
    FE -->|REST/JSON: запросы API\n(пользователи, расписание, настройки)| BE

    TG -->|Webhook/updates: сообщения, команды,\ncallback_query| BOT
    BOT -->|HTTP API (JSON): чтение/запись данных,\nсинхронизация состояния бота| BE
    BOT -->|sendMessage/editMessage и др.\n(Bot API JSON)| TG

    WRK -->|REST/JSON: получение задач,\nсобытий и данных расписания| BE
    WRK -->|Redis commands: очереди/кэши,\nключи задач и таймеров| RD
    WRK -->|HTTP к bot-сервису: триггер отправки\nуведомлений/напоминаний| BOT

    BE -->|SQL (INSERT/SELECT/UPDATE):\nпользователи, расписание, состояния| PG
    BE -->|Redis commands: кэш,\nвременные данные, rate-limit| RD

    PR -->|scrape /metrics: метрики приложения\n(HTTP latency, ошибки, бизнес-метрики)| BE
    PR -->|scrape /metrics: метрики контейнеров\n(CPU/RAM/FS/network)| CAD
    PR -->|scrape /metrics: метрики хоста\n(load, mem, disk, net)| NE
    GF -->|PromQL queries: чтение временных рядов\nдля панелей и алертов| PR
```
