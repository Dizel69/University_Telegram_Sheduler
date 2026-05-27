from pydantic import BaseModel, validator
from typing import List, Optional
from datetime import date as date_type, time as time_type

from .semester_utils import normalize_semester_label


class EventCreate(BaseModel):
    """Схема для создания события."""
    type: str          # Тип события (schedule, homework, exam_control, announcement, transfer)
    subject: Optional[str] = None  # Предмет
    title: Optional[str] = None    # Заголовок
    body: str          # Основной текст
    date: Optional[date_type] = None  # Дата события
    time: Optional[time_type] = None  # Время начала
    end_time: Optional[time_type] = None  # Время окончания
    room: Optional[str] = None     # Аудитория
    teacher: Optional[str] = None  # Преподаватель
    series_id: Optional[str] = None  # ID серии для повторяющихся событий
    lesson_type: Optional[str] = None  # Тип урока (лекция/практика)
    semester: Optional[str] = None  # Семестр (в основном для homework)
    photo_urls: Optional[List[str]] = None
    attachments: Optional[List[dict]] = None
    chat_id: Optional[int] = None  # ID чата Telegram
    topic_thread_id: Optional[int] = None  # ID темы/потока
    reminder_offset_hours: int = 24  # Смещение напоминания в часах

    @validator('date', pre=True)
    def _empty_date_to_none(cls, v):
        # Преобразование пустых строк в None
        if v == "" or v is None:
            return None
        return v

    @validator('time', pre=True)
    def _empty_time_to_none(cls, v):
        # Преобразование пустого времени в None
        if v == "" or v is None:
            return None
        return v

    @validator('end_time', pre=True)
    def _empty_end_time_to_none(cls, v):
        if v == "" or v is None:
            return None
        return v

    @validator('semester', pre=True)
    def _normalize_semester(cls, v):
        if v is None or v == "":
            return None
        return normalize_semester_label(v)


class EventPublic(BaseModel):
    """Схема для публичного представления события."""
    id: int
    type: str
    subject: Optional[str] = None
    title: Optional[str] = None
    body: str
    date: Optional[date_type] = None
    time: Optional[time_type] = None
    end_time: Optional[time_type] = None
    room: Optional[str] = None
    teacher: Optional[str] = None
    series_id: Optional[str] = None
    lesson_type: Optional[str] = None
    semester: Optional[str] = None
    photo_urls: Optional[List[str]] = None
    attachments: Optional[List[dict]] = None
    chat_id: Optional[int] = None
    topic_thread_id: Optional[int] = None
    sent_message_id: Optional[int] = None
    source: Optional[str] = None
    reminder_offset_hours: int = 24

    @validator('semester', pre=True)
    def _normalize_semester_public(cls, v):
        return normalize_semester_label(v)

    class Config:
        orm_mode = True


class UserPublic(BaseModel):
    id: int
    last_name: str
    first_name: str
    middle_name: Optional[str] = None
    birth_date: Optional[date_type] = None
    login: str
    is_admin: bool
    is_owner: bool

    class Config:
        orm_mode = True


class LoginRequest(BaseModel):
    login: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic


class UserCreate(BaseModel):
    last_name: str
    first_name: str
    middle_name: Optional[str] = None
    birth_date: Optional[date_type] = None
    login: str
    password: str
    is_admin: bool = False


class UserUpdate(BaseModel):
    last_name: Optional[str] = None
    first_name: Optional[str] = None
    middle_name: Optional[str] = None
    birth_date: Optional[date_type] = None
    password: Optional[str] = None
    is_admin: Optional[bool] = None


class AttendanceLessonSlot(BaseModel):
    """Одна пара в сетке (отдельное событие расписания)."""

    event_id: int
    subject: str
    label: str  # подпись столбца, напр. «Математика (09:00)»


class AttendanceMarkPublic(BaseModel):
    user_id: int
    event_id: int
    mark: str  # N | B


class AttendanceDayColumn(BaseModel):
    """Один день недели: столбцы — отдельные пары."""

    date: date_type
    slots: List[AttendanceLessonSlot]


class AttendanceBoard(BaseModel):
    week_start: date_type
    week_end: date_type
    users: List[UserPublic]
    days: List[AttendanceDayColumn]
    marks: List[AttendanceMarkPublic]


class AttendanceMarkSet(BaseModel):
    user_id: int
    event_id: int
    mark: Optional[str] = None  # N, B или null — снять отметку

    @validator("mark")
    def _validate_mark(cls, v):
        if v is None or v == "":
            return None
        m = str(v).strip().upper()
        if m in ("Н", "N"):
            return "N"
        if m in ("Б", "B"):
            return "B"
        raise ValueError("mark must be N, B or empty")


class AnalyticsKpi(BaseModel):
    attendance_rate: float
    homework_completion_rate: float
    overdue_homework: int
    lessons_in_period: int
    absent_marks: int
    sick_marks: int
    attendance_slots: int
    transfers: int


class AnalyticsStudentRow(BaseModel):
    user_id: int
    name: str
    attendance_rate: float
    homework_done: int
    homework_total: int
    homework_rate: float
    absent: int
    sick: int


class AnalyticsSubjectRow(BaseModel):
    subject: str
    absent: int
    sick: int
    homework_total: int
    homework_done: int


class AnalyticsWeeklyPoint(BaseModel):
    week_start: date_type
    attendance_rate: float
    homework_rate: float


class AnalyticsTelegramStats(BaseModel):
    posts_attempted: int
    posts_sent: int
    posts_sent_rate: float
    reminders_sent: int
    reminders_pending: int
    reminders_sent_rate: float
    posts_pending: int = 0
    reminders_due_now: int = 0
    reminders_scheduled: int = 0
    events_current_count: int = 0
    posts_waiting_now: int = 0
    reminders_waiting_now: int = 0


class AnalyticsBreakdownItem(BaseModel):
    label: str
    count: int
    percent: float


class AnalyticsSubjectWorkloadRow(BaseModel):
    subject: str
    lessons: int
    homework: int
    exam_controls: int
    transfers: int
    absent: int
    sick: int


class AnalyticsNamedCount(BaseModel):
    name: str
    count: int


class AnalyticsLoadPoint(BaseModel):
    date: date_type
    lessons: int
    homework: int
    controls: int
    announcements: int


class AnalyticsHomeworkOverview(BaseModel):
    total_assignments: int
    total_pairs: int
    done: int
    open: int
    overdue: int
    completion_rate: float


class AnalyticsAttendanceOverview(BaseModel):
    present: int
    absent: int
    sick: int
    total: int
    attendance_rate: float


class AnalyticsBirthdayItem(BaseModel):
    user_id: int
    name: str
    date: date_type
    days_left: int


class AnalyticsDashboard(BaseModel):
    period: str
    period_start: date_type
    period_end: date_type
    semester_filter: Optional[str] = None
    user_filter: Optional[int] = None
    subject_filter: Optional[str] = None
    available_subjects: List[str] = []
    kpi: AnalyticsKpi
    students: List[AnalyticsStudentRow]
    subjects_attendance: List[AnalyticsSubjectRow]
    subjects_homework: List[AnalyticsSubjectRow]
    weekly_trend: List[AnalyticsWeeklyPoint]
    telegram: AnalyticsTelegramStats
    users: List[UserPublic]
    event_type_breakdown: List[AnalyticsBreakdownItem]
    source_breakdown: List[AnalyticsBreakdownItem]
    lesson_type_breakdown: List[AnalyticsBreakdownItem]
    subject_workload: List[AnalyticsSubjectWorkloadRow]
    teacher_workload: List[AnalyticsNamedCount]
    room_workload: List[AnalyticsNamedCount]
    daily_load: List[AnalyticsLoadPoint]
    homework_overview: AnalyticsHomeworkOverview
    attendance_overview: AnalyticsAttendanceOverview
    birthdays_upcoming: List[AnalyticsBirthdayItem]


class SubjectAdminRow(BaseModel):
    subject_key: str
    display_name: str
    is_visible: bool
    raw_names: List[str]
    events_total: int
    schedule_count: int
    homework_count: int
    exam_control_count: int
    transfer_count: int
    announcement_count: int


class SubjectAdminList(BaseModel):
    subjects: List[SubjectAdminRow]


class SubjectAdminUpdate(BaseModel):
    subject_key: str
    display_name: Optional[str] = None
    is_visible: Optional[bool] = None
    rename_events: bool = True


class SubjectAdminUpdateResult(BaseModel):
    ok: bool
    subject: SubjectAdminRow
    updated_events: int


class SubjectVariantUpdate(BaseModel):
    subject_key: str
    raw_name: str
    display_name: str


class SubjectVariantUpdateResult(BaseModel):
    ok: bool
    subject: SubjectAdminRow
    updated_events: int


class TeacherAdminRow(BaseModel):
    teacher_key: str
    display_name: str
    is_visible: bool
    raw_names: List[str]
    events_total: int
    schedule_count: int
    exam_control_count: int
    transfer_count: int
    subjects: List[str]


class TeacherAdminList(BaseModel):
    teachers: List[TeacherAdminRow]


class TeacherAdminUpdate(BaseModel):
    teacher_key: str
    display_name: Optional[str] = None
    is_visible: Optional[bool] = None
    rename_events: bool = True


class TeacherAdminUpdateResult(BaseModel):
    ok: bool
    teacher: TeacherAdminRow
    updated_events: int


class TeacherVariantUpdate(BaseModel):
    teacher_key: str
    raw_name: str
    display_name: str


class TeacherVariantUpdateResult(BaseModel):
    ok: bool
    teacher: TeacherAdminRow
    updated_events: int
