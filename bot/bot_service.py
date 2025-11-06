from fastapi import FastAPI
from pydantic import BaseModel
import os
from telegram import Bot

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is required in environment")

bot = Bot(token=BOT_TOKEN)
app = FastAPI(title="M15 Bot Service")


class SendRequest(BaseModel):
    chat_id: int
    thread_id: int | None = None
    text: str


class CreateTopicRequest(BaseModel):
    chat_id: int
    name: str


@app.post("/send")
async def send_message(req: SendRequest):
    try:
        # Debug: log incoming payload from backend
        try:
            print("DEBUG: bot-service received payload:", req.dict())
        except Exception:
            print("DEBUG: bot-service received payload (unprintable)")
        # Отправляем и возвращаем message_id
        msg = await bot.send_message(chat_id=req.chat_id, text=req.text, message_thread_id=req.thread_id)
        try:
            print("DEBUG: telegram send ok, message_id:", msg.message_id, "chat_id:", msg.chat.id)
        except Exception:
            pass
        return {"ok": True, "message_id": msg.message_id}
    except Exception as e:
        # полезно логировать ошибку
        print("Bot send error:", e)
        return {"ok": False, "error": str(e)}


@app.post("/create_topic")
async def create_topic(req: CreateTopicRequest):
    """
    Create a forum/topic in a supergroup and return its message_thread_id.
    Requires the bot to be an admin with permission to manage topics.
    """
    try:
        print("DEBUG: create_topic request:", req.dict())
        res = await bot.create_forum_topic(chat_id=req.chat_id, name=req.name)
        # Telegram returns a Message object with message_thread_id for the created topic
        thread_id = getattr(res, 'message_thread_id', None)
        print("DEBUG: create_topic result message_thread_id:", thread_id)
        return {"ok": True, "message_thread_id": thread_id}
    except Exception as e:
        print("Create topic error:", e)
        return {"ok": False, "error": str(e)}
