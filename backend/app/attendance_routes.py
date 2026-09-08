import datetime as dt
from datetime import time as dt_time, timedelta
from typing import List, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app import database
from app.deps import require_admin
from app.models import AttendanceMark, Event, User
from app.schemas import (
    AttendanceBoard,
    AttendanceDayColumn,
    AttendanceLessonSlot,
    AttendanceMarkPublic,
    AttendanceMarkSet,
    UserPublic,
)
from app.type_utils import canonical_event_type

router = APIRouter(tags=["attendance"])

_ATTENDANCE_TYPES = frozenset({"schedule", "transfer"})
_SCHEDULE_LIKE_TYPES = frozenset({"schedule", "exam_control", "transfer"})


def _monday_week_start(d: dt.date) -> dt.date:
    return d - timedelta(days=d.weekday())


def _event_subject(ev: Event) -> str:
    return (ev.subject or ev.title or "").strip()


def _lesson_label(ev: Event) -> str:
    subj = _event_subject(ev) or "Предмет"
    tag = ""
    if canonical_event_type(ev.type or "") == "transfer":
        tag = " — перенос"
    if ev.time:
        return f"{subj}{tag} ({ev.time.strftime('%H:%M')})"
    return f"{subj}{tag}".strip()


def _slot_sort_key(ev: Event) -> Tuple:
    t = ev.time or dt_time(23, 59, 59)
    return (t, ev.id or 0)


def _is_attendance_event(ev: Event) -> bool:
    return canonical_event_type(ev.type or "") in _ATTENDANCE_TYPES


def _is_schedule_event(ev: Event) -> bool:
    """Пары, переносы и контрольные/экзамены — для аналитики нагрузки, не для отметок."""
    return canonical_event_type(ev.type or "") in _SCHEDULE_LIKE_TYPES


def _attendance_events_for_day(events: List[Event]) -> List[Event]:
    """Пары и переносы дня. Контрольные и экзамены в посещаемость не входят."""
    out = [ev for ev in events if _is_attendance_event(ev) and _event_subject(ev)]
    out.sort(key=_slot_sort_key)
    return out


def _slots_for_date(session: Session, day: dt.date) -> List[AttendanceLessonSlot]:
    events = session.exec(select(Event).where(Event.date == day)).all()
    return [
        AttendanceLessonSlot(
            event_id=ev.id,
            subject=_event_subject(ev),
            label=_lesson_label(ev),
        )
        for ev in _attendance_events_for_day(events)
    ]


def _resort_day_slots(col: AttendanceDayColumn, session: Session) -> None:
    evs = []
    for s in col.slots:
        ev = session.get(Event, s.event_id)
        if ev:
            evs.append(ev)
    evs.sort(key=_slot_sort_key)
    col.slots = [
        AttendanceLessonSlot(
            event_id=ev.id,
            subject=_event_subject(ev),
            label=_lesson_label(ev),
        )
        for ev in evs
    ]


def _merge_mark_slots(days_out: List[AttendanceDayColumn], marks: List[AttendanceMarkPublic], session: Session) -> None:
    """Добавить столбцы для отметок, если событие ещё не попало в сетку."""
    known = {s.event_id for d in days_out for s in d.slots}
    for m in marks:
        if m.event_id in known:
            continue
        ev = session.get(Event, m.event_id)
        if not ev or not ev.date or not _is_attendance_event(ev):
            continue
        for col in days_out:
            if col.date != ev.date:
                continue
            col.slots.append(
                AttendanceLessonSlot(
                    event_id=ev.id,
                    subject=_event_subject(ev) or "Предмет",
                    label=_lesson_label(ev),
                )
            )
            known.add(m.event_id)
            break
    for col in days_out:
        if col.slots:
            _resort_day_slots(col, session)


@router.get("/admin/attendance", response_model=AttendanceBoard)
def get_attendance_board(
    week_start: dt.date = Query(
        ...,
        alias="week_start",
        description="Любой день; неделя с понедельника по воскресенье",
    ),
    _admin=Depends(require_admin),
):
    monday = _monday_week_start(week_start)
    sunday = monday + timedelta(days=6)

    with Session(database.engine) as session:
        users = session.exec(
            select(User)
            .where(User.is_owner == False)  # noqa: E712
            .order_by(User.last_name, User.first_name)
        ).all()

        days_out: List[AttendanceDayColumn] = []
        for i in range(7):
            d = monday + timedelta(days=i)
            days_out.append(AttendanceDayColumn(date=d, slots=_slots_for_date(session, d)))

        marks_rows: List[AttendanceMark] = []
        for r in session.exec(select(AttendanceMark)).all():
            ev = session.get(Event, r.event_id)
            if ev and ev.date and monday <= ev.date <= sunday and _is_attendance_event(ev):
                marks_rows.append(r)

        marks = [
            AttendanceMarkPublic(user_id=r.user_id, event_id=r.event_id, mark=r.mark)
            for r in marks_rows
        ]
        _merge_mark_slots(days_out, marks, session)

        return AttendanceBoard(
            week_start=monday,
            week_end=sunday,
            users=[UserPublic.from_orm(u) for u in users],
            days=days_out,
            marks=marks,
        )


@router.put("/admin/attendance")
def set_attendance_mark(payload: AttendanceMarkSet, _admin=Depends(require_admin)):
    with Session(database.engine) as session:
        user = session.get(User, payload.user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        if user.is_owner:
            raise HTTPException(status_code=400, detail="Для учётной записи владельца посещаемость не ведётся")

        ev = session.get(Event, payload.event_id)
        if not ev:
            raise HTTPException(status_code=404, detail="Событие не найдено")
        if not _is_attendance_event(ev):
            raise HTTPException(status_code=400, detail="Отметка только для пары из расписания")

        existing = session.exec(
            select(AttendanceMark).where(
                AttendanceMark.user_id == payload.user_id,
                AttendanceMark.event_id == payload.event_id,
            )
        ).first()

        if payload.mark is None:
            if existing:
                session.delete(existing)
                session.commit()
            return {"ok": True}

        if existing:
            existing.mark = payload.mark
            session.add(existing)
        else:
            session.add(
                AttendanceMark(
                    user_id=payload.user_id,
                    event_id=payload.event_id,
                    mark=payload.mark,
                )
            )
        session.commit()
    return {"ok": True}
