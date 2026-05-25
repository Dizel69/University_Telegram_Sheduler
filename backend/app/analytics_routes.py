import datetime as dt
from calendar import monthrange
from collections import defaultdict
from datetime import datetime, timedelta, time as dt_time
from typing import Dict, List, Optional, Set, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
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
    AnalyticsAttendanceOverview,
    AnalyticsDashboard,
    AnalyticsBirthdayItem,
    AnalyticsBreakdownItem,
    AnalyticsHomeworkOverview,
    AnalyticsKpi,
    AnalyticsLoadPoint,
    AnalyticsNamedCount,
    AnalyticsStudentRow,
    AnalyticsSubjectRow,
    AnalyticsSubjectWorkloadRow,
    AnalyticsTelegramStats,
    AnalyticsWeeklyPoint,
    UserPublic,
)
from app.semester_utils import normalize_semester_label
from app.subject_routes import hidden_teacher_names, visible_subject_names_for_period
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


def _normalize_subject(subject: Optional[str]) -> Optional[str]:
    if subject is None:
        return None
    s = str(subject).strip()
    return s if s else None


def _subject_matches_name(name: str, subject_filter: Optional[str]) -> bool:
    if not subject_filter:
        return True
    return name == subject_filter


def _subjects_in_period(session: Session, start: dt.date, end: dt.date) -> List[str]:
    return visible_subject_names_for_period(session, start, end)


def _attendance_slots_in_range(
    session: Session,
    start: dt.date,
    end: dt.date,
    subject_filter: Optional[str] = None,
) -> List[Tuple[int, str]]:
    """(event_id, subject) — one row per lesson slot."""
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
            if _subject_matches_name(subj, subject_filter):
                slots.append((ev.id, subj))
    return slots


def _filter_hw_by_subject(hw_events: List[Event], subject_filter: Optional[str]) -> List[Event]:
    if not subject_filter:
        return hw_events
    return [ev for ev in hw_events if _subject_matches_name(_event_subject(ev) or "Без предмета", subject_filter)]


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


def _percent(part: int, total: int) -> float:
    return round(100.0 * part / total, 1) if total else 0.0


def _breakdown(counter: Dict[str, int]) -> List[AnalyticsBreakdownItem]:
    total = sum(counter.values())
    rows = [
        AnalyticsBreakdownItem(label=label, count=count, percent=_percent(count, total))
        for label, count in counter.items()
        if count > 0
    ]
    rows.sort(key=lambda r: r.count, reverse=True)
    return rows


def _homework_overview(
    hw_events: List[Event],
    user_ids: List[int],
    completions: Set[Tuple[int, int]],
    today: dt.date,
) -> AnalyticsHomeworkOverview:
    rate, done, total_pairs, overdue = _homework_stats(hw_events, user_ids, completions, today)
    return AnalyticsHomeworkOverview(
        total_assignments=len(hw_events),
        total_pairs=total_pairs,
        done=done,
        open=max(total_pairs - done, 0),
        overdue=overdue,
        completion_rate=rate,
    )


def _attendance_overview(
    total: int,
    absent: int,
    sick: int,
    rate: float,
) -> AnalyticsAttendanceOverview:
    return AnalyticsAttendanceOverview(
        present=max(total - absent - sick, 0),
        absent=absent,
        sick=sick,
        total=total,
        attendance_rate=rate,
    )


def _filtered_events_by_subject(events: List[Event], subject_filter: Optional[str]) -> List[Event]:
    if not subject_filter:
        return events
    return [
        ev
        for ev in events
        if _subject_matches_name(_event_subject(ev) or "Без предмета", subject_filter)
    ]


def _subject_workload(
    events: List[Event],
    slots: List[Tuple[int, str]],
    user_ids: List[int],
    marks: Dict[Tuple[int, int], str],
) -> List[AnalyticsSubjectWorkloadRow]:
    by_subject: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {
            "lessons": 0,
            "homework": 0,
            "exam_controls": 0,
            "transfers": 0,
            "absent": 0,
            "sick": 0,
        }
    )
    for ev in events:
        subj = _event_subject(ev) or "Без предмета"
        canon = canonical_event_type(ev.type or "")
        if canon == "schedule":
            by_subject[subj]["lessons"] += 1
        elif canon == "homework":
            by_subject[subj]["homework"] += 1
        elif canon == "exam_control":
            by_subject[subj]["exam_controls"] += 1
        elif canon == "transfer":
            by_subject[subj]["transfers"] += 1

    for event_id, subj in slots:
        for uid in user_ids:
            mark = marks.get((uid, event_id))
            if mark == "N":
                by_subject[subj]["absent"] += 1
            elif mark == "B":
                by_subject[subj]["sick"] += 1

    rows = [
        AnalyticsSubjectWorkloadRow(
            subject=subj,
            lessons=v["lessons"],
            homework=v["homework"],
            exam_controls=v["exam_controls"],
            transfers=v["transfers"],
            absent=v["absent"],
            sick=v["sick"],
        )
        for subj, v in by_subject.items()
        if sum(v.values()) > 0
    ]
    rows.sort(
        key=lambda r: (
            r.lessons + r.homework + r.exam_controls + r.transfers,
            r.absent + r.sick,
        ),
        reverse=True,
    )
    return rows[:10]


def _named_workload(events: List[Event], field: str, hidden_names: Optional[Set[str]] = None) -> List[AnalyticsNamedCount]:
    counter: Dict[str, int] = defaultdict(int)
    hidden = hidden_names or set()
    for ev in events:
        if not _is_schedule_event(ev):
            continue
        value = (getattr(ev, field, None) or "").strip()
        if value and value not in hidden:
            counter[value] += 1
    rows = [AnalyticsNamedCount(name=name, count=count) for name, count in counter.items()]
    rows.sort(key=lambda r: r.count, reverse=True)
    return rows[:8]


def _daily_load(
    events: List[Event],
    start: dt.date,
    end: dt.date,
    period_key: str,
) -> List[AnalyticsLoadPoint]:
    if period_key == "all":
        month_start = dt.date(end.year, end.month, 1)
        buckets = []
        for i in range(11, -1, -1):
            y = month_start.year
            m = month_start.month - i
            while m <= 0:
                m += 12
                y -= 1
            buckets.append(dt.date(y, m, 1))
        data = {d: {"lessons": 0, "homework": 0, "controls": 0, "announcements": 0} for d in buckets}
        for ev in events:
            if not ev.date or ev.date < buckets[0] or ev.date > end:
                continue
            bucket = dt.date(ev.date.year, ev.date.month, 1)
            if bucket not in data:
                continue
            _add_load_point(data[bucket], ev)
    else:
        data = {
            start + timedelta(days=i): {"lessons": 0, "homework": 0, "controls": 0, "announcements": 0}
            for i in range((end - start).days + 1)
        }
        for ev in events:
            if ev.date in data:
                _add_load_point(data[ev.date], ev)

    return [
        AnalyticsLoadPoint(
            date=d,
            lessons=v["lessons"],
            homework=v["homework"],
            controls=v["controls"],
            announcements=v["announcements"],
        )
        for d, v in sorted(data.items())
    ]


def _add_load_point(row: Dict[str, int], ev: Event) -> None:
    canon = canonical_event_type(ev.type or "")
    if canon in ("schedule", "transfer"):
        row["lessons"] += 1
    elif canon == "homework":
        row["homework"] += 1
    elif canon == "exam_control":
        row["controls"] += 1
    elif canon == "announcement":
        row["announcements"] += 1


def _upcoming_birthdays(users: List[User], today: dt.date) -> List[AnalyticsBirthdayItem]:
    out: List[AnalyticsBirthdayItem] = []
    for user in users:
        birth_date = getattr(user, "birth_date", None)
        if not birth_date:
            continue
        birthday = _birthday_on_year_safe(birth_date.month, birth_date.day, today.year)
        if birthday < today:
            birthday = _birthday_on_year_safe(birth_date.month, birth_date.day, today.year + 1)
        days_left = (birthday - today).days
        if days_left > 60:
            continue
        out.append(
            AnalyticsBirthdayItem(
                user_id=user.id,
                name=_user_display_name(user),
                date=birthday,
                days_left=days_left,
            )
        )
    out.sort(key=lambda r: r.days_left)
    return out


def _birthday_on_year_safe(month: int, day: int, year: int) -> dt.date:
    try:
        return dt.date(year, month, day)
    except ValueError:
        return dt.date(year, 2, 28)


def _weekly_trend(
    session: Session,
    end_date: dt.date,
    user_ids: List[int],
    completions: Set[Tuple[int, int]],
    subject_filter: Optional[str],
    semester: Optional[str],
    today: dt.date,
) -> List[AnalyticsWeeklyPoint]:
    marks_all = _marks_map(session, dt.date(2000, 1, 1), end_date)
    points: List[AnalyticsWeeklyPoint] = []
    monday = _monday_week_start(end_date)
    for _ in range(_TREND_WEEKS):
        w_end = monday + timedelta(days=6)
        slots = _attendance_slots_in_range(session, monday, w_end, subject_filter)
        slot_ids = [s[0] for s in slots]
        att_rate, _, _, _ = _attendance_rate(slot_ids, user_ids, marks_all)
        hw = _filter_hw_by_subject(_homework_events(session, monday, w_end, semester), subject_filter)
        hw_rate, _, _, _ = _homework_stats(hw, user_ids, completions, today)
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


def _event_boundary(ev: Event) -> Optional[datetime]:
    if not ev.date:
        return None
    end_t = getattr(ev, "end_time", None) or ev.time or dt_time(23, 59, 59)
    return datetime.combine(ev.date, end_t)


def _is_current_event(ev: Event, now: datetime) -> bool:
    boundary = _event_boundary(ev)
    if not boundary:
        return True
    return boundary >= now


def _remind_at(ev: Event) -> Optional[datetime]:
    if not ev.date:
        return None
    event_time = ev.time if ev.time else dt_time.min
    event_dt = datetime.combine(ev.date, event_time)
    return event_dt - timedelta(hours=getattr(ev, "reminder_offset_hours", 24) or 24)


def _telegram_stats(
    session: Session,
    start: dt.date,
    end: dt.date,
    subject_filter: Optional[str],
) -> AnalyticsTelegramStats:
    now = datetime.utcnow()
    events_period = session.exec(
        select(Event).where(Event.date != None, Event.date >= start, Event.date <= end)  # noqa: E711
    ).all()
    all_events = session.exec(select(Event)).all()

    post_attempted = post_sent = reminders_pending = reminders_sent = 0
    for ev in events_period:
        if not _subject_matches_name(_event_subject(ev) or "Без предмета", subject_filter):
            continue
        canon = canonical_event_type(ev.type or "")
        if canon in _POST_TYPES and (ev.source or "admin") == "admin":
            post_attempted += 1
            if ev.sent_message_id:
                post_sent += 1
        if canon in ("homework", "exam_control"):
            if getattr(ev, "reminder_sent", False):
                reminders_sent += 1
            else:
                reminders_pending += 1

    events_current = posts_waiting = reminders_waiting = reminders_due_now = reminders_scheduled = 0
    for ev in all_events:
        if (ev.source or "") == "manual":
            continue
        if not _subject_matches_name(_event_subject(ev) or "Без предмета", subject_filter):
            continue
        if not _is_current_event(ev, now):
            continue

        events_current += 1
        canon = canonical_event_type(ev.type or "")
        if canon in _POST_TYPES and (ev.source or "admin") == "admin" and not ev.sent_message_id:
            posts_waiting += 1
        if canon in ("homework", "exam_control") and not getattr(ev, "reminder_sent", True):
            reminders_waiting += 1
            remind_at = _remind_at(ev)
            if remind_at and remind_at <= now:
                reminders_due_now += 1
            else:
                reminders_scheduled += 1

    sent_rate = round(100.0 * post_sent / post_attempted, 1) if post_attempted else 0.0
    reminder_rate = (
        round(100.0 * reminders_sent / (reminders_sent + reminders_pending), 1)
        if (reminders_sent + reminders_pending)
        else 0.0
    )
    return AnalyticsTelegramStats(
        posts_attempted=post_attempted,
        posts_sent=post_sent,
        posts_sent_rate=sent_rate,
        posts_pending=max(post_attempted - post_sent, 0),
        reminders_sent=reminders_sent,
        reminders_pending=reminders_pending,
        reminders_sent_rate=reminder_rate,
        reminders_due_now=reminders_due_now,
        reminders_scheduled=reminders_scheduled,
        events_current_count=events_current,
        posts_waiting_now=posts_waiting,
        reminders_waiting_now=reminders_waiting,
    )


@router.get("/admin/analytics", response_model=AnalyticsDashboard)
def get_analytics_dashboard(
    period: str = Query("week", description="week | month | all"),
    week_start: Optional[dt.date] = Query(None, alias="week_start"),
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None, ge=1, le=12),
    semester: Optional[str] = Query(None, description="Фильтр ДЗ по семестру"),
    user_id: Optional[int] = Query(None, description="Фильтр по студенту"),
    subject: Optional[str] = Query(None, description="Фильтр по предмету"),
    _admin=Depends(require_admin),
):
    today = dt.date.today()
    start, end, period_key = _period_bounds(period, week_start, year, month)
    semester_norm = normalize_semester_label(semester) if semester else None
    subject_filter = _normalize_subject(subject)

    with Session(database.engine) as session:
        users = _student_users(session)
        available_subjects = _subjects_in_period(session, start, end)

        if subject_filter and subject_filter not in available_subjects:
            raise HTTPException(status_code=400, detail="Неизвестный предмет для выбранного периода")

        filtered_user_ids = [u.id for u in users]
        if user_id is not None:
            u = session.get(User, user_id)
            if not u:
                raise HTTPException(status_code=404, detail="Пользователь не найден")
            if u.is_owner:
                raise HTTPException(status_code=400, detail="Фильтр по владельцу недоступен")
            filtered_user_ids = [u.id]

        marks = _marks_map(session, start, end)
        completions = _completions_set(session)

        slots = _attendance_slots_in_range(session, start, end, subject_filter)
        slot_ids = [s[0] for s in slots]
        att_rate, absent, sick, att_total = _attendance_rate(slot_ids, filtered_user_ids, marks)

        hw_events = _filter_hw_by_subject(
            _homework_events(session, start, end, semester_norm),
            subject_filter,
        )
        hw_rate, hw_done, hw_total, overdue = _homework_stats(
            hw_events, filtered_user_ids, completions, today
        )

        all_events = session.exec(
            select(Event).where(Event.date != None, Event.date >= start, Event.date <= end)  # noqa: E711
        ).all()
        filtered_events = _filtered_events_by_subject(all_events, subject_filter)
        lessons = sum(1 for ev in filtered_events if _is_schedule_event(ev))
        transfers = sum(1 for ev in filtered_events if canonical_event_type(ev.type or "") == "transfer")

        event_type_counts: Dict[str, int] = defaultdict(int)
        source_counts: Dict[str, int] = defaultdict(int)
        lesson_type_counts: Dict[str, int] = defaultdict(int)
        for ev in filtered_events:
            canon = canonical_event_type(ev.type or "")
            event_type_counts[canon] += 1
            source_counts[getattr(ev, "source", None) or "admin"] += 1
            lesson_type = (getattr(ev, "lesson_type", None) or "").strip()
            if lesson_type:
                lesson_type_counts[lesson_type] += 1

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
        weekly = _weekly_trend(
            session,
            trend_end,
            filtered_user_ids,
            completions,
            subject_filter,
            semester_norm,
            today,
        )

        return AnalyticsDashboard(
            period=period_key,
            period_start=start,
            period_end=end,
            semester_filter=semester_norm,
            user_filter=user_id,
            subject_filter=subject_filter,
            available_subjects=available_subjects,
            kpi=kpi,
            students=student_rows,
            subjects_attendance=_subject_attendance(slots, filtered_user_ids, marks),
            subjects_homework=_subject_homework(hw_events, filtered_user_ids, completions),
            weekly_trend=weekly,
            telegram=_telegram_stats(session, start, end, subject_filter),
            users=[UserPublic.from_orm(u) for u in users],
            event_type_breakdown=_breakdown(event_type_counts),
            source_breakdown=_breakdown(source_counts),
            lesson_type_breakdown=_breakdown(lesson_type_counts),
            subject_workload=_subject_workload(filtered_events, slots, filtered_user_ids, marks),
            teacher_workload=_named_workload(filtered_events, "teacher", hidden_teacher_names(session)),
            room_workload=_named_workload(filtered_events, "room"),
            daily_load=_daily_load(filtered_events, start, end, period_key),
            homework_overview=_homework_overview(hw_events, filtered_user_ids, completions, today),
            attendance_overview=_attendance_overview(att_total, absent, sick, att_rate),
            birthdays_upcoming=_upcoming_birthdays(users, today),
        )
