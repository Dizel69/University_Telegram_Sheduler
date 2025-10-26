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


@app.post("/send")
async def send_message(req: SendRequest):
    try:
        # Отправляем и возвращаем message_id
        msg = await bot.send_message(chat_id=req.chat_id, text=req.text, message_thread_id=req.thread_id)
        return {"ok": True, "message_id": msg.message_id}
    except Exception as e:
        # полезно логировать ошибку
        print("Bot send error:", e)
        return {"ok": False, "error": str(e)}
