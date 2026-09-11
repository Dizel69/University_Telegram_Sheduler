"""Внутренний API для Telegram-бота и персональных напоминаний воркера.

Защита: X-INTERNAL-TOKEN (INTERNAL_SERVICE_TOKEN или ADMIN_TOKEN).
Не предназначен для публичного интернета без этого секрета.
"""

from __future__ import annotations

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
_TAG_RE = re.compile(r"<[^>]+>")

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
    }


def _settings_payload(user: User) -> dict:
    data = _public_user(user)
    data["morning_time"] = DM_MORNING_SCHEDULE_TIME
    data["timezone"] = "Europe/Moscow"
    data["morning_silent_if_empty"] = True
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
        return {"user": _settings_payload(user)}


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
        session.add(user)
        session.commit()
        session.refresh(user)
        return {"ok": True, "user": _settings_payload(user)}


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
    """Утреннее расписание и пинги ДЗ только в личку. Если пар нет — молчим."""
    now = now_msk()
    today = now.date()
    morning = _parse_hhmm(DM_MORNING_SCHEDULE_TIME)
    morning_due = (now.hour, now.minute) >= (morning.hour, morning.minute)

    out_morning = []
    out_hw = []
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
            if not user.dm_homework_reminder:
                continue
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
    return {"morning": out_morning, "homework": out_hw}


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
