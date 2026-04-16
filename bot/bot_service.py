import logging
import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from telegram import Bot
from telegram.error import TelegramError, TimedOut

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bot-service")

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN хранится в переменных окружения")

bot = Bot(token=BOT_TOKEN)
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
        # Отправляем и возвращаем message_id
        msg = await bot.send_message(
            chat_id=req.chat_id,
            text=req.text,
            message_thread_id=req.thread_id,
            connect_timeout=10,
            read_timeout=40,
            write_timeout=40,
            pool_timeout=10,
        )
        logger.info(
            "Telegram send OK: message_id=%s chat_id=%s",
            msg.message_id,
            msg.chat.id,
        )
        return {"ok": True, "message_id": msg.message_id}
    except TimedOut as e:
        logger.warning("Telegram timeout: %s", e)
        raise HTTPException(status_code=504, detail="Telegram timeout")
    except TelegramError as e:
        logger.warning("Telegram API error: %s", e)
        raise HTTPException(status_code=502, detail=f"Telegram API error: {e}")
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
        res = await bot.create_forum_topic(chat_id=req.chat_id, name=req.name)
        # Telegram возвращает Message с message_thread_id для созданной темы
        thread_id = getattr(res, "message_thread_id", None)
        logger.info("Create topic result message_thread_id: %s", thread_id)
        return {"ok": True, "message_thread_id": thread_id}
    except TelegramError as e:
        logger.warning("Create topic Telegram API error: %s", e)
        raise HTTPException(status_code=502, detail=f"Telegram API error: {e}")
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
