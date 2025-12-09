from sqlmodel import select, Session
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
        with Session(engine) as session:
            session.add(event)
            session.commit()
            session.refresh(event)
            return event
    except SQLAlchemyError:
        raise


def get_public_events(limit: int = 500) -> List[Event]:
    """
    Возвращает все события (для публичного календаря), отсортированные по дате/времени.
    """
    with Session(engine) as session:
        statement = select(Event).order_by(Event.date, Event.time)
        result = session.exec(statement).all()
        return result[:limit]


def get_due_reminders(now: datetime | None = None) -> List[Event]:
    """
    Возвращает события, у которых reminder_sent == False и время напоминания <= now.
    """
    if now is None:
        now = datetime.utcnow()
    with Session(engine) as session:
        statement = select(Event).where(Event.reminder_sent == False)
        rows = session.exec(statement).all()
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
    with Session(engine) as session:
        ev = session.get(Event, event_id)
        if ev:
            ev.reminder_sent = True
            session.add(ev)
            session.commit()
            return True
        return False


def set_sent_message(event_id: int, message_id: int) -> bool:
    """
    Сохраняет sent_message_id после успешной отправки ботом.
    """
    with Session(engine) as session:
        ev = session.get(Event, event_id)
        if ev:
            ev.sent_message_id = message_id
            session.add(ev)
            session.commit()
            return True
        return False

def get_event_by_id(event_id: int):
    """
    Возвращает Event по id или None, если не найден.
    """
    with Session(engine) as session:
        ev = session.get(Event, event_id)
        return ev


def delete_event(event_id: int) -> bool:
    """
    Удаляет событие по id. Возвращает True если удалено, False если не найдено.
    """
    with Session(engine) as session:
        ev = session.get(Event, event_id)
        if not ev:
            return False
        session.delete(ev)
        session.commit()
        return True


def update_event(event_id: int, **fields) -> bool:
    """
    Update given fields on an Event. Returns True if event found and updated.
    """
    with Session(engine) as session:
        ev = session.get(Event, event_id)
        if not ev:
            return False
        for k, v in fields.items():
            if hasattr(ev, k):
                setattr(ev, k, v)
        session.add(ev)
        session.commit()
        return True
