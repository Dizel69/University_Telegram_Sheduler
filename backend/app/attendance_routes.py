import datetime as dt
from typing import List, Set

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app import database
from app.deps import require_admin
from app.models import AttendanceMark, Event, User
from app.schemas import AttendanceBoard, AttendanceMarkPublic, AttendanceMarkSet, UserPublic
from app.type_utils import canonical_event_type

router = APIRouter(tags=["attendance"])

_SCHEDULE_TYPES = frozenset({"schedule", "exam_control"})


def _subjects_for_date(session: Session, day: dt.date) -> List[str]:
    events = session.exec(select(Event).where(Event.date == day)).all()
    subjects: Set[str] = set()
    for ev in events:
        if canonical_event_type(ev.type or "") not in _SCHEDULE_TYPES:
            continue
        subj = (ev.subject or ev.title or "").strip()
        if subj:
            subjects.add(subj)

    if subjects:
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
    date: dt.date = Query(..., description="Дата посещаемости (YYYY-MM-DD)"),
    _admin=Depends(require_admin),
):
    with Session(database.engine) as session:
        users = session.exec(select(User).order_by(User.last_name, User.first_name)).all()
        subjects = _subjects_for_date(session, date)
        rows = session.exec(select(AttendanceMark).where(AttendanceMark.attendance_date == date)).all()
        marks = [
            AttendanceMarkPublic(user_id=r.user_id, subject=r.subject, mark=r.mark)
            for r in rows
        ]
        for m in marks:
            if m.subject not in subjects:
                subjects.append(m.subject)
        subjects.sort()
        return AttendanceBoard(
            date=date,
            users=[UserPublic.from_orm(u) for u in users],
            subjects=subjects,
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
