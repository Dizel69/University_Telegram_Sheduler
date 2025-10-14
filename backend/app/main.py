import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from .database import init_db
from .schemas import EventCreate, EventPublic
from .models import Event
from .crud import add_event, get_public_events, get_due_reminders, mark_reminder_sent, set_sent_message
import httpx
from typing import List

BOT_SERVICE_URL = os.getenv("BOT_SERVICE_URL", "http://bot:8081")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
DEFAULT_CHAT_ID = os.getenv("DEFAULT_CHAT_ID", None)

app = FastAPI(title="M15 Scheduler Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # в prod замени на список фронтендов
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()


@app.post("/events/send", response_model=EventPublic)
async def create_and_send(event_in: EventCreate):
    """
    Сохранить событие и сразу отправить сообщение через bot-service.
    Возвращает объект события (с sent_message_id если удачно).
    """
    # Подготовка модели
    ev = Event(**event_in.dict())
    if not ev.chat_id:
        if DEFAULT_CHAT_ID:
            try:
                ev.chat_id = int(DEFAULT_CHAT_ID)
            except:
                ev.chat_id = None

    # Сохраняем в БД (sent_message_id ещё нет)
    created = add_event(ev)

    # Формируем текст сообщения и добавляем ссылку на запись в календаре
    link = f"{FRONTEND_URL}/calendar/m15/event/{created.id}"
    text = f"{created.body}\n\nСсылка в календаре: {link}"

    # Отправляем на bot-service
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{BOT_SERVICE_URL}/send",
                json={
                    "chat_id": created.chat_id,
                    "thread_id": created.topic_thread_id,
                    "text": text
                },
                timeout=10.0
            )
            resp.raise_for_status()
            data = resp.json()
            message_id = data.get("message_id")
            if message_id:
                set_sent_message(created.id, int(message_id))
        except Exception as e:
            # не падаем — запись создана, но отправка не удалась
            print("Warning: error sending to bot-service:", e)

    return created


@app.get("/events", response_model=List[EventPublic])
def public_events():
    """
    Публичный список событий (для календаря).
    """
    return get_public_events()


@app.get("/events/due_reminders")
def events_due_reminders():
    """
    Эндпоинт для worker: вернуть события, которым надо отправить напоминание.
    Возвращаем минимальный набор полей в JSON.
    """
    due = get_due_reminders()
    result = []
    for ev in due:
        result.append({
            "id": ev.id,
            "title": ev.title,
            "body": ev.body,
            "date": ev.date.isoformat() if ev.date else None,
            "time": ev.time.isoformat() if ev.time else None,
            "chat_id": ev.chat_id,
            "thread_id": ev.topic_thread_id
        })
    return result


@app.post("/events/{event_id}/mark_reminder_sent")
def mark_reminder(event_id: int):
    ok = mark_reminder_sent(event_id)
    if not ok:
        raise HTTPException(status_code=404, detail="event not found")
    return {"ok": True}
