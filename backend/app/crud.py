from sqlmodel import select
from .models import Event
from .database import engine
from sqlalchemy.exc import SQLAlchemyError
from typing import List
from datetime import datetime, timedelta


def add_event(event: Event) -> Event:
    """
    Сохраняет Event (SQLModel объект) и возвращает обновлённый объект с id.
    """
    try:
        with engine.begin() as conn:
            conn.add(event)
            conn.commit()
            conn.refresh(event)
            return event
    except SQLAlchemyError:
        raise


def get_public_events(limit: int = 500) -> List[Event]:
    """
    Возвращает все события (для публичного календаря), отсортированные по дате/времени.
    """
    with engine.connect() as conn:
        statement = select(Event).order_by(Event.date, Event.time)
        result = conn.exec(statement).all()
        return result[:limit]


def get_due_reminders(now: datetime | None = None) -> List[Event]:
    """
    Возвращает события, у которых reminder_sent == False и время напоминания <= now.
    """
    if now is None:
        now = datetime.utcnow()
    with engine.connect() as conn:
        statement = select(Event).where(Event.reminder_sent == False)
        rows = conn.exec(statement).all()
        due = []
        for ev in rows:
            if ev.date is None:
                continue
            # Сборка datetime события (если time пуст — берем 00:00)
            event_time = ev.time if ev.time else datetime.min.time()
            event_dt = datetime.combine(ev.date, event_time)
            remind_at = event_dt - timedelta(hours=ev.reminder_offset_hours)
            if remind_at <= now:
                due.append(ev)
        return due


def mark_reminder_sent(event_id: int) -> bool:
    """
    Помечает remind_sent = True для заданного event_id.
    """
    with engine.begin() as conn:
        ev = conn.get(Event, event_id)
        if ev:
            ev.reminder_sent = True
            conn.add(ev)
            conn.commit()
            return True
        return False


def set_sent_message(event_id: int, message_id: int) -> bool:
    """
    Сохраняет sent_message_id после успешной отправки ботом.
    """
    with engine.begin() as conn:
        ev = conn.get(Event, event_id)
        if ev:
            ev.sent_message_id = message_id
            conn.add(ev)
            conn.commit()
            return True
        return False
