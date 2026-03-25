from fastapi import FastAPI
from pydantic import BaseModel
import os
from telegram import Bot

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
        # Логируем входящий payload от бэкенда
        try:
            print("DEBUG: bot-service получил payload:", req.dict())
        except Exception:
            print("DEBUG: bot-service получил payload (невозможно вывести)")
        # Отправляем и возвращаем message_id
        msg = await bot.send_message(chat_id=req.chat_id, text=req.text, message_thread_id=req.thread_id)
        try:
            print("DEBUG: telegram отправка успешна, message_id:", msg.message_id, "chat_id:", msg.chat.id)
        except Exception:
            pass
        return {"ok": True, "message_id": msg.message_id}
    except Exception as e:
        # Логируем ошибку
        print("Ошибка отправки сообщения:", e)
        return {"ok": False, "error": str(e)}


@app.post("/create_topic")
async def create_topic(req: CreateTopicRequest):
    """
    Создаёт форум/тему в супергруппе и возвращает её message_thread_id.
    Требуется, чтобы бот был админом с правами управления темами.
    """
    try:
        print("DEBUG: запрос на создание темы:", req.dict())
        res = await bot.create_forum_topic(chat_id=req.chat_id, name=req.name)
        # Telegram возвращает Message с message_thread_id для созданной темы
        thread_id = getattr(res, 'message_thread_id', None)
        print("DEBUG: результат создания темы message_thread_id:", thread_id)
        return {"ok": True, "message_thread_id": thread_id}
    except Exception as e:
        print("Ошибка создания темы:", e)
        return {"ok": False, "error": str(e)}
