import datetime as dt
from datetime import timedelta
from typing import List, Set

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app import database
from app.deps import require_admin
from app.models import AttendanceMark, Event, User
from app.schemas import (
    AttendanceBoard,
    AttendanceDayColumn,
    AttendanceMarkPublic,
    AttendanceMarkSet,
    UserPublic,
)
from app.type_utils import canonical_event_type

router = APIRouter(tags=["attendance"])

_SCHEDULE_TYPES = frozenset({"schedule", "exam_control"})


def _monday_week_start(d: dt.date) -> dt.date:
    return d - timedelta(days=d.weekday())


def _subjects_for_date(session: Session, day: dt.date, *, fallback_global: bool) -> List[str]:
    events = session.exec(select(Event).where(Event.date == day)).all()
    subjects: Set[str] = set()
    for ev in events:
        if canonical_event_type(ev.type or "") not in _SCHEDULE_TYPES:
            continue
        subj = (ev.subject or ev.title or "").strip()
        if subj:
            subjects.add(subj)

    if subjects or not fallback_global:
        return sorted(subjects)

    all_schedule = session.exec(select(Event)).all()
    for ev in all_schedule:
        if canonical_event_type(ev.type or "") not in _SCHEDULE_TYPES:
            continue
        subj = (ev.subject or ev.title or "").strip()
        if subj:
            subjects.add(subj)
    return sorted(subjects)


@router.get("/admin/attendance", response_model=AttendanceBoard)
def get_attendance_board(
    week_start: dt.date = Query(
        ...,
        alias="week_start",
        description="Любой день; неделя берётся с понедельника по воскресенье (передайте понедельник или любую дату внутри недели)",
    ),
    _admin=Depends(require_admin),
):
    monday = _monday_week_start(week_start)
    sunday = monday + timedelta(days=6)

    with Session(database.engine) as session:
        users = session.exec(
            select(User)
            .where(User.is_admin == False)  # noqa: E712
            .order_by(User.last_name, User.first_name)
        ).all()

        days_out: List[AttendanceDayColumn] = []
        for i in range(7):
            d = monday + timedelta(days=i)
            subj = _subjects_for_date(session, d, fallback_global=False)
            days_out.append(AttendanceDayColumn(date=d, subjects=subj))

        marks_rows = session.exec(
            select(AttendanceMark).where(
                AttendanceMark.attendance_date >= monday,
                AttendanceMark.attendance_date <= sunday,
            )
        ).all()

        marks = [
            AttendanceMarkPublic(
                user_id=r.user_id,
                subject=r.subject,
                date=r.attendance_date,
                mark=r.mark,
            )
            for r in marks_rows
        ]

        # подтянуть предметы, по которым уже есть отметки, в соответствующий день
        for m in marks:
            d = m.date
            if d < monday or d > sunday:
                continue
            for col in days_out:
                if col.date == d and m.subject not in col.subjects:
                    col.subjects.append(m.subject)
                    col.subjects.sort()

        return AttendanceBoard(
            week_start=monday,
            week_end=sunday,
            users=[UserPublic.from_orm(u) for u in users],
            days=days_out,
            marks=marks,
        )


@router.put("/admin/attendance")
def set_attendance_mark(payload: AttendanceMarkSet, _admin=Depends(require_admin)):
    subject = payload.subject.strip()
    if not subject:
        raise HTTPException(status_code=400, detail="Укажите предмет")

    with Session(database.engine) as session:
        user = session.get(User, payload.user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        if user.is_admin:
            raise HTTPException(status_code=400, detail="Для учётной записи администратора посещаемость не ведётся")

        existing = session.exec(
            select(AttendanceMark).where(
                AttendanceMark.user_id == payload.user_id,
                AttendanceMark.subject == subject,
                AttendanceMark.attendance_date == payload.date,
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
                    subject=subject,
                    attendance_date=payload.date,
                    mark=payload.mark,
                )
            )
        session.commit()
    return {"ok": True}
