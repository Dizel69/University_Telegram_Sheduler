"""Внутренний API для Telegram-бота и персональных напоминаний воркера.

Защита: X-INTERNAL-TOKEN (INTERNAL_SERVICE_TOKEN или ADMIN_TOKEN).
Не предназначен для публичного интернета без этого секрета.
"""

from __future__ import annotations

import hashlib
import html
import os
import re
from datetime import date, datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.database import engine
from app.deps import require_internal_service
from app.models import BotDialogState, Event, HomeworkCompletion, PersonalReminderSent, User
from app.security import verify_password
from app.subject_routes import clean_subject_name, normalize_subject_key
from app.type_utils import canonical_event_type

router = APIRouter(prefix="/internal/bot", tags=["internal-bot"], include_in_schema=False)

MSK = ZoneInfo("Europe/Moscow")
FRONTEND_URL = os.getenv("FRONTEND_URL") or (
    f"http://{os.getenv('HOST')}:3000" if os.getenv("HOST") else "http://127.0.0.1:3000"
)
DM_MORNING_SCHEDULE_TIME = (os.getenv("DM_MORNING_SCHEDULE_TIME") or "07:30").strip()
LESSON_TYPES = {"schedule", "exam_control", "transfer"}
MIRROR_TYPES = {"schedule", "homework", "announcement", "exam_control", "transfer"}
ALLOWED_HW_OFFSETS = {1, 3, 12, 24}
ALLOWED_LESSON_OFFSETS = {5, 10, 30}
# Poll воркера ~60с: пинг пары чуть позже отметки «за N минут», не до самого начала.
LESSON_SOON_GRACE = timedelta(minutes=2)
TRANSFER_EVE_TIME = time(17, 0)
SLOT_LOOKAHEAD_DAYS = 6
WEEKDAY_LABELS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
_TAG_RE = re.compile(r"<[^>]+>")
_HTTP_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_BARE_HOST_RE = re.compile(r"(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s]*)?", re.IGNORECASE)
_BARE_FIND_RE = re.compile(
    r"(?<![\w@/])((?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s<>\"']*)?)",
    re.IGNORECASE,
)

DIALOG_IDLE = "idle"
DIALOG_WAIT_LOGIN = "wait_login"
DIALOG_WAIT_PASSWORD = "wait_password"
DIALOG_WAIT_FEEDBACK = "wait_feedback"
DIALOG_WAIT_REBIND = "wait_rebind"


def now_msk() -> datetime:
    return datetime.now(MSK)


def today_msk() -> date:
    return now_msk().date()


def _esc(value: str) -> str:
    return html.escape(value or "", quote=False)


def display_short_name(user: User) -> str:
    initial = (user.first_name or "").strip()
    letter = initial[0].upper() if initial else ""
    last = (user.last_name or "").strip()
    if last and letter:
        return f"{last} {letter}."
    return last or (user.login or "студент")


def full_name(user: User) -> str:
    return " ".join(p for p in [user.last_name, user.first_name, user.middle_name] if p).strip()


def event_card_url(event_id: int) -> str:
    base = FRONTEND_URL.rstrip("/")
    return f"{base}/calendar/m15/event/{event_id}"


def _clock(value) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M")
    text = str(value).strip()
    if not text:
        return None
    parts = text.split(":")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"{int(parts[0]):02d}:{int(parts[1]):02d}"
    return text


def _plain_body(raw: str, limit: int = 140) -> str:
    text = _TAG_RE.sub(" ", raw or "")
    text = html.unescape(text)
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _lesson_type_label(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    key = str(raw).strip().lower()
    mapping = {
        "lecture": "лекция",
        "лекция": "лекция",
        "practice": "практика",
        "практика": "практика",
        "seminar": "семинар",
        "exam": "экзамен",
        "control": "контрольная",
        "лабораторная": "лабораторная",
        "lab": "лабораторная",
    }
    return mapping.get(key, str(raw).strip())


def _event_to_lesson(ev: Event) -> dict:
    subject = (ev.subject or ev.title or "Пара").strip()
    start = _clock(ev.time)
    end = _clock(ev.end_time)
    return {
        "id": ev.id,
        "date": ev.date.isoformat() if ev.date else None,
        "time": start,
        "end_time": end,
        "subject": subject,
        "room": (ev.room or "").strip() or None,
        "teacher": (ev.teacher or "").strip() or None,
        "lesson_type": _lesson_type_label(ev.lesson_type),
        "type": canonical_event_type(ev.type or ""),
    }


def format_lesson_line(item: dict) -> str:
    start = item.get("time")
    end = item.get("end_time")
    if start and end:
        when = f"{start}–{end}"
    elif start:
        when = start
    else:
        when = "время не указано"
    subject = _esc(item.get("subject") or "Пара")
    bits = [f"<b>{_esc(when)}</b> {subject}"]
    extra = []
    if item.get("room"):
        extra.append(f"ауд. {_esc(item['room'])}")
    if item.get("teacher"):
        extra.append(_esc(item["teacher"]))
    if item.get("lesson_type"):
        extra.append(_esc(item["lesson_type"]))
    if extra:
        bits.append(" · ".join(extra))
    return "\n".join(bits)


def format_day_lessons(title: str, lessons: list[dict], empty_text: str) -> str:
    if not lessons:
        return empty_text
    lines = [f"<b>{_esc(title)}</b>", ""]
    for item in lessons:
        lines.append(format_lesson_line(item))
        lines.append("")
    return "\n".join(lines).strip()


def _is_lesson(ev: Event) -> bool:
    return canonical_event_type(ev.type or "") in LESSON_TYPES


def _load_lessons_on(session: Session, day: date) -> list[Event]:
    rows = session.exec(select(Event).where(Event.date == day)).all()
    lessons = [ev for ev in rows if _is_lesson(ev)]
    lessons.sort(key=lambda e: (e.time is None, e.time or time.min, e.id or 0))
    return lessons


def _user_by_telegram(session: Session, telegram_id: int) -> Optional[User]:
    return session.exec(select(User).where(User.telegram_id == telegram_id)).first()


def _clean_url(raw: str) -> str:
    return (raw or "").strip().rstrip(").,;]>\"'")


def _looks_like_url(value: Optional[str]) -> bool:
    text = (value or "").strip()
    if not text or any(ch.isspace() for ch in text):
        return False
    low = text.lower()
    if low.startswith("http://") or low.startswith("https://"):
        return True
    if not _BARE_HOST_RE.fullmatch(text):
        return False
    host = text.split("/", 1)[0]
    return host.count(".") >= 2 or "/" in text


def _first_link(text: Optional[str]) -> Optional[str]:
    raw = text or ""
    http = _HTTP_RE.search(raw)
    if http:
        return _clean_url(http.group(0))
    bare = _BARE_FIND_RE.search(raw)
    if not bare:
        return None
    found = _clean_url(bare.group(1))
    return found if _looks_like_url(found) else None


def _event_link(ev: Event) -> Optional[str]:
    room = (ev.room or "").strip()
    if _looks_like_url(room):
        return _clean_url(room)
    return _first_link(ev.body)


def _place_lines(room: Optional[str], link: Optional[str]) -> list[str]:
    room_text = (room or "").strip()
    lines: list[str] = []
    if room_text and not _looks_like_url(room_text):
        lines.append(f"ауд {room_text}")
    if link:
        lines.append(link)
    elif room_text and _looks_like_url(room_text):
        lines.append(_clean_url(room_text))
    return lines


def _button_place(room: Optional[str], link: Optional[str]) -> str:
    room_text = (room or "").strip()
    parts: list[str] = []
    if room_text and not _looks_like_url(room_text):
        parts.append(f"ауд {room_text}")
    if link or _looks_like_url(room_text):
        parts.append("ссылка")
    return " ".join(parts)


def _slot_token(key: str) -> str:
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def _lesson_keys(user: User) -> list[str]:
    raw = user.dm_lesson_slot_keys
    if not isinstance(raw, list):
        return []
    keys: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            keys.append(item.strip())
    return keys


def build_first_slots(events: list[Event], origin: date) -> list[dict]:
    """Первая пара предмета в день недели: минимальное time среди type=schedule.

    Ключ стабильный (subject_key|weekday|HH:MM), без event.id конкретной недели.
    exam_control и transfer в список не входят.
    """
    grouped: dict[tuple[str, int], Event] = {}
    for ev in events:
        if canonical_event_type(ev.type or "") != "schedule":
            continue
        if ev.date is None or ev.time is None:
            continue
        name = clean_subject_name(ev.subject or ev.title)
        subject_key = normalize_subject_key(name)
        if not subject_key:
            continue
        weekday = ev.date.weekday()
        current = grouped.get((subject_key, weekday))
        if current is None or (ev.time, ev.id or 0) < (current.time or time.max, current.id or 0):
            grouped[(subject_key, weekday)] = ev

    slots: list[dict] = []
    for ev in grouped.values():
        name = clean_subject_name(ev.subject or ev.title)
        subject_key = normalize_subject_key(name)
        weekday = ev.date.weekday() if ev.date else 0
        hhmm = _clock(ev.time)
        if not hhmm:
            continue
        slot_key = f"{subject_key}|{weekday}|{hhmm}"
        link = _event_link(ev)
        room = (ev.room or "").strip() or None
        slots.append(
            {
                "key": slot_key,
                "token": _slot_token(slot_key),
                "subject": name or "Пара",
                "weekday": weekday,
                "weekday_label": WEEKDAY_LABELS[weekday],
                "time": hhmm,
                "start_time": ev.time,
                "room": None if _looks_like_url(room) else room,
                "link": link,
                "place_label": _button_place(room, link),
                "event_id": ev.id,
            }
        )
    slots.sort(
        key=lambda s: (
            (int(s["weekday"]) - origin.weekday()) % 7,
            s["time"],
            str(s["subject"]).casefold(),
        )
    )
    return slots


def _events_between(session: Session, start: date, end: date) -> list[Event]:
    return list(session.exec(select(Event).where(Event.date >= start, Event.date <= end)).all())


def _week_first_slots(session: Session, origin: Optional[date] = None) -> list[dict]:
    today = origin or today_msk()
    end = today + timedelta(days=SLOT_LOOKAHEAD_DAYS)
    return build_first_slots(_events_between(session, today, end), today)


def _public_slots(slots: list[dict], selected: set[str]) -> list[dict]:
    rows = []
    for slot in slots:
        rows.append(
            {
                "key": slot["key"],
                "token": slot["token"],
                "subject": slot["subject"],
                "weekday": slot["weekday"],
                "weekday_label": slot["weekday_label"],
                "time": slot["time"],
                "room": slot.get("room"),
                "link": slot.get("link"),
                "place_label": slot.get("place_label") or "",
                "selected": slot["key"] in selected,
            }
        )
    return rows


def format_lesson_soon_text(slot: dict, offset_min: int) -> str:
    lines = [f"<b>{_esc(slot.get('subject') or 'Пара')}</b>", _esc(slot.get("time") or "")]
    room = slot.get("room")
    link = slot.get("link")
    if room:
        lines.append(_esc(f"ауд {room}"))
    if link:
        lines.append(_esc(link))
    lines.append(f"через {int(offset_min)} мин")
    return "\n".join(line for line in lines if line)


def format_transfer_eve_text(ev: Event) -> str:
    subject = clean_subject_name(ev.subject or ev.title) or "Перенос"
    lines = ["<b>Перенос</b>", _esc(subject)]
    when = []
    if ev.date:
        when.append(ev.date.strftime("%d.%m.%Y"))
    clock = _clock(ev.time)
    if clock:
        when.append(clock)
    if when:
        lines.append(_esc(" ".join(when)))
    for part in _place_lines(ev.room, _event_link(ev)):
        lines.append(_esc(part))
    return "\n".join(lines)


def _dialog(session: Session, telegram_id: int) -> BotDialogState:
    row = session.get(BotDialogState, telegram_id)
    if row:
        return row
    row = BotDialogState(telegram_id=telegram_id, state=DIALOG_IDLE)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _public_user(user: User) -> dict:
    return {
        "id": user.id,
        "login": user.login,
        "last_name": user.last_name,
        "first_name": user.first_name,
        "middle_name": user.middle_name,
        "short_name": display_short_name(user),
        "full_name": full_name(user),
        "telegram_id": user.telegram_id,
        "is_admin": user.is_admin,
        "dm_mirror_posts": bool(user.dm_mirror_posts),
        "dm_mirror_asked": bool(user.dm_mirror_asked),
        "dm_morning_schedule": bool(user.dm_morning_schedule),
        "dm_homework_reminder": bool(user.dm_homework_reminder),
        "dm_homework_offset_hours": int(user.dm_homework_offset_hours or 24),
        "dm_lesson_soon": bool(user.dm_lesson_soon),
        "dm_lesson_offset_minutes": int(user.dm_lesson_offset_minutes or 5),
        "dm_lesson_slot_keys": _lesson_keys(user),
        "dm_transfer_eve": bool(user.dm_transfer_eve),
    }


def _settings_payload(user: User, slots: Optional[list[dict]] = None) -> dict:
    data = _public_user(user)
    data["morning_time"] = DM_MORNING_SCHEDULE_TIME
    data["timezone"] = "Europe/Moscow"
    data["morning_silent_if_empty"] = True
    selected = set(_lesson_keys(user))
    public = _public_slots(slots or [], selected)
    current_keys = [row["key"] for row in public]
    data["lesson_slots"] = public
    data["dm_lesson_all"] = bool(current_keys) and all(key in selected for key in current_keys)
    return data


class DialogPut(BaseModel):
    telegram_id: int
    state: str
    pending_login: Optional[str] = None
    login_message_id: Optional[int] = None
    pending_user_id: Optional[int] = None


class BotLoginBody(BaseModel):
    telegram_id: int
    login: str
    password: str
    confirm_rebind: bool = False


class TelegramIdBody(BaseModel):
    telegram_id: int


class SettingsPatch(BaseModel):
    telegram_id: int
    dm_mirror_posts: Optional[bool] = None
    dm_morning_schedule: Optional[bool] = None
    dm_homework_reminder: Optional[bool] = None
    dm_homework_offset_hours: Optional[int] = None
    dm_lesson_soon: Optional[bool] = None
    dm_lesson_offset_minutes: Optional[int] = None
    dm_lesson_all: Optional[bool] = None
    dm_lesson_slot_toggle: Optional[str] = None
    dm_transfer_eve: Optional[bool] = None
    dm_mirror_asked: Optional[bool] = None


class HomeworkDoneBody(BaseModel):
    telegram_id: int


class FeedbackBody(BaseModel):
    telegram_id: int
    text: str


class MarkPersonalBody(BaseModel):
    user_id: int
    kind: str
    dedupe_key: str
    event_id: Optional[int] = None


@router.get("/dialog")
def get_dialog(telegram_id: int, _: bool = Depends(require_internal_service)):
    with Session(engine) as session:
        row = session.get(BotDialogState, telegram_id)
        user = _user_by_telegram(session, telegram_id)
        return {
            "telegram_id": telegram_id,
            "state": row.state if row else DIALOG_IDLE,
            "pending_login": row.pending_login if row else None,
            "login_message_id": row.login_message_id if row else None,
            "pending_user_id": row.pending_user_id if row else None,
            "user": _public_user(user) if user else None,
        }


@router.put("/dialog")
def put_dialog(body: DialogPut, _: bool = Depends(require_internal_service)):
    with Session(engine) as session:
        row = session.get(BotDialogState, body.telegram_id)
        if not row:
            row = BotDialogState(telegram_id=body.telegram_id)
        row.state = body.state
        row.pending_login = body.pending_login
        row.login_message_id = body.login_message_id
        row.pending_user_id = body.pending_user_id
        row.updated_at = datetime.utcnow()
        session.add(row)
        session.commit()
        return {"ok": True, "state": row.state}


@router.post("/login")
def bot_login(body: BotLoginBody, _: bool = Depends(require_internal_service)):
    login_key = (body.login or "").strip()
    if not login_key or not body.password:
        raise HTTPException(status_code=400, detail="Укажите логин и пароль")

    with Session(engine) as session:
        user = session.exec(select(User).where(User.login == login_key)).first()
        if not user or not verify_password(body.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Неверный логин или пароль")

        occupied = _user_by_telegram(session, body.telegram_id)
        if occupied and occupied.id != user.id:
            raise HTTPException(
                status_code=409,
                detail="Этот Telegram уже привязан к другому аккаунту. Сначала /выход там.",
            )

        if user.telegram_id and user.telegram_id != body.telegram_id:
            if not body.confirm_rebind:
                dialog = _dialog(session, body.telegram_id)
                dialog.state = DIALOG_WAIT_REBIND
                dialog.pending_user_id = user.id
                dialog.pending_login = login_key
                dialog.updated_at = datetime.utcnow()
                session.add(dialog)
                session.commit()
                return {
                    "ok": False,
                    "need_rebind": True,
                    "message": "Этот аккаунт уже привязан к другому Telegram. Подтвердите перепривязку или сделайте /выход там.",
                }
            user.telegram_id = body.telegram_id
        else:
            user.telegram_id = body.telegram_id

        user.last_seen_at = datetime.utcnow()
        session.add(user)
        dialog = session.get(BotDialogState, body.telegram_id)
        if dialog:
            dialog.state = DIALOG_IDLE
            dialog.pending_login = None
            dialog.pending_user_id = None
            dialog.updated_at = datetime.utcnow()
            session.add(dialog)
        session.commit()
        session.refresh(user)
        return {
            "ok": True,
            "need_rebind": False,
            "ask_mirror": not bool(user.dm_mirror_asked),
            "user": _public_user(user),
        }


@router.post("/logout")
def bot_logout(body: TelegramIdBody, _: bool = Depends(require_internal_service)):
    with Session(engine) as session:
        user = _user_by_telegram(session, body.telegram_id)
        if user:
            user.telegram_id = None
            user.dm_mirror_posts = False
            user.dm_mirror_asked = False
            user.dm_morning_schedule = False
            user.dm_homework_reminder = False
            user.dm_homework_offset_hours = 24
            user.dm_lesson_soon = False
            user.dm_lesson_offset_minutes = 5
            user.dm_lesson_slot_keys = []
            user.dm_transfer_eve = False
            session.add(user)
        dialog = session.get(BotDialogState, body.telegram_id)
        if dialog:
            session.delete(dialog)
        session.commit()
        return {"ok": True}


@router.get("/me")
def bot_me(telegram_id: int, _: bool = Depends(require_internal_service)):
    with Session(engine) as session:
        user = _user_by_telegram(session, telegram_id)
        if not user:
            return {"user": None}
        return {"user": _settings_payload(user, _week_first_slots(session))}


@router.patch("/settings")
def bot_settings(body: SettingsPatch, _: bool = Depends(require_internal_service)):
    with Session(engine) as session:
        user = _user_by_telegram(session, body.telegram_id)
        if not user:
            raise HTTPException(status_code=401, detail="Сначала войдите через /start")
        if body.dm_mirror_posts is not None:
            user.dm_mirror_posts = bool(body.dm_mirror_posts)
            user.dm_mirror_asked = True
        if body.dm_mirror_asked is not None:
            user.dm_mirror_asked = bool(body.dm_mirror_asked)
        if body.dm_morning_schedule is not None:
            user.dm_morning_schedule = bool(body.dm_morning_schedule)
        if body.dm_homework_reminder is not None:
            user.dm_homework_reminder = bool(body.dm_homework_reminder)
        if body.dm_homework_offset_hours is not None:
            hours = int(body.dm_homework_offset_hours)
            if hours not in ALLOWED_HW_OFFSETS:
                raise HTTPException(status_code=400, detail="Допустимо 24, 12, 3 или 1 час")
            user.dm_homework_offset_hours = hours
        if body.dm_lesson_soon is not None:
            user.dm_lesson_soon = bool(body.dm_lesson_soon)
        if body.dm_lesson_offset_minutes is not None:
            minutes = int(body.dm_lesson_offset_minutes)
            if minutes not in ALLOWED_LESSON_OFFSETS:
                raise HTTPException(status_code=400, detail="Допустимо 5, 10 или 30 минут")
            user.dm_lesson_offset_minutes = minutes
        if body.dm_lesson_slot_toggle:
            token = body.dm_lesson_slot_toggle.strip()
            match = next(
                (slot for slot in _week_first_slots(session) if slot["token"] == token or slot["key"] == token),
                None,
            )
            if not match:
                raise HTTPException(status_code=400, detail="Слот не найден")
            keys = _lesson_keys(user)
            if match["key"] in keys:
                keys = [key for key in keys if key != match["key"]]
            else:
                keys.append(match["key"])
            user.dm_lesson_slot_keys = keys
        if body.dm_lesson_all is not None:
            if body.dm_lesson_all:
                user.dm_lesson_slot_keys = [slot["key"] for slot in _week_first_slots(session)]
            else:
                user.dm_lesson_slot_keys = []
        if body.dm_transfer_eve is not None:
            user.dm_transfer_eve = bool(body.dm_transfer_eve)
        session.add(user)
        session.commit()
        session.refresh(user)
        return {"ok": True, "user": _settings_payload(user, _week_first_slots(session))}


@router.get("/day")
def bot_day(
    telegram_id: int,
    day: Optional[str] = None,
    offset: int = 0,
    _: bool = Depends(require_internal_service),
):
    target = today_msk() + timedelta(days=int(offset or 0))
    if day:
        try:
            target = datetime.strptime(day, "%Y-%m-%d").date()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="неверная дата") from exc
    with Session(engine) as session:
        user = _user_by_telegram(session, telegram_id)
        if not user:
            raise HTTPException(status_code=401, detail="Сначала войдите через /start")
        lessons = [_event_to_lesson(ev) for ev in _load_lessons_on(session, target)]
        label = "Сегодня" if target == today_msk() else "Завтра" if target == today_msk() + timedelta(days=1) else target.strftime("%d.%m")
        title = f"{label}, {target.strftime('%d.%m.%Y')}"
        empty = f"На {target.strftime('%d.%m')} пар нет."
        return {
            "date": target.isoformat(),
            "lessons": lessons,
            "html": format_day_lessons(title, lessons, empty),
        }


@router.get("/next-lesson")
def bot_next_lesson(telegram_id: int, _: bool = Depends(require_internal_service)):
    now = now_msk()
    today = now.date()
    now_t = now.time().replace(microsecond=0)
    with Session(engine) as session:
        user = _user_by_telegram(session, telegram_id)
        if not user:
            raise HTTPException(status_code=401, detail="Сначала войдите через /start")
        today_lessons = [_event_to_lesson(ev) for ev in _load_lessons_on(session, today)]

        def parse_t(value: Optional[str]) -> Optional[time]:
            if not value:
                return None
            hh, mm = value.split(":")[:2]
            return time(int(hh), int(mm))

        current = None
        upcoming_today = []
        for item in today_lessons:
            start = parse_t(item.get("time")) or time.min
            end = parse_t(item.get("end_time"))
            if end and start <= now_t < end:
                current = item
            elif start > now_t:
                upcoming_today.append(item)
            elif not end and start > now_t:
                upcoming_today.append(item)

        if current:
            until = current.get("end_time") or "?"
            parts = [f"<b>Сейчас</b> до { _esc(until) }:", format_lesson_line(current)]
            if upcoming_today:
                parts.extend(["", "<b>Дальше:</b>", format_lesson_line(upcoming_today[0])])
            else:
                parts.extend(["", "Это последняя пара на сегодня."])
            return {"html": "\n".join(parts), "status": "now"}

        if upcoming_today:
            return {
                "html": "<b>Следующая пара сегодня:</b>\n" + format_lesson_line(upcoming_today[0]),
                "status": "later_today",
            }

        rows = session.exec(select(Event).where(Event.date > today)).all()
        future = [ev for ev in rows if _is_lesson(ev) and ev.date]
        future.sort(key=lambda e: (e.date, e.time is None, e.time or time.min, e.id or 0))
        if not future:
            return {"html": "Ближайших пар в календаре нет.", "status": "none"}
        nxt = _event_to_lesson(future[0])
        dlabel = datetime.strptime(nxt["date"], "%Y-%m-%d").strftime("%d.%m")
        return {
            "html": f"<b>На сегодня всё.</b> Ближайшая: {dlabel}\n" + format_lesson_line(nxt),
            "status": "next_day",
        }


@router.get("/week")
def bot_week(telegram_id: int, _: bool = Depends(require_internal_service)):
    today = today_msk()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    with Session(engine) as session:
        user = _user_by_telegram(session, telegram_id)
        if not user:
            raise HTTPException(status_code=401, detail="Сначала войдите через /start")
        rows = session.exec(
            select(Event).where(Event.date >= monday, Event.date <= sunday)
        ).all()
        by_day: dict[date, list[Event]] = {}
        for ev in rows:
            if ev.date and _is_lesson(ev):
                by_day.setdefault(ev.date, []).append(ev)
        lines = [f"<b>Неделя {monday.strftime('%d.%m')}–{sunday.strftime('%d.%m')}</b>", ""]
        any_lessons = False
        for i in range(7):
            day = monday + timedelta(days=i)
            evs = sorted(
                by_day.get(day, []),
                key=lambda e: (e.time is None, e.time or time.min, e.id or 0),
            )
            if not evs:
                continue
            any_lessons = True
            lines.append(f"<b>{weekdays[i]} {day.strftime('%d.%m')}</b>")
            for ev in evs:
                item = _event_to_lesson(ev)
                start = item.get("time") or "—"
                subj = _esc(item.get("subject") or "Пара")
                room = f" ({_esc(item['room'])})" if item.get("room") else ""
                lines.append(f"{_esc(start)} {subj}{room}")
            lines.append("")
        if not any_lessons:
            return {"html": "На этой неделе пар нет.", "days": []}
        return {"html": "\n".join(lines).strip()}


@router.get("/homework")
def bot_homework(telegram_id: int, _: bool = Depends(require_internal_service)):
    with Session(engine) as session:
        user = _user_by_telegram(session, telegram_id)
        if not user:
            raise HTTPException(status_code=401, detail="Сначала войдите через /start")
        done_ids = {
            r.event_id
            for r in session.exec(
                select(HomeworkCompletion).where(HomeworkCompletion.user_id == user.id)
            ).all()
        }
        rows = session.exec(select(Event)).all()
        open_hw = [
            ev
            for ev in rows
            if canonical_event_type(ev.type or "") == "homework" and ev.id not in done_ids
        ]
        open_hw.sort(key=lambda e: (e.date is None, e.date or date.max, e.time is None, e.time or time.min, e.id or 0))
        items = []
        for ev in open_hw:
            title = (ev.subject or ev.title or "ДЗ").strip()
            when = ev.date.strftime("%d.%m") if ev.date else "без даты"
            clock = _clock(ev.time)
            if clock:
                when = f"{when} {clock}"
            body = _plain_body(ev.body or "")
            html_item = f"<b>{_esc(title)}</b>\n{_esc(when)}"
            if body:
                html_item += f"\n{_esc(body)}"
            items.append(
                {
                    "event_id": ev.id,
                    "html": html_item,
                    "url": event_card_url(ev.id),
                    "done": False,
                }
            )
        if not items:
            return {"html": "Открытых ДЗ нет. Все задания закрыты.", "items": []}
        return {"html": f"<b>Открытые ДЗ</b> ({len(items)})", "items": items}


@router.post("/homework/{event_id}/done")
def bot_homework_done(
    event_id: int,
    body: HomeworkDoneBody,
    _: bool = Depends(require_internal_service),
):
    with Session(engine) as session:
        user = _user_by_telegram(session, body.telegram_id)
        if not user:
            raise HTTPException(status_code=401, detail="Сначала войдите через /start")
        ev = session.get(Event, event_id)
        if not ev:
            raise HTTPException(status_code=404, detail="Событие не найдено")
        if canonical_event_type(ev.type or "") != "homework":
            raise HTTPException(status_code=400, detail="Можно отмечать только домашние задания")
        dup = session.exec(
            select(HomeworkCompletion).where(
                HomeworkCompletion.user_id == user.id,
                HomeworkCompletion.event_id == event_id,
            )
        ).first()
        if not dup:
            session.add(HomeworkCompletion(user_id=user.id, event_id=event_id))
            session.commit()
        return {"ok": True}


@router.get("/mirror-targets")
def mirror_targets(_: bool = Depends(require_internal_service)):
    with Session(engine) as session:
        users = session.exec(
            select(User).where(User.telegram_id.is_not(None), User.dm_mirror_posts == True)  # noqa: E712
        ).all()
        return {
            "telegram_ids": [int(u.telegram_id) for u in users if u.telegram_id],
        }


def list_mirror_telegram_ids() -> list[int]:
    with Session(engine) as session:
        users = session.exec(
            select(User).where(User.telegram_id.is_not(None), User.dm_mirror_posts == True)  # noqa: E712
        ).all()
        return [int(u.telegram_id) for u in users if u.telegram_id]


def should_mirror_event_type(event_type: Optional[str]) -> bool:
    return canonical_event_type(event_type or "") in MIRROR_TYPES


@router.get("/due-personal")
def due_personal(_: bool = Depends(require_internal_service)):
    """Утро, ДЗ, первая пара и перенос — только в личку. Если пар нет — утро молчит."""
    now = now_msk()
    today = now.date()
    morning = _parse_hhmm(DM_MORNING_SCHEDULE_TIME)
    morning_due = (now.hour, now.minute) >= (morning.hour, morning.minute)
    tomorrow = today + timedelta(days=1)
    transfer_eve_due = (now.hour, now.minute) >= (TRANSFER_EVE_TIME.hour, TRANSFER_EVE_TIME.minute)

    out_morning = []
    out_hw = []
    out_lesson = []
    out_transfer = []
    with Session(engine) as session:
        users = session.exec(select(User).where(User.telegram_id.is_not(None))).all()
        sent_rows = session.exec(select(PersonalReminderSent)).all()
        sent = {(r.user_id, r.kind, r.dedupe_key) for r in sent_rows}

        today_lessons = [_event_to_lesson(ev) for ev in _load_lessons_on(session, today)]
        day_html = format_day_lessons(
            f"Расписание на сегодня, {today.strftime('%d.%m')}",
            today_lessons,
            "",
        )

        all_events = session.exec(select(Event)).all()
        completions = session.exec(select(HomeworkCompletion)).all()
        done_map: dict[int, set[int]] = {}
        for c in completions:
            done_map.setdefault(c.user_id, set()).add(c.event_id)

        today_first = build_first_slots([ev for ev in all_events if ev.date == today], today)
        transfers_tomorrow = [
            ev
            for ev in all_events
            if ev.date == tomorrow and canonical_event_type(ev.type or "") == "transfer"
        ]

        for user in users:
            tid = int(user.telegram_id)
            if user.dm_morning_schedule and morning_due and today_lessons:
                key = today.isoformat()
                if (user.id, "morning", key) not in sent:
                    out_morning.append(
                        {
                            "user_id": user.id,
                            "telegram_id": tid,
                            "kind": "morning",
                            "dedupe_key": key,
                            "text": day_html,
                        }
                    )
            if user.dm_homework_reminder:
                offset = int(user.dm_homework_offset_hours or 24)
                done = done_map.get(user.id, set())
                for ev in all_events:
                    if canonical_event_type(ev.type or "") != "homework":
                        continue
                    if ev.id in done or ev.date is None:
                        continue
                    event_time = ev.time if ev.time else time.min
                    due_at = datetime.combine(ev.date, event_time, tzinfo=MSK)
                    remind_at = due_at - timedelta(hours=offset)
                    if now < remind_at:
                        continue
                    key = str(ev.id)
                    if (user.id, "homework", key) in sent:
                        continue
                    title = (ev.subject or ev.title or "ДЗ").strip()
                    when = ev.date.strftime("%d.%m")
                    clock = _clock(ev.time)
                    if clock:
                        when = f"{when} {clock}"
                    text = (
                        f"<b>Напоминание о ДЗ</b>\n{_esc(title)}\nдо {_esc(when)}\n"
                        f"{_esc(_plain_body(ev.body or ''))}"
                    ).strip()
                    out_hw.append(
                        {
                            "user_id": user.id,
                            "telegram_id": tid,
                            "event_id": ev.id,
                            "kind": "homework",
                            "dedupe_key": key,
                            "text": text,
                            "url": event_card_url(ev.id),
                        }
                    )
            if tid > 0 and user.dm_lesson_soon:
                offset_min = int(user.dm_lesson_offset_minutes or 5)
                if offset_min not in ALLOWED_LESSON_OFFSETS:
                    offset_min = 5
                selected = set(_lesson_keys(user))
                for slot in today_first:
                    if slot["key"] not in selected or slot.get("start_time") is None:
                        continue
                    start = datetime.combine(today, slot["start_time"], tzinfo=MSK)
                    remind_at = start - timedelta(minutes=offset_min)
                    if now < remind_at or now >= remind_at + LESSON_SOON_GRACE or now >= start:
                        continue
                    dedupe = f"{today.isoformat()}|{slot['key']}"
                    if (user.id, "lesson_soon", dedupe) in sent:
                        continue
                    out_lesson.append(
                        {
                            "user_id": user.id,
                            "telegram_id": tid,
                            "event_id": slot.get("event_id"),
                            "kind": "lesson_soon",
                            "dedupe_key": dedupe,
                            "text": format_lesson_soon_text(slot, offset_min),
                        }
                    )
            if tid > 0 and user.dm_transfer_eve and transfer_eve_due:
                for ev in transfers_tomorrow:
                    dedupe = str(ev.id)
                    if (user.id, "transfer_eve", dedupe) in sent:
                        continue
                    out_transfer.append(
                        {
                            "user_id": user.id,
                            "telegram_id": tid,
                            "event_id": ev.id,
                            "kind": "transfer_eve",
                            "dedupe_key": dedupe,
                            "text": format_transfer_eve_text(ev),
                        }
                    )
    return {
        "morning": out_morning,
        "homework": out_hw,
        "lesson_soon": out_lesson,
        "transfer_eve": out_transfer,
    }


@router.post("/mark-personal-sent")
def mark_personal_sent(body: MarkPersonalBody, _: bool = Depends(require_internal_service)):
    with Session(engine) as session:
        existing = session.exec(
            select(PersonalReminderSent).where(
                PersonalReminderSent.user_id == body.user_id,
                PersonalReminderSent.kind == body.kind,
                PersonalReminderSent.dedupe_key == body.dedupe_key,
            )
        ).first()
        if not existing:
            session.add(
                PersonalReminderSent(
                    user_id=body.user_id,
                    event_id=body.event_id,
                    kind=body.kind,
                    dedupe_key=body.dedupe_key,
                )
            )
            session.commit()
        return {"ok": True}


@router.post("/feedback")
async def bot_feedback(body: FeedbackBody, _: bool = Depends(require_internal_service)):
    from app.feedback_routes import (
        BOT_SERVICE_URL,
        _esc as fb_esc,
        _feedback_chat_id,
        _sender_label,
    )

    text = (body.text or "").strip()
    if len(text) < 3:
        raise HTTPException(status_code=400, detail="Слишком коротко, напишите подробнее")
    chat_id = _feedback_chat_id()
    if chat_id is None:
        raise HTTPException(status_code=503, detail="Обратная связь ещё не настроена (нужен FEEDBACK_CHAT_ID)")

    with Session(engine) as session:
        user = _user_by_telegram(session, body.telegram_id)
        if not user:
            raise HTTPException(status_code=401, detail="Сначала войдите через /start")
        sender = _sender_label(user)
        lines = [
            "<b>Обратная связь из Telegram</b>",
            "",
            fb_esc(text[:3500]),
            "",
            f"От: {fb_esc(sender or user.login)}",
            f"login: <code>{fb_esc(user.login)}</code>",
            f"telegram_id: <code>{int(body.telegram_id)}</code>",
            f"ФИО: {fb_esc(full_name(user))}",
        ]
        payload = {"chat_id": chat_id, "text": "\n".join(lines)[:4090]}

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(f"{BOT_SERVICE_URL}/send", json=payload, timeout=45.0)
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail="Не удалось связаться с ботом") from exc
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail="Не удалось отправить сообщение в Telegram")
    with Session(engine) as session:
        dialog = session.get(BotDialogState, body.telegram_id)
        if dialog:
            dialog.state = DIALOG_IDLE
            dialog.pending_login = None
            dialog.updated_at = datetime.utcnow()
            session.add(dialog)
            session.commit()
    return {"ok": True}


def _parse_hhmm(value: str) -> time:
    try:
        hh, mm = value.split(":", 1)
        return time(int(hh), int(mm))
    except Exception:
        return time(7, 30)
