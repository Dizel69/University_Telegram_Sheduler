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

API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

app = FastAPI(title="Сервис бота М15")


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
        payload: dict[str, object] = {
            "chat_id": req.chat_id,
            "text": req.text,
        }
        if req.thread_id is not None:
            payload["message_thread_id"] = req.thread_id

        url = f"{API_BASE}/sendMessage"
        data = json.dumps(payload)

        cmd = [
            "curl",
            "-sS",
            "-X",
            "POST",
            url,
            "-H",
            "Content-Type: application/json",
            "-d",
            data,
        ]

        loop = asyncio.get_running_loop()
        result: subprocess.CompletedProcess[str] = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                cmd,
                text=True,
                capture_output=True,
            ),
        )

        if result.returncode != 0:
            logger.warning(
                "curl sendMessage failed: rc=%s stderr=%s",
                result.returncode,
                result.stderr,
            )
            raise HTTPException(
                status_code=502,
                detail=f"Telegram send curl failed: {result.stderr.strip()}",
            )

        try:
            body = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            logger.warning("Telegram send invalid JSON: %s", e)
            raise HTTPException(
                status_code=502,
                detail="Telegram returned invalid JSON",
            )

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
    except Exception as e:
        logger.exception("Unexpected send failure")
        raise HTTPException(status_code=500, detail=f"Unexpected bot-service error: {e}")


@app.post("/create_topic")
async def create_topic(req: CreateTopicRequest):
    """
    Создаёт форум/тему в супергруппе и возвращает её message_thread_id.
    Требуется, чтобы бот был админом с правами управления темами.
    """
    try:
        logger.info("POST /create_topic payload: %s", req.dict())

        payload = {
            "chat_id": req.chat_id,
            "name": req.name,
        }
        url = f"{API_BASE}/createForumTopic"
        data = json.dumps(payload)

        cmd = [
            "curl",
            "-sS",
            "-X",
            "POST",
            url,
            "-H",
            "Content-Type: application/json",
            "-d",
            data,
        ]

        loop = asyncio.get_running_loop()
        result: subprocess.CompletedProcess[str] = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                cmd,
                text=True,
                capture_output=True,
            ),
        )

        if result.returncode != 0:
            logger.warning(
                "curl createForumTopic failed: rc=%s stderr=%s",
                result.returncode,
                result.stderr,
            )
            raise HTTPException(
                status_code=502,
                detail=f"Telegram create_topic curl failed: {result.stderr.strip()}",
            )

        try:
            body = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            logger.warning("Telegram create_topic invalid JSON: %s", e)
            raise HTTPException(
                status_code=502,
                detail="Telegram returned invalid JSON",
            )

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
    except Exception as e:
        logger.exception("Unexpected create_topic failure")
        raise HTTPException(status_code=500, detail=f"Unexpected bot-service error: {e}")


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
