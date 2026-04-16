import asyncio
import json
import logging
import os
import subprocess
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
        },
        {
            "name": "ipv4-resolve",
            "family_flag": "-4",
            "resolve": f"{TELEGRAM_HOST}:443:{TELEGRAM_IPV4}",
        },
        {
            "name": "system-dns",
            "family_flag": None,
            "resolve": None,
        },
    ]

    last_error = "unknown error"
    for route in route_variants:
        cmd = [
            "curl",
            "-sS",
            "--connect-timeout",
            "8",
            "--max-time",
            "25",
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

        logger.info("Telegram curl try route=%s", route["name"])
        result = await _run_curl(cmd)
        if result.returncode != 0:
            last_error = (
                f"route={route['name']} rc={result.returncode} "
                f"err={result.stderr.strip()}"
            )
            logger.warning("Telegram curl failed: %s", last_error)
            continue

        try:
            body = json.loads(result.stdout)
        except json.JSONDecodeError:
            logger.warning("Telegram returned non-JSON: %s", result.stdout[:200])
            raise HTTPException(status_code=502, detail="Telegram returned invalid JSON")

        logger.info("Telegram curl success route=%s", route["name"])
        return body

    raise HTTPException(status_code=502, detail=f"Telegram unreachable: {last_error}")


class SendRequest(BaseModel):
    """Запрос на отправку сообщения."""
    chat_id: int
    thread_id: int | None = None
    text: str


class CreateTopicRequest(BaseModel):
    """Запрос на создание темы в чате."""
    chat_id: int
    name: str


@app.post("/send")
async def send_message(req: SendRequest):
    """Отправляет сообщение в Telegram и возвращает ID сообщения."""
    try:
        logger.info("POST /send payload: %s", req.dict())
        payload: dict[str, object] = {"chat_id": req.chat_id, "text": req.text}
        if req.thread_id is not None:
            payload["message_thread_id"] = req.thread_id

        body = await _telegram_call("sendMessage", payload)

        if not body.get("ok"):
            logger.warning("Telegram API error payload: %s", body)
            raise HTTPException(
                status_code=502,
                detail=f"Telegram API error: {body}",
            )

        msg = body.get("result") or {}
        message_id = msg.get("message_id")
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
