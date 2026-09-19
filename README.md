# University Telegram Scheduler (M15)

Микросервисный проект для ведения **календаря событий** (расписание/домашка/объявления/экзамены) и **отправки сообщений/напоминаний в Telegram**.

## Что в репозитории

- **`backend`**: FastAPI API + БД событий (SQLModel), формирует текст сообщений и дергает bot-service.
- **`bot`**: FastAPI сервис-обёртка над Telegram Bot API (отправка сообщений, создание тем/топиков).
- **`worker`**: APScheduler-воркер, периодически опрашивает backend на “пора напоминать” и отправляет напоминания через bot-service.
- **`frontend`**: React + Vite UI (публичный календарь и админ-панель).
- **`postgres`**: база данных (через `docker-compose.yml`).

> В репозитории также есть папка `parser` (FastAPI + pdfplumber для парсинга PDF), **но в текущем `docker-compose.yml` она не подключена** Она будет удалена.

## Быстрый старт (Docker)

### Предусловия

- Docker + Docker Compose
- Токен Telegram-бота (через `@BotFather`)
- (Опционально) `chat_id` нужного чата/супергруппы и `message_thread_id` темы (если используете форумные темы)

### 1) Создай `.env` в корне

Минимально необходимое:

```env
# Telegram
BOT_TOKEN=123456:ABCDEF....

# Backend auth (для админских действий с фронта)
ADMIN_TOKEN=change-me

# Database (backend читает DATABASE_URL)
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=m15db
DATABASE_URL=postgresql://postgres:postgres@postgres:5432/m15db

# Схема БД при старте backend: SQLModel.metadata.create_all добавляет **отсутствующие**
# таблицы по моделям. Дополнительные идемпотентные изменения (ALTER и т.п. для старых БД)
# — в `backend/app/schema_migrations.py` (функция `apply_additive_schema_migrations`),
# она вызывается из `init_db()`.

# URLs для связи сервисов (можно оставить дефолты)
BACKEND_URL=http://backend:8000
BOT_SERVICE_URL=http://bot:8081

# Если у сервера IPv4 до Telegram не работает, можно зафиксировать IPv6
# для bot-контейнера через docker-compose extra_hosts.
TELEGRAM_API_IPV6=2001:67c:4e8:f004::9
# Если IPv4 и IPv6 до Telegram режутся провайдером — SOCKS/HTTP прокси.
# Это НЕ готовый адрес: прокси должен реально слушать указанный порт.
# TELEGRAM_PROXY=socks5h://127.0.0.1:1080

# Либо свой релей Bot API (Cloudflare Worker и т.п.), если api.telegram.org
# недоступен с сервера. Релей должен проксировать путь /bot<token>/<method>.
# TELEGRAM_API_BASE=https://tg-relay.example.workers.dev

# Для ссылок в Telegram на карточку события в UI
# Если FRONTEND_URL не задан, backend попробует собрать его из HOST:3000
HOST=sysprog.duckdns.org
FRONTEND_URL=https://sysprog.duckdns.org
BACKEND_PUBLIC_URL=https://sysprog.duckdns.org
PUBLIC_HOST=sysprog.duckdns.org

# Дефолтный чат для отправки, если у события не задан chat_id
DEFAULT_CHAT_ID=-1001234567890

# Личный чат с ботом для багов/предложений с сайта (положительный Telegram user id).
# Не ставь сюда id группы — иначе сообщения попадут в беседу.
# Как получить: напиши боту /start, затем узнай свой id через @userinfobot.
FEEDBACK_CHAT_ID=123456789

# Общий секрет backend ↔ bot ↔ worker для /internal/bot/* (если пусто — берётся ADMIN_TOKEN).
# INTERNAL_SERVICE_TOKEN=change-me-internal

# Утреннее расписание в личку (Europe/Moscow). Если на день пар нет — бот молчит.
# DM_MORNING_SCHEDULE_TIME=07:30

# Bot-сервис (network_mode: host) ходит в backend на localhost:
# BACKEND_URL=http://127.0.0.1:8000

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

- **Frontend (UI)**: `https://sysprog.duckdns.org` (Caddy на `:80`/`:443`, Let's Encrypt). Запасной вход без HTTPS: `http://localhost:3000`
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
- **`POST /feedback`**: баг или предложение с сайта. Уходит в личку бота (`FEEDBACK_CHAT_ID`), не в групповую беседу. Авторизация не обязательна.

## Bot-service API

Адрес: `http://localhost:8081`

- **`POST /send`**: отправить сообщение (`chat_id`, `thread_id` опционально, `text`).
- **`POST /create_topic`**: создать тему в супергруппе (бот должен быть админом с правом управления темами).
- **`GET /health`**: liveness; для личного бота ещё поля `polling` / `last_poll_ok_at` (long polling `getUpdates` внутри bot-сервиса, тот же curl IPv6/IPv4 канал).

Студент в **личке** логинится тем же логином/паролем, что на сайте (`telegram_id` на `app_user`). В группах команды не обслуживаются. Копии постов в личку — только при включённом зеркале; групповые reminder’ы воркера в личку не дублируются. Утреннее расписание и пинги ДЗ идут только в ЛС по флагам из `/настройки`. Внутренние эндпоинты backend: `/internal/bot/*` (заголовок `X-INTERNAL-TOKEN`).

## Frontend

- Vite dev-сервер запускается внутри контейнера и доступен снаружи на `:3000`.
- В dev-режиме настроен прокси на backend для путей `/api` и `/events`.

## CI/CD (GitHub Actions)

В `.github/workflows/ci-cd.yml` деплой зависит от изменённых файлов:

- коммит с префиксом `docs` по-прежнему пропускается целиком;
- изменения только в мониторинге (`prometheus.yml`, `grafana/`, `loki-config.yml`, `fluent-bit/`, `blackbox.yml`) перезапускают только мониторинг;
- изменения вне мониторинга не трогают Prometheus/Grafana/Loki и остальные exporter'ы;
- если в одном пуше есть и то и другое (или изменён `docker-compose.yml`), job'ы приложения и мониторинга идут параллельно.

Код копируется на сервер по SCP, затем по SSH выполняется точечный `docker compose up` без `docker compose down` всего стека.

Ожидаемые секреты репозитория:

- `DEPLOY_HOST`
- `DEPLOY_USER`
- `DEPLOY_KEY`
- `DEPLOY_PATH`

## Troubleshooting (частые проблемы)

- **Бот не отправляет в тему**: проверь `thread_id` (message_thread_id) и что чат — супергруппа с включёнными темами.
- **401/403 с фронта**: проверь `ADMIN_TOKEN` и заголовок `X-ADMIN-TOKEN`.
- **Ссылки в Telegram ведут не туда**: выставь `FRONTEND_URL` (например `https://sysprog.duckdns.org`).
- **HTTPS не поднимается**: открой на сервере/роутере TCP `80` и `443`, затем `docker compose logs caddy`.
- **Telegram доступен только по IPv6**: в `.env` задай `TELEGRAM_API_IPV6`, затем пересоздай `bot`. Бот сам пробует IPv6 → IPv4 → DNS и запоминает рабочий маршрут.
- **Telegram режется и по IPv4, и по IPv6** (все маршруты дают `curl (28)`, а какой-то IP отвечает не-TLS мусором — `wrong version number`): нужен выход мимо сети хостера. Два варианта, оба требуют пересоздать `bot`:
  - свой релей Bot API: `TELEGRAM_API_BASE=https://<твой-релей>` (тогда пиннинг IP отключается, бот ходит одним маршрутом);
  - SOCKS/HTTP прокси: `TELEGRAM_PROXY=socks5h://host:port`.

  Проверка, что прокси вообще живой (пустой ответ или `connection refused` — значит порт никто не слушает):

  ```bash
  docker compose exec bot sh -c 'printenv TELEGRAM_PROXY'
  docker compose exec bot sh -c 'curl -sS -o /dev/null -w "%{http_code} %{time_total}\n" --max-time 15 -x "$TELEGRAM_PROXY" https://api.telegram.org'
  ```

  MTProto-прокси из Telegram-каналов (`tg://proxy?server=...&secret=...`) для Bot API **не годятся**: это отдельный протокол для клиентов, curl через него в `api.telegram.org` не пойдёт.

### Релей Bot API на Cloudflare Workers

Код в `tg-relay/`. Воркер принимает `/bot<token>/<method>` и пересылает в Telegram; `ALLOWED_BOT_TOKEN` не даёт использовать его как открытый релей для чужих ботов.

Деплой (с машины, где Telegram и Cloudflare доступны):

```bash
cd tg-relay
npx wrangler login
npx wrangler deploy                         # выдаст https://tg-relay.<аккаунт>.workers.dev
# Секрет кладётся после деплоя: до него воркера ещё нет.
# Имя секрета вводится в команде, значение (BOT_TOKEN вида 123456:AA...) — в ответ на запрос.
npx wrangler secret put ALLOWED_BOT_TOKEN
```

Проверка релея и подключение на сервере:

```bash
curl -sS "https://tg-relay.<аккаунт>.workers.dev/bot<BOT_TOKEN>/getMe"   # ожидается {"ok":true,...}

# в .env на сервере
TELEGRAM_API_BASE=https://tg-relay.<аккаунт>.workers.dev

docker compose up -d --force-recreate bot
docker compose logs bot --tail 20 | grep 'Telegram transport'
```

В логе должно быть `base=https://tg-relay...`, а `/health/telegram` — снова `ok`. Токен виден в URL, поэтому релей должен быть **твой**, и ссылку на воркер лучше не публиковать.
- **Бот молчит в личке**: long polling (`getUpdates`) идёт тем же каналом, что и отправка. Если в Grafana растёт «Недоступность Telegram», бот **не видит** входящие. Проверь `docker compose logs bot | grep -E 'getUpdates|Telegram curl failed'`. Можно задать запасные IPv4: `TELEGRAM_API_IPV4_EXTRA=149.154.167.99,149.154.167.91`. Если IPv6 у тебя единственный рабочий путь — `TELEGRAM_PREFER_IPV6=1`.
- **Обратная связь / дни рождения не уходят, в Grafana «Telegram недоступен»**: смотри `worker_telegram_reachable` и логи `bot` (`Telegram unreachable`). Мониторинг теперь бьёт в `/health/telegram` бота, а не напрямую в `api.telegram.org` из docker-сети.
- **Обратная связь не приходит в личку**: `FEEDBACK_CHAT_ID` должен быть **твоим** числовым user id (положительное число), не `DEFAULT_CHAT_ID` группы. Сначала открой бота и нажми `/start` — иначе Telegram запретит боту писать первым.

## Схема взаимодействия контейнеров

```mermaid
flowchart LR
    %% Внешние акторы
    U[Пользователь / Браузер]
    TG[Telegram API]

    %% Контейнеры приложения
    CADDY["caddy\n:80/:443"]
    FE["frontend\n:3000->5173"]
    BE["backend\n:8000"]
    BOT["bot\n:8081"]
    WRK[worker]
    PG[(postgres)]

    %% Мониторинг
    PR["prometheus\n:9090"]
    GF["grafana\n:3001->3000"]
    CAD["cadvisor\n:8082->8080"]
    NE["node-exporter\n:9100"]

    %% Пользовательские потоки
    U -->|"HTTPS :443 (без порта)"| CADDY
    CADDY -->|reverse proxy| FE
    FE -->|"REST/JSON: запросы API\n(пользователи, расписание, настройки)"| BE

    %% Telegram-потоки
    TG -->|"Webhook/updates: сообщения, команды,\ncallback_query"| BOT
    BOT -->|"HTTP API (JSON): чтение/запись данных,\nсинхронизация состояния бота"| BE
    BOT -->|"sendMessage/editMessage и др.\n(Bot API JSON)"| TG

    %% Worker-потоки
    WRK -->|"REST/JSON: получение задач,\nсобытий и данных расписания"| BE
    WRK -->|"HTTP к bot-сервису: триггер отправки\nуведомлений/напоминаний"| BOT

    %% Backend-хранилища
    BE -->|"SQL (INSERT/SELECT/UPDATE):\nпользователи, расписание, состояния"| PG

    %% Метрики и дашборды
    PR -->|"scrape /metrics: метрики приложения\n(HTTP latency, ошибки, бизнес-метрики)"| BE
    PR -->|"scrape /metrics: метрики контейнеров\n(CPU/RAM/FS/network)"| CAD
    PR -->|"scrape /metrics: метрики хоста\n(load, mem, disk, net)"| NE
    GF -->|"PromQL queries: чтение временных рядов\nдля панелей и алертов"| PR

```
