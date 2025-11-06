import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Path
from app.database import init_db
from app.schemas import EventCreate, EventPublic
from app.models import Event
from app.crud import add_event, get_public_events, get_due_reminders, mark_reminder_sent, set_sent_message
import httpx
from typing import List
from typing import List
from datetime import datetime
from pydantic import BaseModel

BOT_SERVICE_URL = os.getenv("BOT_SERVICE_URL", "http://bot:8081")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
DEFAULT_CHAT_ID = os.getenv("DEFAULT_CHAT_ID", None)

# Optional per-type chat overrides (set these in your .env if you want messages routed
# to different chats depending on type)
CHAT_ID_SCHEDULE = os.getenv("CHAT_ID_SCHEDULE")
CHAT_ID_HOMEWORK = os.getenv("CHAT_ID_HOMEWORK")
CHAT_ID_ANNOUNCEMENTS = os.getenv("CHAT_ID_ANNOUNCEMENTS")

TYPE_HASHTAG = {
    'schedule': '#Расписание',
    'homework': '#Домашнее_задание',
    'announcement': '#Объявление'
}

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
    # Собираем текст в формате: #Тип \n #Предмет \nТело\n\nСсылка...
    parts = []
    parts.append(TYPE_HASHTAG.get(created.type, ''))
    if created.subject:
        subj_tag = '#' + created.subject.replace(' ', '_')
        parts.append(subj_tag)
    parts.append(created.body or '')
    parts.append('')
    parts.append(f"Ссылка в календаре: {link}")
    text = '\n'.join([p for p in parts if p is not None and p != ''])

    # Решаем, в какой чат отправлять по типу, если не указан chat_id у события
    def _resolve_chat_id(ev_obj):
        if ev_obj.chat_id:
            return ev_obj.chat_id
        # per-type overrides from env
        try:
            if ev_obj.type == 'schedule' and CHAT_ID_SCHEDULE:
                return int(CHAT_ID_SCHEDULE)
            if ev_obj.type == 'homework' and CHAT_ID_HOMEWORK:
                return int(CHAT_ID_HOMEWORK)
            if ev_obj.type == 'announcement' and CHAT_ID_ANNOUNCEMENTS:
                return int(CHAT_ID_ANNOUNCEMENTS)
        except Exception:
            pass
        if DEFAULT_CHAT_ID:
            try:
                return int(DEFAULT_CHAT_ID)
            except Exception:
                return None
        return None

    target_chat = _resolve_chat_id(created)

    # Отправляем на bot-service
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{BOT_SERVICE_URL}/send",
                json={
                    "chat_id": target_chat,
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


@app.get("/events/{event_id}/resolve_chat")
def resolve_chat(event_id: int):
    """
    Вспомогательный эндпоинт: вернуть разрешённый chat_id, который будет использован для отправки
    (учитывает chat_id в событии, затем per-type env override, затем DEFAULT_CHAT_ID).
    """
    from .crud import get_event_by_id
    ev = get_event_by_id(event_id)
    if not ev:
        raise HTTPException(status_code=404, detail="event not found")

    def _resolve(ev_obj):
        if ev_obj.chat_id:
            return ev_obj.chat_id
        try:
            if ev_obj.type == 'schedule' and CHAT_ID_SCHEDULE:
                return int(CHAT_ID_SCHEDULE)
            if ev_obj.type == 'homework' and CHAT_ID_HOMEWORK:
                return int(CHAT_ID_HOMEWORK)
            if ev_obj.type == 'announcement' and CHAT_ID_ANNOUNCEMENTS:
                return int(CHAT_ID_ANNOUNCEMENTS)
        except Exception:
            pass
        if DEFAULT_CHAT_ID:
            try:
                return int(DEFAULT_CHAT_ID)
            except Exception:
                return None
        return None

    return {"chat_id": _resolve(ev), "type": ev.type}


@app.delete("/events/{event_id}")
def delete_event_endpoint(event_id: int):
    from .crud import delete_event
    ok = delete_event(event_id)
    if not ok:
        raise HTTPException(status_code=404, detail="event not found")
    return {"ok": True}


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

# Вспомогательная схема для импорта (локальная, можно держать прямо здесь)
class ParsedItem(BaseModel):
    page: int | None = None
    raw: str
    type: str | None = None
    start: str | None = None   # "HH:MM"
    end: str | None = None
    date: str | None = None    # "DD.MM.YYYY" или "DD-MM-YYYY"
    images: list | None = None

@app.post("/events/import")
def import_events(items: List[ParsedItem]):
    """
    Импортировать распарсенные элементы (из parser) в базу.
    По умолчанию сохраняет source='dekanat' и НЕ отправляет сообщения ботом.
    Возвращает список созданных id.
    """
    created_ids = []
    from .crud import add_event  # локальный импорт чтобы избежать циклов

    for it in items:
        # Преобразуем строковую дату в ISO date (попытка поддержать DD.MM.YYYY)
        ev_date = None
        try:
            if it.date:
                # пробуем несколько форматов
                for fmt in ("%d.%m.%Y", "%d-%m-%Y", "%d.%m.%y", "%d-%m-%y"):
                    try:
                        ev_date = datetime.strptime(it.date, fmt).date()
                        break
                    except Exception:
                        continue
        except Exception:
            ev_date = None

        body_text = it.raw
        title = None
        # Попробуем выделить краткий заголовок — первые 60 символов или до точки
        if it.raw:
            title = it.raw.split('\n')[0][:60]

        # Собираем Event (sqlmodel) объект
        from .models import Event
        ev = Event(
            type = it.type or "schedule",
            subject = None,
            title = title,
            body = body_text,
            date = ev_date,
            time = None,
            chat_id = None,  # не указываем — будут использовать default или ручное назначение в админке
            topic_thread_id = None,
            reminder_offset_hours = 24,
            reminder_sent = False,
            source = "dekanat"
        )
        created = add_event(ev)
        created_ids.append(created.id)

    return {"created": created_ids, "count": len(created_ids)}

@app.post("/events/{event_id}/send_now")
async def send_now(event_id: int = Path(..., description="ID события")):
    """
    Отправляет существующее событие (из БД) ботом и сохраняет sent_message_id.
    """
    from .crud import get_event_by_id, set_sent_message
    ev = get_event_by_id(event_id)
    if not ev:
        raise HTTPException(status_code=404, detail="event not found")

    # Формируем текст (как при создании)
    link = f"{FRONTEND_URL}/calendar/m15/event/{ev.id}"
    parts = []
    parts.append(TYPE_HASHTAG.get(ev.type, ''))
    if ev.subject:
        parts.append('#' + ev.subject.replace(' ', '_'))
    parts.append(ev.body or '')
    parts.append('')
    parts.append(f"Ссылка в календаре: {link}")
    text = '\n'.join([p for p in parts if p is not None and p != ''])

    # определяем chat_id (сначала у события, иначе per-type override, иначе DEFAULT_CHAT_ID)
    def _resolve_chat_id_for(ev_obj):
        if ev_obj.chat_id:
            return ev_obj.chat_id
        try:
            if ev_obj.type == 'schedule' and CHAT_ID_SCHEDULE:
                return int(CHAT_ID_SCHEDULE)
            if ev_obj.type == 'homework' and CHAT_ID_HOMEWORK:
                return int(CHAT_ID_HOMEWORK)
            if ev_obj.type == 'announcement' and CHAT_ID_ANNOUNCEMENTS:
                return int(CHAT_ID_ANNOUNCEMENTS)
        except Exception:
            pass
        if DEFAULT_CHAT_ID:
            try:
                return int(DEFAULT_CHAT_ID)
            except Exception:
                return None
        return None

    chat_id = _resolve_chat_id_for(ev)
    if not chat_id:
        raise HTTPException(status_code=400, detail="No chat_id set for this event and DEFAULT_CHAT_ID not configured")

    # Отправляем в bot-service
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{BOT_SERVICE_URL}/send",
                json={
                    "chat_id": chat_id,
                    "thread_id": ev.topic_thread_id,
                    "text": text
                },
                timeout=15.0
            )
            resp.raise_for_status()
            data = resp.json()
            message_id = data.get("message_id")
            if message_id:
                set_sent_message(ev.id, int(message_id))
                return {"ok": True, "message_id": message_id}
            else:
                return {"ok": False, "error": data}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
