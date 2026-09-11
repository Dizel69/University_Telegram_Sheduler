import asyncio
import json
import logging
import os
import subprocess
import time as _time
from pathlib import Path
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from starlette.responses import Response
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from telegram_html import sanitize_telegram_html
from menu_keyboard import menu_keyboard

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bot-service")

# Prometheus-метрики бота
TELEGRAM_MESSAGES_SENT = Counter(
    "telegram_messages_sent_total", "Успешные вызовы Telegram API (транспорт)"
)
TELEGRAM_SEND_ERRORS = Counter(
    "telegram_send_errors_total", "Ошибки при отправке через бот-сервис"
)
TELEGRAM_UNREACHABLE = Counter(
    "telegram_unreachable_total", "Случаи, когда Telegram API был недоступен"
)
TELEGRAM_REQUEST_DURATION = Histogram(
    "telegram_request_duration_seconds", "Длительность вызова Telegram API"
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN хранится в переменных окружения")

TELEGRAM_HOST = "api.telegram.org"
API_BASE = f"https://{TELEGRAM_HOST}/bot{BOT_TOKEN}"

# Рабочие IP Telegram для явного route fallback
TELEGRAM_IPV6 = os.getenv("TELEGRAM_API_IPV6", "2001:67c:4e8:f004::9")
TELEGRAM_IPV4 = os.getenv("TELEGRAM_API_IPV4", "149.154.166.110")
# Опционально: socks5h://127.0.0.1:1080 или http://user:pass@host:port
TELEGRAM_PROXY = (os.getenv("TELEGRAM_PROXY") or "").strip()

# Последний успешный маршрут — его пробуем первым, чтобы мёртвый IPv6 не съедал таймаут.
_last_good_route: str | None = None

app = FastAPI(title="Сервис бота М15")


def _route_variants(*, long_poll: bool = False, quick: bool = False) -> list[dict]:
    if TELEGRAM_PROXY:
        if long_poll:
            timeout = ("10", "45")
        elif quick:
            timeout = ("3", "8")
        else:
            timeout = ("8", "25")
        return [
            {
                "name": "proxy",
                "family_flag": None,
                "resolve": None,
                "connect_timeout": timeout[0],
                "max_time": timeout[1],
            }
        ]
    if long_poll:
        return [
            {
                "name": "ipv6-resolve",
                "family_flag": "-6",
                "resolve": f"{TELEGRAM_HOST}:443:[{TELEGRAM_IPV6}]",
                "connect_timeout": "4",
                "max_time": "40",
            },
            {
                "name": "ipv4-resolve",
                "family_flag": "-4",
                "resolve": f"{TELEGRAM_HOST}:443:{TELEGRAM_IPV4}",
                "connect_timeout": "8",
                "max_time": "45",
            },
            {
                "name": "system-dns",
                "family_flag": None,
                "resolve": None,
                "connect_timeout": "8",
                "max_time": "45",
            },
        ]
    if quick:
        return [
            {
                "name": "ipv6-resolve",
                "family_flag": "-6",
                "resolve": f"{TELEGRAM_HOST}:443:[{TELEGRAM_IPV6}]",
                "connect_timeout": "2",
                "max_time": "6",
            },
            {
                "name": "ipv4-resolve",
                "family_flag": "-4",
                "resolve": f"{TELEGRAM_HOST}:443:{TELEGRAM_IPV4}",
                "connect_timeout": "3",
                "max_time": "8",
            },
            {
                "name": "system-dns",
                "family_flag": None,
                "resolve": None,
                "connect_timeout": "3",
                "max_time": "8",
            },
        ]
    return [
        {
            "name": "ipv6-resolve",
            "family_flag": "-6",
            "resolve": f"{TELEGRAM_HOST}:443:[{TELEGRAM_IPV6}]",
            "connect_timeout": "2",
            "max_time": "12",
        },
        {
            "name": "ipv4-resolve",
            "family_flag": "-4",
            "resolve": f"{TELEGRAM_HOST}:443:{TELEGRAM_IPV4}",
            "connect_timeout": "5",
            "max_time": "25",
        },
        {
            "name": "system-dns",
            "family_flag": None,
            "resolve": None,
            "connect_timeout": "5",
            "max_time": "20",
        },
    ]


def _ordered_routes(routes: list[dict]) -> list[dict]:
    if not _last_good_route:
        return list(routes)
    preferred = [r for r in routes if r["name"] == _last_good_route]
    rest = [r for r in routes if r["name"] != _last_good_route]
    return preferred + rest


def _apply_route_flags(cmd: list[str], route: dict) -> None:
    if TELEGRAM_PROXY:
        cmd.extend(["-x", TELEGRAM_PROXY])
    if route["family_flag"] is not None:
        cmd.append(route["family_flag"])
    if route["resolve"] is not None:
        cmd.extend(["--resolve", route["resolve"]])


async def _run_curl(args: list[str]) -> subprocess.CompletedProcess[str]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: subprocess.run(args, text=True, capture_output=True),
    )


async def _telegram_call(method: str, payload: dict, *, long_poll: bool = False, quick: bool = False) -> dict:
    global _last_good_route
    url = f"{API_BASE}/{method}"
    payload_json = json.dumps(payload, ensure_ascii=False)

    # IPv6 -> IPv4 -> DNS, но первый — последний успешный маршрут.
    route_variants = _ordered_routes(_route_variants(long_poll=long_poll, quick=quick))
    max_rounds = 1 if long_poll or quick else 2

    last_error = "unknown error"
    _started = _time.perf_counter()
    for round_idx in range(1, max_rounds + 1):
        for route in route_variants:
            cmd = [
                "curl",
                "-sS",
                "--connect-timeout",
                route["connect_timeout"],
                "--max-time",
                route["max_time"],
                "-X",
                "POST",
                url,
                "-H",
                "Content-Type: application/json",
                "-d",
                payload_json,
            ]
            _apply_route_flags(cmd, route)

            if method != "getUpdates":
                logger.info("Telegram curl try round=%s route=%s", round_idx, route["name"])
            result = await _run_curl(cmd)
            if result.returncode != 0:
                last_error = (
                    f"round={round_idx} route={route['name']} rc={result.returncode} "
                    f"err={result.stderr.strip()}"
                )
                logger.warning("Telegram curl failed: %s", last_error)
                continue

            try:
                body = json.loads(result.stdout)
            except json.JSONDecodeError:
                logger.warning("Telegram returned non-JSON: %s", result.stdout[:200])
                raise HTTPException(status_code=502, detail="Telegram returned invalid JSON")

            _last_good_route = route["name"]
            if method not in {"getUpdates", "getMe", "deleteWebhook"}:
                logger.info("Telegram curl success round=%s route=%s", round_idx, route["name"])
                TELEGRAM_MESSAGES_SENT.inc()
                TELEGRAM_REQUEST_DURATION.observe(_time.perf_counter() - _started)
            elif method != "getUpdates":
                logger.info("Telegram curl success round=%s route=%s method=%s", round_idx, route["name"], method)
            return body

        # Пауза между раундами — даём сети "подышать"
        if round_idx < max_rounds:
            await asyncio.sleep(round_idx)

    if method != "getMe":
        TELEGRAM_UNREACHABLE.inc()
    raise HTTPException(status_code=502, detail=f"Telegram unreachable: {last_error}")


async def _telegram_call_multipart(method: str, fields: dict[str, object], file_field: str, file_path: str, filename: str | None = None) -> dict:
    global _last_good_route
    url = f"{API_BASE}/{method}"
    route_variants = _ordered_routes(_route_variants())

    last_error = "unknown error"
    for round_idx in range(1, 3):
        for route in route_variants:
            cmd = [
                "curl",
                "-sS",
                "--connect-timeout", route["connect_timeout"],
                "--max-time", route["max_time"],
                "-X", "POST", url,
            ]
            _apply_route_flags(cmd, route)
            for k, v in fields.items():
                if v is None:
                    continue
                cmd.extend(["-F", f"{k}={v}"])
            # Сохраняем оригинальное имя файла (иначе Telegram возьмёт имя из storage_key).
            # curl: запятые/точки с запятой в имени экранируем, чтобы не сломать синтаксис -F.
            file_spec = f"{file_field}=@{file_path}"
            if filename:
                safe = filename.replace("\\", "_").replace('"', "_").replace(";", "_").replace(",", "_")
                file_spec += f";filename={safe}"
            cmd.extend(["-F", file_spec])

            result = await _run_curl(cmd)
            if result.returncode != 0:
                last_error = (
                    f"round={round_idx} route={route['name']} rc={result.returncode} err={result.stderr.strip()}"
                )
                logger.warning("Telegram multipart curl failed: %s", last_error)
                continue
            try:
                body = json.loads(result.stdout)
            except json.JSONDecodeError:
                raise HTTPException(status_code=502, detail="Telegram returned invalid JSON")
            _last_good_route = route["name"]
            return body
        if round_idx < 2:
            await asyncio.sleep(round_idx)
    raise HTTPException(status_code=502, detail=f"Telegram unreachable: {last_error}")


class SendRequest(BaseModel):
    """Запрос на отправку сообщения."""
    chat_id: int
    thread_id: int | None = None
    text: str
    photos: list[str] | None = None
    documents: list[str] | None = None
    local_files: list[dict] | None = None
    reply_markup: dict | None = None


class CreateTopicRequest(BaseModel):
    """Запрос на создание темы в чате."""
    chat_id: int
    name: str


def _effective_thread_id(thread_id: int | None) -> int | None:
    """General (1) нельзя передавать в API — omit для постинга в General."""
    if thread_id is None:
        return None
    try:
        tid = int(thread_id)
    except (TypeError, ValueError):
        return None
    return None if tid == 1 else tid


def _owner_feedback_menu_markup(chat_id: int, existing: dict | None) -> dict | None:
    """В личке владельца (FEEDBACK_CHAT_ID) оставляем меню бота вместе с отзывом.

    Групповые посты (отрицательный chat_id) не трогаем. Явный reply_markup не перезаписываем.
    """
    if existing is not None:
        return existing
    raw = (os.getenv("FEEDBACK_CHAT_ID") or "").strip()
    if not raw:
        return None
    try:
        owner_id = int(raw)
    except ValueError:
        return None
    if owner_id <= 0 or int(chat_id) != owner_id:
        return None
    return menu_keyboard()


def _apply_html_text(payload: dict, key: str = "text") -> None:
    """Санитизирует текст и включает parse_mode=HTML, чтобы эффекты были видны в Telegram."""
    raw = payload.get(key)
    if raw is None or raw == "":
        return
    payload[key] = sanitize_telegram_html(str(raw))
    payload["parse_mode"] = "HTML"


@app.post("/send")
async def send_message(req: SendRequest):
    """Отправляет сообщение в Telegram и возвращает ID сообщения."""
    try:
        thread_id = _effective_thread_id(req.thread_id)
        logger.info("POST /send payload: %s", req.dict())
        photos = [str(p).strip() for p in (req.photos or []) if str(p).strip()]
        documents = [str(p).strip() for p in (req.documents or []) if str(p).strip()]
        local_files = [x for x in (req.local_files or []) if isinstance(x, dict)]
        if len(photos) > 10:
            raise HTTPException(status_code=400, detail="Telegram supports up to 10 photos in media group")

        body: dict = {"ok": True, "result": {}}
        if photos:
            if len(photos) == 1:
                payload: dict[str, object] = {"chat_id": req.chat_id, "photo": photos[0], "caption": req.text}
                if thread_id is not None:
                    payload["message_thread_id"] = thread_id
                _apply_html_text(payload, "caption")
                body = await _telegram_call("sendPhoto", payload)
            else:
                media: list[dict[str, str]] = []
                for idx, photo in enumerate(photos):
                    item: dict[str, str] = {"type": "photo", "media": photo}
                    if idx == 0 and req.text:
                        item["caption"] = req.text
                        _apply_html_text(item, "caption")
                    media.append(item)
                payload = {"chat_id": req.chat_id, "media": media}
                if thread_id is not None:
                    payload["message_thread_id"] = thread_id
                body = await _telegram_call("sendMediaGroup", payload)
        elif not documents:
            payload = {"chat_id": req.chat_id, "text": req.text}
            if thread_id is not None:
                payload["message_thread_id"] = thread_id
            markup = _owner_feedback_menu_markup(req.chat_id, req.reply_markup)
            if markup is not None:
                payload["reply_markup"] = markup
            _apply_html_text(payload, "text")
            body = await _telegram_call("sendMessage", payload)

        if documents:
            for idx, document in enumerate(documents):
                payload_doc: dict[str, object] = {"chat_id": req.chat_id, "document": document}
                if thread_id is not None:
                    payload_doc["message_thread_id"] = thread_id
                if not photos and idx == 0 and req.text:
                    payload_doc["caption"] = req.text
                    _apply_html_text(payload_doc, "caption")
                doc_body = await _telegram_call("sendDocument", payload_doc)
                if idx == 0 and not photos:
                    body = doc_body

        local_photo_paths = []
        local_doc_paths = []
        for row in local_files:
            path = str(row.get("path") or "").strip()
            kind = str(row.get("kind") or "document").strip().lower()
            name = str(row.get("name") or "").strip() or None
            if not path or not Path(path).exists():
                continue
            if kind == "photo":
                local_photo_paths.append((path, name))
            else:
                local_doc_paths.append((path, name))

        for idx, (path, name) in enumerate(local_photo_paths):
            fields: dict[str, object] = {"chat_id": req.chat_id}
            if thread_id is not None:
                fields["message_thread_id"] = thread_id
            if idx == 0 and req.text:
                fields["caption"] = req.text
                _apply_html_text(fields, "caption")
            photo_body = await _telegram_call_multipart("sendPhoto", fields, "photo", path, filename=name)
            if idx == 0 and not photos and not documents:
                body = photo_body

        for idx, (path, name) in enumerate(local_doc_paths):
            fields = {"chat_id": req.chat_id}
            if thread_id is not None:
                fields["message_thread_id"] = thread_id
            if idx == 0 and req.text and not photos and not documents and not local_photo_paths:
                fields["caption"] = req.text
                _apply_html_text(fields, "caption")
            doc_body = await _telegram_call_multipart("sendDocument", fields, "document", path, filename=name)
            if idx == 0 and not photos and not documents and not local_photo_paths:
                body = doc_body

        if not body.get("ok"):
            logger.warning("Telegram API error payload: %s", body)
            raise HTTPException(
                status_code=502,
                detail=f"Telegram API error: {body}",
            )

        result_obj = body.get("result") or {}
        if isinstance(result_obj, list):
            first = result_obj[0] if result_obj else {}
            message_id = first.get("message_id")
        else:
            message_id = result_obj.get("message_id")
        logger.info("Telegram send OK: message_id=%s chat_id=%s", message_id, req.chat_id)
        return {"ok": True, "message_id": message_id}
    except HTTPException:
        TELEGRAM_SEND_ERRORS.inc()
        raise
    except Exception as e:
        # Не логируем URL (там BOT_TOKEN), поэтому только тип/текст исключения.
        TELEGRAM_SEND_ERRORS.inc()
        logger.exception("Unexpected send failure: %s", type(e).__name__)
        raise HTTPException(status_code=500, detail="Unexpected bot-service error")


@app.post("/create_topic")
async def create_topic(req: CreateTopicRequest):
    """
    Создаёт форум/тему в супергруппе и возвращает её message_thread_id.
    Требуется, чтобы бот был админом с правами управления темами.
    """
    try:
        logger.info("POST /create_topic payload: %s", req.dict())
        payload = {"chat_id": req.chat_id, "name": req.name}
        body = await _telegram_call("createForumTopic", payload)

        if not body.get("ok"):
            logger.warning("Telegram API error payload (create_topic): %s", body)
            raise HTTPException(
                status_code=502,
                detail=f"Telegram API error: {body}",
            )

        result_obj = body.get("result") or {}
        thread_id = result_obj.get("message_thread_id")
        logger.info("Create topic result message_thread_id: %s", thread_id)
        return {"ok": True, "message_thread_id": thread_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unexpected create_topic failure: %s", type(e).__name__)
        raise HTTPException(status_code=500, detail="Unexpected bot-service error")


@app.on_event("startup")
async def _start_dm_polling():
    flag = (os.getenv("DISABLE_TELEGRAM_POLLING") or "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        logger.info("Telegram polling disabled (DISABLE_TELEGRAM_POLLING)")
        return
    import dm_bot

    asyncio.create_task(dm_bot.poll_loop(), name="telegram-long-polling")


@app.get("/")
async def root():
    return {"service": "bot-service", "status": "ok"}


@app.get("/health")
async def health():
    import dm_bot
    import time as _t

    last = dm_bot.last_poll_ok_at
    stale = True
    if last is not None:
        stale = (_t.time() - last) > 90
    polling_on = dm_bot.polling_enabled
    ok = True
    if polling_on and stale and last is not None:
        ok = False
    return {
        "ok": ok,
        "polling": polling_on,
        "last_poll_ok_at": last,
    }


@app.get("/health/telegram")
async def health_telegram():
    """Проверка реального канала отправки: bot-service -> Telegram API.

    503, если Telegram недоступен — так blackbox и воркер видят ту же правду.
    """
    started = _time.perf_counter()
    try:
        body = await _telegram_call("getMe", {}, quick=True)
        if not body.get("ok"):
            raise HTTPException(status_code=502, detail=f"Telegram API error: {body}")
        return {"ok": True, "latency_seconds": _time.perf_counter() - started}
    except HTTPException as e:
        return Response(
            content=json.dumps({
                "ok": False,
                "latency_seconds": _time.perf_counter() - started,
                "detail": str(e.detail),
            }),
            status_code=503,
            media_type="application/json",
        )
    except Exception as e:
        return Response(
            content=json.dumps({
                "ok": False,
                "latency_seconds": _time.perf_counter() - started,
                "detail": f"{type(e).__name__}: {e}",
            }),
            status_code=503,
            media_type="application/json",
        )


@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
