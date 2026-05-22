import datetime as dt
from calendar import monthrange
from collections import defaultdict
from datetime import timedelta
from typing import Dict, List, Optional, Set, Tuple

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from app import database
from app.attendance_routes import (
    _attendance_events_for_day,
    _event_subject,
    _is_schedule_event,
    _monday_week_start,
)
from app.deps import require_admin
from app.models import AttendanceMark, Event, HomeworkCompletion, User
from app.schemas import (
    AnalyticsDashboard,
    AnalyticsKpi,
    AnalyticsStudentRow,
    AnalyticsSubjectRow,
    AnalyticsTelegramStats,
    AnalyticsWeeklyPoint,
    UserPublic,
)
from app.semester_utils import normalize_semester_label
from app.type_utils import canonical_event_type

router = APIRouter(tags=["analytics"])

_POST_TYPES = frozenset({"homework", "announcement", "exam_control", "transfer"})
_TREND_WEEKS = 8


def _period_bounds(
    period: str,
    week_start: Optional[dt.date],
    year: Optional[int],
    month: Optional[int],
) -> Tuple[dt.date, dt.date, str]:
    today = dt.date.today()
    p = (period or "week").strip().lower()
    if p == "month":
        y = year or today.year
        m = month or today.month
        if m < 1 or m > 12:
            m = today.month
        last = monthrange(y, m)[1]
        return dt.date(y, m, 1), dt.date(y, m, last), "month"
    if p == "all":
        return dt.date(2000, 1, 1), today, "all"
    anchor = week_start or today
    monday = _monday_week_start(anchor)
    return monday, monday + timedelta(days=6), "week"


def _student_users(session: Session) -> List[User]:
    return session.exec(
        select(User)
        .where(User.is_owner == False)  # noqa: E712
        .order_by(User.last_name, User.first_name)
    ).all()


def _user_display_name(u: User) -> str:
    parts = [u.last_name, u.first_name]
    if u.middle_name:
        parts.append(u.middle_name)
    return " ".join(p for p in parts if p)


def _attendance_slots_in_range(
    session: Session,
    start: dt.date,
    end: dt.date,
) -> List[Tuple[int, int, str]]:
    """(event_id, user_id implicit later, subject) — one row per lesson slot."""
    events = session.exec(
        select(Event).where(Event.date != None, Event.date >= start, Event.date <= end)  # noqa: E711
    ).all()
    by_day: Dict[dt.date, List[Event]] = defaultdict(list)
    for ev in events:
        if ev.date:
            by_day[ev.date].append(ev)
    slots: List[Tuple[int, str]] = []
    for day in sorted(by_day.keys()):
        for ev in _attendance_events_for_day(by_day[day]):
            subj = _event_subject(ev) or "Без предмета"
            slots.append((ev.id, subj))
    return slots


def _marks_map(session: Session, start: dt.date, end: dt.date) -> Dict[Tuple[int, int], str]:
    out: Dict[Tuple[int, int], str] = {}
    for row in session.exec(select(AttendanceMark)).all():
        ev = session.get(Event, row.event_id)
        if not ev or not ev.date or ev.date < start or ev.date > end:
            continue
        out[(row.user_id, row.event_id)] = row.mark
    return out


def _homework_events(
    session: Session,
    start: dt.date,
    end: dt.date,
    semester: Optional[str],
) -> List[Event]:
    events = session.exec(
        select(Event).where(Event.date != None, Event.date >= start, Event.date <= end)  # noqa: E711
    ).all()
    out = []
    for ev in events:
        if canonical_event_type(ev.type or "") != "homework":
            continue
        if semester:
            if normalize_semester_label(getattr(ev, "semester", None)) != semester:
                continue
        out.append(ev)
    return out


def _completions_set(session: Session) -> Set[Tuple[int, int]]:
    return {(r.user_id, r.event_id) for r in session.exec(select(HomeworkCompletion)).all()}


def _attendance_rate(
    slot_event_ids: List[int],
    user_ids: List[int],
    marks: Dict[Tuple[int, int], str],
) -> Tuple[float, int, int, int]:
    if not slot_event_ids or not user_ids:
        return 0.0, 0, 0, 0
    total = len(slot_event_ids) * len(user_ids)
    absent = sick = 0
    for uid in user_ids:
        for eid in slot_event_ids:
            m = marks.get((uid, eid))
            if m == "N":
                absent += 1
            elif m == "B":
                sick += 1
    present = total - absent - sick
    rate = round(100.0 * present / total, 1) if total else 0.0
    return rate, absent, sick, total


def _homework_stats(
    hw_events: List[Event],
    user_ids: List[int],
    completions: Set[Tuple[int, int]],
    today: dt.date,
) -> Tuple[float, int, int, int]:
    if not hw_events or not user_ids:
        return 0.0, 0, 0, 0
    total_pairs = len(hw_events) * len(user_ids)
    done = sum(1 for ev in hw_events for uid in user_ids if (uid, ev.id) in completions)
    overdue = sum(
        1
        for ev in hw_events
        if ev.date and ev.date < today
        for uid in user_ids
        if (uid, ev.id) not in completions
    )
    rate = round(100.0 * done / total_pairs, 1) if total_pairs else 0.0
    return rate, done, total_pairs, overdue


def _subject_attendance(
    slots: List[Tuple[int, str]],
    user_ids: List[int],
    marks: Dict[Tuple[int, int], str],
) -> List[AnalyticsSubjectRow]:
    by_subj: Dict[str, Dict[str, int]] = defaultdict(lambda: {"absent": 0, "sick": 0})
    for eid, subj in slots:
        for uid in user_ids:
            m = marks.get((uid, eid))
            if m == "N":
                by_subj[subj]["absent"] += 1
            elif m == "B":
                by_subj[subj]["sick"] += 1
    rows = [
        AnalyticsSubjectRow(
            subject=subj,
            absent=v["absent"],
            sick=v["sick"],
            homework_total=0,
            homework_done=0,
        )
        for subj, v in by_subj.items()
    ]
    rows.sort(key=lambda r: r.absent + r.sick, reverse=True)
    return rows[:5]


def _subject_homework(
    hw_events: List[Event],
    user_ids: List[int],
    completions: Set[Tuple[int, int]],
) -> List[AnalyticsSubjectRow]:
    by_subj: Dict[str, Dict[str, int]] = defaultdict(lambda: {"total": 0, "done": 0})
    for ev in hw_events:
        subj = _event_subject(ev) or "Без предмета"
        by_subj[subj]["total"] += len(user_ids)
        by_subj[subj]["done"] += sum(1 for uid in user_ids if (uid, ev.id) in completions)
    rows = [
        AnalyticsSubjectRow(
            subject=subj,
            absent=0,
            sick=0,
            homework_total=v["total"],
            homework_done=v["done"],
        )
        for subj, v in by_subj.items()
        if v["total"] > 0
    ]
    rows.sort(key=lambda r: r.homework_total - r.homework_done, reverse=True)
    return rows[:5]


def _weekly_trend(
    session: Session,
    end_date: dt.date,
    users: List[User],
    completions: Set[Tuple[int, int]],
) -> List[AnalyticsWeeklyPoint]:
    user_ids = [u.id for u in users]
    marks_all = _marks_map(session, dt.date(2000, 1, 1), end_date)
    points: List[AnalyticsWeeklyPoint] = []
    monday = _monday_week_start(end_date)
    for _ in range(_TREND_WEEKS):
        w_end = monday + timedelta(days=6)
        slots = _attendance_slots_in_range(session, monday, w_end)
        slot_ids = [s[0] for s in slots]
        att_rate, _, _, _ = _attendance_rate(slot_ids, user_ids, marks_all)
        hw = _homework_events(session, monday, w_end, None)
        hw_rate, _, _, _ = _homework_stats(hw, user_ids, completions, end_date)
        points.append(
            AnalyticsWeeklyPoint(
                week_start=monday,
                attendance_rate=att_rate,
                homework_rate=hw_rate,
            )
        )
        monday -= timedelta(days=7)
    points.reverse()
    return points


def _telegram_stats(session: Session, start: dt.date, end: dt.date) -> AnalyticsTelegramStats:
    events = session.exec(
        select(Event).where(Event.date != None, Event.date >= start, Event.date <= end)  # noqa: E711
    ).all()
    post_attempted = post_sent = reminders_due = reminders_sent = 0
    for ev in events:
        canon = canonical_event_type(ev.type or "")
        if canon in _POST_TYPES and (ev.source or "admin") == "admin":
            post_attempted += 1
            if ev.sent_message_id:
                post_sent += 1
        if canon in ("homework", "exam_control") and not getattr(ev, "reminder_sent", True):
            reminders_due += 1
        elif canon in ("homework", "exam_control") and getattr(ev, "reminder_sent", False):
            reminders_sent += 1
    sent_rate = round(100.0 * post_sent / post_attempted, 1) if post_attempted else 0.0
    reminder_rate = (
        round(100.0 * reminders_sent / (reminders_sent + reminders_due), 1)
        if (reminders_sent + reminders_due)
        else 0.0
    )
    return AnalyticsTelegramStats(
        posts_attempted=post_attempted,
        posts_sent=post_sent,
        posts_sent_rate=sent_rate,
        reminders_sent=reminders_sent,
        reminders_pending=reminders_due,
        reminders_sent_rate=reminder_rate,
    )


@router.get("/admin/analytics", response_model=AnalyticsDashboard)
def get_analytics_dashboard(
    period: str = Query("week", description="week | month | all"),
    week_start: Optional[dt.date] = Query(None, alias="week_start"),
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None, ge=1, le=12),
    semester: Optional[str] = Query(None, description="Фильтр ДЗ по семестру"),
    _admin=Depends(require_admin),
):
    today = dt.date.today()
    start, end, period_key = _period_bounds(period, week_start, year, month)
    semester_norm = normalize_semester_label(semester) if semester else None

    with Session(database.engine) as session:
        users = _student_users(session)
        user_ids = [u.id for u in users]
        marks = _marks_map(session, start, end)
        completions = _completions_set(session)

        slots = _attendance_slots_in_range(session, start, end)
        slot_ids = [s[0] for s in slots]
        att_rate, absent, sick, att_total = _attendance_rate(slot_ids, user_ids, marks)

        hw_events = _homework_events(session, start, end, semester_norm)
        hw_rate, hw_done, hw_total, overdue = _homework_stats(hw_events, user_ids, completions, today)

        all_events = session.exec(
            select(Event).where(Event.date != None, Event.date >= start, Event.date <= end)  # noqa: E711
        ).all()
        lessons = sum(1 for ev in all_events if _is_schedule_event(ev))
        transfers = sum(1 for ev in all_events if canonical_event_type(ev.type or "") == "transfer")

        student_rows: List[AnalyticsStudentRow] = []
        for u in users:
            s_att, s_abs, s_sick, _ = _attendance_rate(slot_ids, [u.id], marks)
            s_hw_rate, s_done, s_total, _ = _homework_stats(hw_events, [u.id], completions, today)
            student_rows.append(
                AnalyticsStudentRow(
                    user_id=u.id,
                    name=_user_display_name(u),
                    attendance_rate=s_att,
                    homework_done=s_done,
                    homework_total=s_total,
                    homework_rate=s_hw_rate,
                    absent=s_abs,
                    sick=s_sick,
                )
            )

        kpi = AnalyticsKpi(
            attendance_rate=att_rate,
            homework_completion_rate=hw_rate,
            overdue_homework=overdue,
            lessons_in_period=lessons,
            absent_marks=absent,
            sick_marks=sick,
            attendance_slots=att_total,
            transfers=transfers,
        )

        trend_end = end if period_key != "all" else today
        weekly = _weekly_trend(session, trend_end, users, completions)

        return AnalyticsDashboard(
            period=period_key,
            period_start=start,
            period_end=end,
            semester_filter=semester_norm,
            kpi=kpi,
            students=student_rows,
            subjects_attendance=_subject_attendance(slots, user_ids, marks),
            subjects_homework=_subject_homework(hw_events, user_ids, completions),
            weekly_trend=weekly,
            telegram=_telegram_stats(session, start, end),
            users=[UserPublic.from_orm(u) for u in users],
        )
