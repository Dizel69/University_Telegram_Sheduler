from typing import Optional
import datetime as dt

from sqlmodel import SQLModel, Field
from sqlalchemy import Column, BigInteger, UniqueConstraint


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


class HomeworkCompletion(SQLModel, table=True):
    """Отметка «ДЗ выполнено» для пары пользователь + событие."""

    __tablename__ = "homework_completion"

    __table_args__ = (UniqueConstraint("user_id", "event_id", name="uq_hw_user_event"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="app_user.id", index=True)
    event_id: int = Field(foreign_key="event.id", index=True)
    completed_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)


class AttendanceMark(SQLModel, table=True):
    """Посещаемость: Н — отсутствовал, Б — болеет (на дату и предмет)."""

    __tablename__ = "attendance_mark"

    __table_args__ = (
        UniqueConstraint("user_id", "subject", "attendance_date", name="uq_attendance_user_subject_date"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="app_user.id", index=True)
    subject: str = Field(index=True)
    attendance_date: dt.date = Field(index=True)
    mark: str = Field(index=True)  # N | B
