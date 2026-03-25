from typing import Optional
import datetime as dt

from sqlmodel import SQLModel, Field
from sqlalchemy import Column, BigInteger


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

    chat_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    topic_thread_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))

    sent_message_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))

    created_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)
    reminder_offset_hours: int = Field(default=24)
    reminder_sent: bool = Field(default=False)
    source: Optional[str] = Field(default="admin")
