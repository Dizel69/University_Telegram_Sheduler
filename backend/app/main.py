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
# IP или имя хоста для сервисов при развёртывании (пример: 185.28.85.183)
HOST = os.getenv("HOST")
# FRONTEND_URL может быть задан явно; если нет и HOST установлен, собираем URL из HOST:PORT
FRONTEND_URL = os.getenv("FRONTEND_URL") or (f"http://{HOST}:3000" if HOST else "http://127.0.0.1:3000")
DEFAULT_CHAT_ID = os.getenv("DEFAULT_CHAT_ID", None)
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")

# Опциональные переопределения чатов по типам событий
# (установи в .env если хочешь маршрутизировать сообщения в разные чаты)
CHAT_ID_SCHEDULE = os.getenv("CHAT_ID_SCHEDULE")
CHAT_ID_HOMEWORK = os.getenv("CHAT_ID_HOMEWORK")
CHAT_ID_ANNOUNCEMENTS = os.getenv("CHAT_ID_ANNOUNCEMENTS")

# Опциональные переопределения потоков/тем по типам (message_thread_id в Telegram)
THREAD_ID_SCHEDULE = os.getenv("THREAD_ID_SCHEDULE")
THREAD_ID_HOMEWORK = os.getenv("THREAD_ID_HOMEWORK")
THREAD_ID_ANNOUNCEMENTS = os.getenv("THREAD_ID_ANNOUNCEMENTS")

TYPE_HASHTAG = {
    'schedule': '#Расписание',
    'homework': '#Домашнее_задание',
    'announcement': '#Объявление',
}

app = FastAPI(title="Планировщик университета - Бэкенд")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В production замени на список разрешённых фронтендов
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()


def _resolve_chat_id(ev_obj):
    """
    Определяет chat_id для события: предпочитаем явный event.chat_id,
    затем переменные среди по типам, затем DEFAULT_CHAT_ID.
    """
    if getattr(ev_obj, "chat_id", None):
        return ev_obj.chat_id
    try:
        if ev_obj.type in ('schedule', 'exam_control') and CHAT_ID_SCHEDULE:
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
    Определяет тему/поток (message_thread_id) для события:
    предпочитаем явный event.topic_thread_id, затем переменные среды по типам, иначе None.
    """
    if getattr(ev_obj, "topic_thread_id", None):
        return ev_obj.topic_thread_id
    try:
        if ev_obj.type in ('schedule', 'exam_control') and THREAD_ID_SCHEDULE:
            return int(THREAD_ID_SCHEDULE)
        if ev_obj.type == 'homework' and THREAD_ID_HOMEWORK:
            return int(THREAD_ID_HOMEWORK)
        if ev_obj.type == 'announcement' and THREAD_ID_ANNOUNCEMENTS:
            return int(THREAD_ID_ANNOUNCEMENTS)
    except Exception:
        pass
    return None


def _canonical_type(t: str) -> str:
    """
    Возвращает каноничный английский токен для известных типов.
    """
    if not t:
        return t
    n = str(t).lower().strip()
    if 'перенос' in n or 'transfer' in n:
        return 'transfer'
    if 'домаш' in n or 'homework' in n:
        return 'homework'
    if (
        'exam_control' in n
        or 'контрольн' in n
        or 'экзамен' in n
    ):
        return 'exam_control'
    if 'распис' in n or 'schedule' in n:
        return 'schedule'
    if 'объяв' in n or 'announcement' in n:
        return 'announcement'
    return n


def _build_telegram_message_text(ev) -> str:
    """
    Текст поста в Telegram. Для exam_control — формат с хэштегами по выбору вида;
    для остальных типов — прежняя схема + ссылка.
    """
    link = f"{FRONTEND_URL}/calendar/m15/event/{getattr(ev, 'id', 0)}"
    canon = _canonical_type(getattr(ev, "type", "") or "")

    if canon == "exam_control":
        lines = []
        lt = getattr(ev, "lesson_type", None)
        lines.append("#Экзамен" if lt == "exam" else "#Контрольная_работа")
        subj = getattr(ev, "subject", None)
        if subj and str(subj).strip():
            lines.append("#" + str(subj).strip().replace(" ", "_"))
        room = getattr(ev, "room", None)
        if room and str(room).strip():
            lines.append("Аудитория")
            lines.append(str(room).strip())
        teacher = getattr(ev, "teacher", None)
        if teacher and str(teacher).strip():
            lines.append("преподаватель")
            lines.append(str(teacher).strip())
        body = (getattr(ev, "body", None) or "").strip()
        if body:
            lines.append(body)
        lines.append("")
        lines.append(f"Ссылка в календаре: {link}")
        return "\n".join(lines)

    parts = []
    parts.append(TYPE_HASHTAG.get(canon, ""))
    if getattr(ev, "subject", None):
        parts.append("#" + str(ev.subject).replace(" ", "_"))
    parts.append(getattr(ev, "body", None) or "")
    if getattr(ev, "room", None):
        parts.append(f"Аудитория: {ev.room}")
    if getattr(ev, "teacher", None):
        parts.append(f"Преподаватель: {ev.teacher}")
    parts.append("")
    parts.append(f"Ссылка в календаре: {link}")
    return "\n".join([p for p in parts if p is not None and p != ""])


def require_admin(x_admin_token: str | None = Header(None)):
    """
    Требует валидный X-ADMIN-TOKEN в заголовке, соответствующий ADMIN_TOKEN из переменных среды.
    Если ADMIN_TOKEN не настроен, админ-функции отключены.
    """
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Администраторские действия выключены для этого экземпляра")
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Неверный токен администратора")
    return True


@app.get('/admin/validate')
def admin_validate(admin_ok: bool = Depends(require_admin)):
    """Лёгкий эндпоинт для проверки админ-токена при входе с фронтенда."""
    return {"ok": True}


@app.post("/events/send", response_model=EventPublic)
async def create_and_send(event_in: EventCreate, admin_ok: bool = Depends(require_admin)):
    """
    Сохраняет событие и сразу отправляет его сообщение через bot-service.
    Возвращает объект события (с sent_message_id если успешно).
    """
    # NOTE: Authorization temporarily disabled for local development
    # Не включаем ADMIN_TOKEN проверку тут

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

    # Подготовка события в базе данных (sent_message_id ещё не установлен)
    created = add_event(ev)

    # Для schedule событий не отправлять уведомления — пометить как отправленные
    if created.type == 'schedule':
        mark_reminder_sent(created.id)
        # Нормализуем возвращаемый тип для согласованности фронтенда
        try:
            created.type = _canonical_type(created.type)
        except Exception:
            pass
        return created

    text = _build_telegram_message_text(created)

    # Resolve chat and thread ids for sending
    target_chat = _resolve_chat_id(created)
    target_thread = _resolve_thread_id(created)

    # Отправляем на bot-service — логируем исходящий payload и ответ
    payload = {
        "chat_id": target_chat,
        "thread_id": target_thread,
        "text": text
    }
    print("DEBUG: исходящий запрос к bot-service:", payload)
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(f"{BOT_SERVICE_URL}/send", json=payload, timeout=10.0)
            # Логирование ответа для дотрансляции
            try:
                resp_text = resp.text
            except Exception:
                resp_text = '<unable to read response body>'
            print("DEBUG: ответ bot-service:", resp.status_code, resp_text)

            try:
                data = resp.json()
            except Exception:
                data = {}
            print('DEBUG: разобранные данные ответа:', data)

            # Если не получили message_id и пытались отправить в потоке, повторяем без thread_id
            message_id = data.get('message_id')
            if not message_id and target_thread is not None:
                print('DEBUG: не получен message_id; повтор без thread_id')
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
                    print('Предупреждение: повтор без thread_id не удался:', e)
            else:
                if message_id:
                    set_sent_message(created.id, int(message_id))
        except Exception as e:
            # Не падаем — запись создана, но отправка не удалась
            print("Предупреждение: ошибка при отправке на bot-service:", e)

    # Нормализуем возвращаемый тип для согласованности фронтенда
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
    # Нормализуем типы в каноничные токены для непрерывности фронтенда
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
            'lesson_type': getattr(ev, 'lesson_type', None),
            'chat_id': ev.chat_id,
            'topic_thread_id': ev.topic_thread_id,
            'sent_message_id': getattr(ev, 'sent_message_id', None),
            'source': ev.source,
            'reminder_offset_hours': getattr(ev, 'reminder_offset_hours', 24),
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
        raise HTTPException(status_code=400, detail='неверный формат даты')
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
        raise HTTPException(status_code=400, detail='неверные год/месяц')
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
        raise HTTPException(status_code=404, detail="событие не найдено")

    # Возвращаем как разрешённый chat_id так и thread_id для удобства UI
    return {"chat_id": _resolve_chat_id(ev), "thread_id": _resolve_thread_id(ev), "type": _canonical_type(ev.type)}


@app.delete("/events/{event_id}")
def delete_event_endpoint(event_id: int, admin_ok: bool = Depends(require_admin)):
    from .crud import delete_event
    # Авторизация отключена для локальной разработки
    ok = delete_event(event_id)
    if not ok:
        raise HTTPException(status_code=404, detail="событие не найдено")
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
            "type": _canonical_type(ev.type),
            "title": ev.title,
            "subject": getattr(ev, "subject", None),
            "body": ev.body,
            "date": ev.date.isoformat() if ev.date else None,
            "time": ev.time.isoformat() if ev.time else None,
            "room": getattr(ev, 'room', None),
            "teacher": getattr(ev, 'teacher', None),
            "lesson_type": getattr(ev, "lesson_type", None),
            # return resolved chat/thread so worker can post into correct topic
            "chat_id": _resolve_chat_id(ev),
            "thread_id": _resolve_thread_id(ev)
        })
    return result


@app.get('/calendar')
def calendar_view(start: str | None = None, end: str | None = None, type: str | None = None):
    """
    Возвращает публичные события, опционально отфильтрованные по диапазону дат (YYYY-MM-DD) и/или
    каноническому `type` (например `homework`). Используется UI публичного календаря.
    """
    from .crud import get_public_events
    all_ev = get_public_events(limit=1000)
    def in_range(ev):
        if start and ev.date and ev.date.isoformat() < start:
            return False
        if end and ev.date and ev.date.isoformat() > end:
            return False
        return True

    filtered = []
    for ev in all_ev:
        if not in_range(ev):
            continue
        can = _canonical_type(ev.type)
        if type and can != type:
            continue
        filtered.append({
            'id': ev.id,
            'type': can,
            'subject': ev.subject,
            'title': ev.title,
            'body': ev.body,
            'date': ev.date.isoformat() if ev.date else None,
            'time': ev.time.isoformat() if ev.time else None,
            'end_time': ev.end_time.isoformat() if getattr(ev, 'end_time', None) else None,
            'room': getattr(ev, 'room', None),
            'teacher': getattr(ev, 'teacher', None),
            'series_id': getattr(ev, 'series_id', None),
            'lesson_type': getattr(ev, 'lesson_type', None),
            'chat_id': ev.chat_id,
            'thread_id': ev.topic_thread_id,
            'reminder_offset_hours': getattr(ev, 'reminder_offset_hours', 24),
        })
    return filtered


@app.post("/events/{event_id}/mark_reminder_sent")
def mark_reminder(event_id: int):
    ok = mark_reminder_sent(event_id)
    if not ok:
        raise HTTPException(status_code=404, detail="событие не найдено")
    return {"ok": True}

# На настоящий момент PDF импорт неподдерживается


@app.post("/events")
def create_event(event_in: EventCreate, admin_ok: bool = Depends(require_admin)):
    """
    Новое событие в базе данных без отправки через бот.
    Ручные записи: source=manual (скрыты во вкладке «События»).
    Расписание — без напоминаний; домашка и контрольные/экзамены — с напоминаниями по reminder_offset_hours.
    """
    # Авторизация временно отключена для локальной разработки
    from .models import Event
    from .crud import add_event

    ev = Event(**event_in.dict())
    # Помечаем события, созданные через нтерфейс/ручной календарь
    # (чтобы они были исключены из уведомлений и списка событий)
    ev.source = 'manual'
    # Расписание — без напоминаний; ДЗ и контрольные/экзамены — worker может напомнить
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

    if ev.type == 'schedule':
        ev.reminder_sent = True
    elif ev.type in ('homework', 'exam_control'):
        ev.reminder_sent = False

    created = add_event(ev)
    try:
        created.type = _canonical_type(created.type)
    except Exception:
        pass
    return created


class EventUpdate(BaseModel):
    """Модель обновления события."""
    date: Optional[str] = None      # Новая дата
    time: Optional[str] = None      # Новое время начала
    end_time: Optional[str] = None  # Новое время окончания
    title: Optional[str] = None     # Новый заголовок
    body: Optional[str] = None      # Новые детали
    type: Optional[str] = None      # Новый тип
    subject: Optional[str] = None   # Предмет
    room: Optional[str] = None      # Новая аудитория
    teacher: Optional[str] = None   # Новый преподаватель
    lesson_type: Optional[str] = None  # exam / control для exam_control; lecture / practice для schedule
    reminder_offset_hours: Optional[int] = None


@app.put('/events/{event_id}')
def update_event_endpoint(event_id: int, update: EventUpdate, admin_ok: bool = Depends(require_admin), apply_to_series: bool = False):
    """
    Обновляем поля события (используется рля переноса/перемещения событий).
    Если apply_to_series=True и событие часть серии, применяем изменения к всем событиям в серии.
    """
    from .crud import update_event, get_event_by_id, update_events_by_series
    ev = get_event_by_id(event_id)
    if not ev:
        raise HTTPException(status_code=404, detail='событие не найдено')
    fields = {k:v for k,v in update.dict().items() if v is not None}
    if apply_to_series and getattr(ev, 'series_id', None):
        cnt = update_events_by_series(ev.series_id, **fields)
        if cnt == 0:
            raise HTTPException(status_code=404, detail='событий в серии не найдено')
        return {'ok': True, 'updated': cnt}
    else:
        ok = update_event(event_id, **fields)
        if not ok:
            raise HTTPException(status_code=500, detail='не удалось обновить')
        return {'ok': True}

@app.post("/events/{event_id}/send_now")
async def send_now(event_id: int = Path(..., description="ID события"), admin_ok: bool = Depends(require_admin)):
    """
    Отправляет существующее событие (из БД) ботом и сохраняет sent_message_id.
    """
    from .crud import get_event_by_id, set_sent_message
    ev = get_event_by_id(event_id)
    if not ev:
        raise HTTPException(status_code=404, detail="событие не найдено")

    text = _build_telegram_message_text(ev)

    # auth for send_now
    # Authorization disabled for local development

    # Определяем chat_id и thread (предпочитаем явные поля события, затем переменные по типам, затем DEFAULT_CHAT_ID)
    chat_id = _resolve_chat_id(ev)
    thread_id = _resolve_thread_id(ev)
    if not chat_id:
        raise HTTPException(status_code=400, detail="Не установлен chat_id для этого события и не настроен DEFAULT_CHAT_ID")

    # Отправляем в bot-service
    # Отправляем в bot-service — debug outgoing payload and response
    payload = {"chat_id": chat_id, "thread_id": thread_id, "text": text}
    print("DEBUG: send_now исходящий к bot-service:", payload)
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(f"{BOT_SERVICE_URL}/send", json=payload, timeout=15.0)
            try:
                resp_text = resp.text
            except Exception:
                resp_text = '<невозможно прочитать тело ответа>'
            print("DEBUG: send_now ответ bot-service:", resp.status_code, resp_text)

            try:
                data = resp.json()
            except Exception:
                data = {}
            print('DEBUG: send_now разобранные данные ответа:', data)

            message_id = data.get('message_id')
            if not message_id and thread_id is not None:
                print('DEBUG: send_now не получен message_id; повтор без thread_id')
                payload2 = {"chat_id": chat_id, "text": text}
                try:
                    resp2 = await client.post(f"{BOT_SERVICE_URL}/send", json=payload2, timeout=15.0)
                    try:
                        resp2_text = resp2.text
                    except Exception:
                        resp2_text = '<невозможно прочитать тело ответа>'
                    print('DEBUG: send_now ответ bot-service (повтор):', resp2.status_code, resp2_text)
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
