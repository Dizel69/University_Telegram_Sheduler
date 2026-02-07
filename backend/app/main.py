import os
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Path
from app.database import init_db
from app.schemas import EventCreate, EventPublic
from app.models import Event
from app.crud import add_event, get_public_events, get_due_reminders, mark_reminder_sent, set_sent_message
import httpx
from typing import List, Optional
import calendar as _calendar
from datetime import datetime, date, time
from pydantic import BaseModel

BOT_SERVICE_URL = os.getenv("BOT_SERVICE_URL", "http://bot:8081")
# Host IP or name for services when deployed (example: 185.28.85.183)
HOST = os.getenv("HOST")
# FRONTEND_URL can be provided explicitly; if not, and HOST is set, build URL from HOST:PORT
FRONTEND_URL = os.getenv("FRONTEND_URL") or (f"http://{HOST}:3000" if HOST else "http://127.0.0.1:3000")
DEFAULT_CHAT_ID = os.getenv("DEFAULT_CHAT_ID", None)
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")

# Optional per-type chat overrides (set these in your .env if you want messages routed
# to different chats depending on type)
CHAT_ID_SCHEDULE = os.getenv("CHAT_ID_SCHEDULE")
CHAT_ID_HOMEWORK = os.getenv("CHAT_ID_HOMEWORK")
CHAT_ID_ANNOUNCEMENTS = os.getenv("CHAT_ID_ANNOUNCEMENTS")

# Optional per-type thread/topic overrides (message_thread_id in Telegram)
THREAD_ID_SCHEDULE = os.getenv("THREAD_ID_SCHEDULE")
THREAD_ID_HOMEWORK = os.getenv("THREAD_ID_HOMEWORK")
THREAD_ID_ANNOUNCEMENTS = os.getenv("THREAD_ID_ANNOUNCEMENTS")

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


def _resolve_chat_id(ev_obj):
    """
    Resolve chat_id for an event object: prefer explicit event.chat_id, then per-type env vars, then DEFAULT_CHAT_ID.
    """
    if getattr(ev_obj, "chat_id", None):
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


def _resolve_thread_id(ev_obj):
    """
    Resolve topic/thread id (message_thread_id) for an event: prefer explicit event.topic_thread_id,
    then per-type THREAD_ID_* env vars, else None.
    """
    if getattr(ev_obj, "topic_thread_id", None):
        return ev_obj.topic_thread_id
    try:
        if ev_obj.type == 'schedule' and THREAD_ID_SCHEDULE:
            return int(THREAD_ID_SCHEDULE)
        if ev_obj.type == 'homework' and THREAD_ID_HOMEWORK:
            return int(THREAD_ID_HOMEWORK)
        if ev_obj.type == 'announcement' and THREAD_ID_ANNOUNCEMENTS:
            return int(THREAD_ID_ANNOUNCEMENTS)
    except Exception:
        pass
    return None


def _canonical_type(t: str) -> str:
    """Return a canonical English token for known types regardless of incoming language/variants."""
    if not t:
        return t
    n = str(t).lower().strip()
    if 'перенос' in n or 'transfer' in n:
        return 'transfer'
    if 'домаш' in n or 'homework' in n:
        return 'homework'
    if 'распис' in n or 'schedule' in n:
        return 'schedule'
    if 'объяв' in n or 'announcement' in n:
        return 'announcement'
    return n


def require_admin(x_admin_token: str | None = Header(None)):
    """
    Require a valid X-ADMIN-TOKEN header that matches ADMIN_TOKEN from env.
    If ADMIN_TOKEN is not configured, admin actions are disabled.
    """
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Admin actions are disabled on this instance")
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid admin token")
    return True


@app.get('/admin/validate')
def admin_validate(admin_ok: bool = Depends(require_admin)):
    """Lightweight endpoint to validate admin token from the frontend during login."""
    return {"ok": True}


@app.post("/events/send", response_model=EventPublic)
async def create_and_send(event_in: EventCreate, admin_ok: bool = Depends(require_admin)):
    """
    Сохранить событие и сразу отправить сообщение через bot-service.
    Возвращает объект события (с sent_message_id если удачно).
    """
    # NOTE: Authorization temporarily disabled for local development
    # If you want to re-enable, restore the ADMIN_TOKEN check here.

    # Подготовка модели
    ev = Event(**event_in.dict())
    # Defensive normalization before saving: if body/title mention 'перенос', force type
    try:
        text_lower_pre = ((ev.body or '') + ' ' + (ev.title or '')).lower()
        if 'перенос' in text_lower_pre or 'перенес' in text_lower_pre:
            ev.type = 'transfer'
        else:
            try:
                ev.type = _canonical_type(ev.type)
            except Exception:
                pass
    except Exception:
        pass
    if not ev.chat_id:
        if DEFAULT_CHAT_ID:
            try:
                ev.chat_id = int(DEFAULT_CHAT_ID)
            except:
                ev.chat_id = None

    # Сохраняем в БД (sent_message_id ещё нет)
    created = add_event(ev)

    # Для schedule событий не отправлять уведомления — пометить как отправленные
    if created.type == 'schedule':
        mark_reminder_sent(created.id)
        # normalize returned type for frontend consistency
        try:
            created.type = _canonical_type(created.type)
        except Exception:
            pass
        return created

    # Формируем текст сообщения и добавляем ссылку на запись в календаре
    link = f"{FRONTEND_URL}/calendar/m15/event/{created.id}"
    # Собираем текст в формате: #Тип \n #Предмет \nТело\n\nСсылка...
    parts = []
    parts.append(TYPE_HASHTAG.get(created.type, ''))
    if created.subject:
        subj_tag = '#' + created.subject.replace(' ', '_')
        parts.append(subj_tag)
    parts.append(created.body or '')
    if getattr(created, 'room', None):
        parts.append(f"Аудитория: {created.room}")
    if getattr(created, 'teacher', None):
        parts.append(f"Преподаватель: {created.teacher}")
    parts.append('')
    parts.append(f"Ссылка в календаре: {link}")
    text = '\n'.join([p for p in parts if p is not None and p != ''])

    # Resolve chat and thread ids for sending
    target_chat = _resolve_chat_id(created)
    target_thread = _resolve_thread_id(created)

    # Отправляем на bot-service — debug: логируем outgoing payload и ответ
    payload = {
        "chat_id": target_chat,
        "thread_id": target_thread,
        "text": text
    }
    print("DEBUG: outgoing to bot-service:", payload)
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(f"{BOT_SERVICE_URL}/send", json=payload, timeout=10.0)
            # Log response for debugging
            try:
                resp_text = resp.text
            except Exception:
                resp_text = '<unable to read response body>'
            print("DEBUG: bot-service response:", resp.status_code, resp_text)

            try:
                data = resp.json()
            except Exception:
                data = {}
            print('DEBUG: parsed bot response data:', data)

            # If we didn't get a message_id back, and we attempted to send to a thread, retry without thread_id
            message_id = data.get('message_id')
            if not message_id and target_thread is not None:
                print('DEBUG: no message_id received; retrying without thread_id')
                payload2 = {"chat_id": target_chat, "text": text}
                try:
                    resp2 = await client.post(f"{BOT_SERVICE_URL}/send", json=payload2, timeout=10.0)
                    try:
                        resp2_text = resp2.text
                    except Exception:
                        resp2_text = '<unable to read response body>'
                    print('DEBUG: bot-service response (retry):', resp2.status_code, resp2_text)
                    try:
                        data2 = resp2.json()
                    except Exception:
                        data2 = {}
                    message_id = data2.get('message_id')
                    if message_id:
                        set_sent_message(created.id, int(message_id))
                except Exception as e:
                    print('Warning: retry without thread_id failed:', e)
            else:
                if message_id:
                    set_sent_message(created.id, int(message_id))
        except Exception as e:
            # не падаем — запись создана, но отправка не удалась
            print("Warning: error sending to bot-service:", e)

    # normalize returned type for frontend consistency
    try:
        created.type = _canonical_type(created.type)
    except Exception:
        pass
    return created


@app.get("/events", response_model=List[EventPublic])
def public_events():
    """
    Публичный список событий (для календаря).
    """
    rows = get_public_events()
    # normalize types to canonical tokens for frontend consistency
    out = []
    for ev in rows:
        out.append({
            'id': ev.id,
            'type': _canonical_type(ev.type),
            'subject': ev.subject,
            'title': ev.title,
            'body': ev.body,
            'date': ev.date,
            'time': ev.time,
            'end_time': getattr(ev, 'end_time', None),
            'room': getattr(ev, 'room', None),
            'teacher': getattr(ev, 'teacher', None),
            'series_id': getattr(ev, 'series_id', None),
            'chat_id': ev.chat_id,
            'topic_thread_id': ev.topic_thread_id,
            'sent_message_id': getattr(ev, 'sent_message_id', None),
            'source': ev.source
        })
    return out


@app.delete('/events/day')
def delete_events_day(date: str, admin_ok: bool = Depends(require_admin)):
    """
    Удалить все события на указанную дату (YYYY-MM-DD).
    """
    from .crud import delete_events_by_date
    try:
        d = datetime.strptime(date, '%Y-%m-%d').date()
    except Exception:
        raise HTTPException(status_code=400, detail='invalid date format')
    cnt = delete_events_by_date(d)
    return {'deleted': cnt}


@app.delete('/events/month')
def delete_events_month(year: int, month: int, admin_ok: bool = Depends(require_admin)):
    """
    Удалить все события в указанном месяце (year, month) — month: 1-12
    """
    from .crud import delete_events_in_range
    try:
        y = int(year)
        m = int(month)
        if m < 1 or m > 12:
            raise ValueError()
    except Exception:
        raise HTTPException(status_code=400, detail='invalid year/month')
    first = date(y, m, 1)
    last_day = _calendar.monthrange(y, m)[1]
    last = date(y, m, last_day)
    cnt = delete_events_in_range(first, last)
    return {'deleted': cnt}


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

    # return both resolved chat_id and thread_id for UI convenience
    return {"chat_id": _resolve_chat_id(ev), "thread_id": _resolve_thread_id(ev), "type": _canonical_type(ev.type)}


@app.delete("/events/{event_id}")
def delete_event_endpoint(event_id: int, admin_ok: bool = Depends(require_admin)):
    from .crud import delete_event
    # Authorization disabled for local development
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
            "room": getattr(ev, 'room', None),
            "teacher": getattr(ev, 'teacher', None),
            # return resolved chat/thread so worker can post into correct topic
            "chat_id": _resolve_chat_id(ev),
            "thread_id": _resolve_thread_id(ev)
        })
    return result


@app.get('/calendar')
def calendar_view(start: str | None = None, end: str | None = None):
    """
    Return public events optionally filtered by ISO date range (YYYY-MM-DD).
    Used by public calendar UI.
    """
    from .crud import get_public_events
    all_ev = get_public_events(limit=1000)
    def in_range(ev):
        if start and ev.date and ev.date.isoformat() < start:
            return False
        if end and ev.date and ev.date.isoformat() > end:
            return False
        return True

    filtered = [
        {
            'id': ev.id,
            'type': _canonical_type(ev.type),
            'subject': ev.subject,
            'title': ev.title,
            'body': ev.body,
            'date': ev.date.isoformat() if ev.date else None,
            'time': ev.time.isoformat() if ev.time else None,
            'end_time': ev.end_time.isoformat() if getattr(ev, 'end_time', None) else None,
            'room': getattr(ev, 'room', None),
            'teacher': getattr(ev, 'teacher', None),
            'series_id': getattr(ev, 'series_id', None),
            'chat_id': ev.chat_id,
            'thread_id': ev.topic_thread_id
        }
        for ev in all_ev if in_range(ev)
    ]
    return filtered


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
def import_events(items: List[ParsedItem], admin_ok: bool = Depends(require_admin)):
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


@app.post("/events")
def create_event(event_in: EventCreate, admin_ok: bool = Depends(require_admin)):
    """
    Create an event in the database without sending it via bot.
    Used by the admin UI to add events manually.
    For schedule type events, automatically mark reminder_sent=True (no notifications).
    """
    # Authorization temporarily disabled for local development
    from .models import Event
    from .crud import add_event

    ev = Event(**event_in.dict())
    # mark events created via UI/manual calendar so they are excluded from reminders and Events list
    ev.source = 'manual'
    ev.reminder_sent = True
    # For schedule events, do not send reminders
    if ev.type == 'schedule':
        ev.reminder_sent = True
    # Defensive normalization BEFORE saving: look at body/title and adjust type
    try:
        text_lower_pre = ((ev.body or '') + ' ' + (ev.title or '')).lower()
        if 'перенос' in text_lower_pre or 'перенес' in text_lower_pre:
            ev.type = 'transfer'
        else:
            try:
                ev.type = _canonical_type(ev.type)
            except Exception:
                pass
    except Exception:
        pass

    created = add_event(ev)
    try:
        created.type = _canonical_type(created.type)
    except Exception:
        pass
    return created


class EventUpdate(BaseModel):
    date: Optional[str] = None
    time: Optional[str] = None
    end_time: Optional[str] = None
    title: Optional[str] = None
    body: Optional[str] = None
    type: Optional[str] = None
    room: Optional[str] = None
    teacher: Optional[str] = None


@app.put('/events/{event_id}')
def update_event_endpoint(event_id: int, update: EventUpdate, admin_ok: bool = Depends(require_admin), apply_to_series: bool = False):
    """Update event fields (used for transferring/moving events).
    If apply_to_series=True and the event belongs to a series, apply changes to all events in that series."""
    from .crud import update_event, get_event_by_id, update_events_by_series
    ev = get_event_by_id(event_id)
    if not ev:
        raise HTTPException(status_code=404, detail='event not found')
    fields = {k:v for k,v in update.dict().items() if v is not None}
    if apply_to_series and getattr(ev, 'series_id', None):
        cnt = update_events_by_series(ev.series_id, **fields)
        if cnt == 0:
            raise HTTPException(status_code=404, detail='no events in series found')
        return {'ok': True, 'updated': cnt}
    else:
        ok = update_event(event_id, **fields)
        if not ok:
            raise HTTPException(status_code=500, detail='failed to update')
        return {'ok': True}

@app.post("/events/{event_id}/send_now")
async def send_now(event_id: int = Path(..., description="ID события"), admin_ok: bool = Depends(require_admin)):
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
    if getattr(ev, 'room', None):
        parts.append(f"Аудитория: {ev.room}")
    if getattr(ev, 'teacher', None):
        parts.append(f"Преподаватель: {ev.teacher}")
    parts.append('')
    parts.append(f"Ссылка в календаре: {link}")
    text = '\n'.join([p for p in parts if p is not None and p != ''])

    # auth for send_now
    # Authorization disabled for local development

    # determine chat_id and thread (prefer event explicit fields, then per-type env, then DEFAULT_CHAT_ID)
    chat_id = _resolve_chat_id(ev)
    thread_id = _resolve_thread_id(ev)
    if not chat_id:
        raise HTTPException(status_code=400, detail="No chat_id set for this event and DEFAULT_CHAT_ID not configured")

    # Отправляем в bot-service
    # Отправляем в bot-service — debug outgoing payload and response
    payload = {"chat_id": chat_id, "thread_id": thread_id, "text": text}
    print("DEBUG: send_now outgoing to bot-service:", payload)
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(f"{BOT_SERVICE_URL}/send", json=payload, timeout=15.0)
            try:
                resp_text = resp.text
            except Exception:
                resp_text = '<unable to read response body>'
            print("DEBUG: send_now bot-service response:", resp.status_code, resp_text)

            try:
                data = resp.json()
            except Exception:
                data = {}
            print('DEBUG: parsed bot response data (send_now):', data)

            message_id = data.get('message_id')
            if not message_id and thread_id is not None:
                print('DEBUG: send_now no message_id received; retrying without thread_id')
                payload2 = {"chat_id": chat_id, "text": text}
                try:
                    resp2 = await client.post(f"{BOT_SERVICE_URL}/send", json=payload2, timeout=15.0)
                    try:
                        resp2_text = resp2.text
                    except Exception:
                        resp2_text = '<unable to read response body>'
                    print('DEBUG: send_now bot-service response (retry):', resp2.status_code, resp2_text)
                    try:
                        data2 = resp2.json()
                    except Exception:
                        data2 = {}
                    message_id = data2.get('message_id')
                    if message_id:
                        set_sent_message(ev.id, int(message_id))
                        return {"ok": True, "message_id": message_id}
                    else:
                        return {"ok": False, "error": data2}
                except Exception as e:
                    raise HTTPException(status_code=500, detail=str(e))
            else:
                if message_id:
                    set_sent_message(ev.id, int(message_id))
                    return {"ok": True, "message_id": message_id}
                else:
                    return {"ok": False, "error": data}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
