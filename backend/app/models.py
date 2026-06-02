from typing import Optional
import datetime as dt

from sqlmodel import SQLModel, Field
from sqlalchemy import Column, BigInteger, UniqueConstraint, JSON


class Event(SQLModel, table=True):
    """Модель события для расписания, домашних заданий и объявлений."""
    id: Optional[int] = Field(default=None, primary_key=True)

    type: str = Field(index=True)
    subject: Optional[str] = Field(default=None)  # Предмет
    title: Optional[str] = Field(default=None)    # Заголовок
    body: str                                       # Текст сообщения

    date: Optional[dt.date] = Field(default=None) # Дата
    time: Optional[dt.time] = Field(default=None) # Время начала
    end_time: Optional[dt.time] = Field(default=None)  # Время окончания
    # Опциональная аудитория/кабинет для событий расписания
    room: Optional[str] = Field(default=None)
    # Опциональное имя преподавателя
    teacher: Optional[str] = Field(default=None)
    # Опциональный ID серии для повторяющихся событий
    series_id: Optional[str] = Field(default=None)
    # Тип урока (лекция или практика)
    lesson_type: Optional[str] = Field(default=None)
    # Семестр (произвольная метка, как в настройках «Текущий семестр») — для домашних заданий
    semester: Optional[str] = Field(default=None)
    photo_urls: Optional[list[str]] = Field(default=None, sa_column=Column(JSON, nullable=True))
    attachments: Optional[list[dict]] = Field(default=None, sa_column=Column(JSON, nullable=True))

    chat_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    topic_thread_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))

    sent_message_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))

    created_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)
    reminder_offset_hours: int = Field(default=24)
    reminder_sent: bool = Field(default=False)
    source: Optional[str] = Field(default="admin")


class User(SQLModel, table=True):
    """Учётная запись пользователя приложения (до 8 человек)."""

    __tablename__ = "app_user"

    id: Optional[int] = Field(default=None, primary_key=True)
    last_name: str = Field(index=True)
    first_name: str
    middle_name: Optional[str] = Field(default=None)
    birth_date: Optional[dt.date] = Field(default=None)
    login: str = Field(unique=True, index=True)
    password_hash: str
    is_admin: bool = Field(default=False)
    is_owner: bool = Field(default=False)
    last_seen_at: Optional[dt.datetime] = Field(default=None, index=True)


class HomeworkCompletion(SQLModel, table=True):
    """Отметка «ДЗ выполнено» для пары пользователь + событие."""

    __tablename__ = "homework_completion"

    __table_args__ = (UniqueConstraint("user_id", "event_id", name="uq_hw_user_event"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="app_user.id", index=True)
    event_id: int = Field(foreign_key="event.id", index=True)
    completed_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)


class AttendanceMark(SQLModel, table=True):
    """Посещаемость по конкретной паре (событию): Н — отсутствовал, Б — болеет."""

    __tablename__ = "attendance_mark"

    __table_args__ = (UniqueConstraint("user_id", "event_id", name="uq_attendance_user_event"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="app_user.id", index=True)
    event_id: int = Field(foreign_key="event.id", index=True)
    mark: str = Field(index=True)  # N | B


class SubjectSetting(SQLModel, table=True):
    """Настройки отображения предмета, найденного в событиях календаря."""

    __tablename__ = "subject_setting"

    __table_args__ = (UniqueConstraint("subject_key", name="uq_subject_setting_key"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    subject_key: str = Field(index=True)
    display_name: str
    is_visible: bool = Field(default=True)
    updated_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)


class TeacherSetting(SQLModel, table=True):
    """Настройки отображения преподавателя, найденного в событиях календаря."""

    __tablename__ = "teacher_setting"

    __table_args__ = (UniqueConstraint("teacher_key", name="uq_teacher_setting_key"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    teacher_key: str = Field(index=True)
    display_name: str
    is_visible: bool = Field(default=True)
    updated_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)


class CalendarDayRangeHighlight(SQLModel, table=True):
    """Цветовая заливка диапазона дней в публичном календаре (общая для всех клиентов)."""

    __tablename__ = "calendar_day_range_highlight"

    id: Optional[int] = Field(default=None, primary_key=True)
    start_date: dt.date = Field(index=True)
    end_date: dt.date = Field(index=True)
    color: str = Field(max_length=16)
    stitch: bool = Field(default=True)
    sort_order: int = Field(default=0, index=True)
