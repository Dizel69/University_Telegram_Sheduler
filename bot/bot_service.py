import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bot-service")

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN хранится в переменных окружения")

TELEGRAM_HOST = "api.telegram.org"
API_BASE = f"https://{TELEGRAM_HOST}/bot{BOT_TOKEN}"

# Рабочие IP Telegram для явного route fallback
TELEGRAM_IPV6 = os.getenv("TELEGRAM_API_IPV6", "2001:67c:4e8:f004::9")
TELEGRAM_IPV4 = os.getenv("TELEGRAM_API_IPV4", "149.154.166.110")

app = FastAPI(title="Сервис бота М15")


async def _run_curl(args: list[str]) -> subprocess.CompletedProcess[str]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: subprocess.run(args, text=True, capture_output=True),
    )


async def _telegram_call(method: str, payload: dict) -> dict:
    url = f"{API_BASE}/{method}"
    payload_json = json.dumps(payload, ensure_ascii=False)

    # Пробуем маршруты по порядку: IPv6 -> IPv4 -> системный DNS.
    # Для первых двух явно фиксируем стек (-6/-4), чтобы curl не "перепрыгивал".
    route_variants = [
        {
            "name": "ipv6-resolve",
            "family_flag": "-6",
            "resolve": f"{TELEGRAM_HOST}:443:[{TELEGRAM_IPV6}]",
            "connect_timeout": "4",
            "max_time": "12",
        },
        {
            "name": "ipv4-resolve",
            "family_flag": "-4",
            "resolve": f"{TELEGRAM_HOST}:443:{TELEGRAM_IPV4}",
            "connect_timeout": "15",
            "max_time": "40",
        },
        {
            "name": "system-dns",
            "family_flag": None,
            "resolve": None,
            "connect_timeout": "8",
            "max_time": "25",
        },
    ]

    last_error = "unknown error"
    max_rounds = 3
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
            if route["family_flag"] is not None:
                cmd.append(route["family_flag"])
            if route["resolve"] is not None:
                cmd.extend(["--resolve", route["resolve"]])

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

            logger.info("Telegram curl success round=%s route=%s", round_idx, route["name"])
            return body

        # Пауза между раундами — даём сети "подышать"
        if round_idx < max_rounds:
            await asyncio.sleep(round_idx)

    raise HTTPException(status_code=502, detail=f"Telegram unreachable: {last_error}")


async def _telegram_call_multipart(method: str, fields: dict[str, object], file_field: str, file_path: str) -> dict:
    url = f"{API_BASE}/{method}"
    route_variants = [
        {"name": "ipv6-resolve", "family_flag": "-6", "resolve": f"{TELEGRAM_HOST}:443:[{TELEGRAM_IPV6}]", "connect_timeout": "4", "max_time": "12"},
        {"name": "ipv4-resolve", "family_flag": "-4", "resolve": f"{TELEGRAM_HOST}:443:{TELEGRAM_IPV4}", "connect_timeout": "15", "max_time": "40"},
        {"name": "system-dns", "family_flag": None, "resolve": None, "connect_timeout": "8", "max_time": "25"},
    ]

    last_error = "unknown error"
    for round_idx in range(1, 4):
        for route in route_variants:
            cmd = [
                "curl",
                "-sS",
                "--connect-timeout", route["connect_timeout"],
                "--max-time", route["max_time"],
                "-X", "POST", url,
            ]
            if route["family_flag"] is not None:
                cmd.append(route["family_flag"])
            if route["resolve"] is not None:
                cmd.extend(["--resolve", route["resolve"]])
            for k, v in fields.items():
                if v is None:
                    continue
                cmd.extend(["-F", f"{k}={v}"])
            cmd.extend(["-F", f"{file_field}=@{file_path}"])

            result = await _run_curl(cmd)
            if result.returncode != 0:
                last_error = (
                    f"round={round_idx} route={route['name']} rc={result.returncode} err={result.stderr.strip()}"
                )
                logger.warning("Telegram multipart curl failed: %s", last_error)
                continue
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                raise HTTPException(status_code=502, detail="Telegram returned invalid JSON")
        if round_idx < 3:
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


class CreateTopicRequest(BaseModel):
    """Запрос на создание темы в чате."""
    chat_id: int
    name: str


@app.post("/send")
async def send_message(req: SendRequest):
    """Отправляет сообщение в Telegram и возвращает ID сообщения."""
    try:
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
                if req.thread_id is not None:
                    payload["message_thread_id"] = req.thread_id
                body = await _telegram_call("sendPhoto", payload)
            else:
                media: list[dict[str, str]] = []
                for idx, photo in enumerate(photos):
                    item: dict[str, str] = {"type": "photo", "media": photo}
                    if idx == 0 and req.text:
                        item["caption"] = req.text
                    media.append(item)
                payload = {"chat_id": req.chat_id, "media": media}
                if req.thread_id is not None:
                    payload["message_thread_id"] = req.thread_id
                body = await _telegram_call("sendMediaGroup", payload)
        elif not documents:
            payload = {"chat_id": req.chat_id, "text": req.text}
            if req.thread_id is not None:
                payload["message_thread_id"] = req.thread_id
            body = await _telegram_call("sendMessage", payload)

        if documents:
            for idx, document in enumerate(documents):
                payload_doc: dict[str, object] = {"chat_id": req.chat_id, "document": document}
                if req.thread_id is not None:
                    payload_doc["message_thread_id"] = req.thread_id
                if not photos and idx == 0 and req.text:
                    payload_doc["caption"] = req.text
                doc_body = await _telegram_call("sendDocument", payload_doc)
                if idx == 0 and not photos:
                    body = doc_body

        local_photo_paths = []
        local_doc_paths = []
        for row in local_files:
            path = str(row.get("path") or "").strip()
            kind = str(row.get("kind") or "document").strip().lower()
            if not path or not Path(path).exists():
                continue
            if kind == "photo":
                local_photo_paths.append(path)
            else:
                local_doc_paths.append(path)

        for idx, path in enumerate(local_photo_paths):
            fields: dict[str, object] = {"chat_id": req.chat_id}
            if req.thread_id is not None:
                fields["message_thread_id"] = req.thread_id
            if idx == 0 and req.text:
                fields["caption"] = req.text
            photo_body = await _telegram_call_multipart("sendPhoto", fields, "photo", path)
            if idx == 0 and not photos and not documents:
                body = photo_body

        for idx, path in enumerate(local_doc_paths):
            fields = {"chat_id": req.chat_id}
            if req.thread_id is not None:
                fields["message_thread_id"] = req.thread_id
            if idx == 0 and req.text and not photos and not documents and not local_photo_paths:
                fields["caption"] = req.text
            doc_body = await _telegram_call_multipart("sendDocument", fields, "document", path)
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
        raise
    except Exception as e:
        # Не логируем URL (там BOT_TOKEN), поэтому только тип/текст исключения.
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


@app.get("/")
async def root():
    return {"service": "bot-service", "status": "ok"}


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/metrics")
async def metrics():
    # Не поддерживает Prometheus-метрики, но явный ответ уменьшает шум от 404.
    return {"ok": False, "detail": "metrics_not_implemented"}
