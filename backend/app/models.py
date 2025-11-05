# backend/app/models.py
from typing import Optional
from datetime import date, time, datetime

from sqlmodel import SQLModel, Field, Column
from sqlalchemy import Date, Time, DateTime, Integer, Boolean, String, Text


class Event(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True, sa_column=Column(Integer, autoincrement=True))

    # 'schedule' | 'homework' | 'announcement'
    type: str = Field(index=True, sa_column=Column(String(128)))
    subject: Optional[str] = Field(default=None, sa_column=Column(String(256)))
    title: Optional[str] = Field(default=None, sa_column=Column(String(256)))
    body: str = Field(sa_column=Column(Text), default="")

    # Дата/время события (для календаря)
    date: Optional[date] = Field(default=None, sa_column=Column(Date))
    time: Optional[time] = Field(default=None, sa_column=Column(Time))

    # Telegram
    chat_id: Optional[int] = Field(default=None, sa_column=Column(Integer))
    topic_thread_id: Optional[int] = Field(default=None, sa_column=Column(Integer))  # message_thread_id (forum topic)

    # После отправки ботом
    sent_message_id: Optional[int] = Field(default=None, sa_column=Column(Integer))

    # Метаданные
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime))
    reminder_offset_hours: int = Field(default=24, sa_column=Column(Integer))
    reminder_sent: bool = Field(default=False, sa_column=Column(Boolean))
    source: Optional[str] = Field(default="admin", sa_column=Column(String(64)))  # 'admin' или 'dekanat' (импорт)
