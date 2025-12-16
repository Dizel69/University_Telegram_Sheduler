from typing import Optional
import datetime as dt

from sqlmodel import SQLModel, Field
from sqlalchemy import Column, BigInteger


class Event(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    type: str = Field(index=True)
    subject: Optional[str] = Field(default=None)
    title: Optional[str] = Field(default=None)
    body: str

    date: Optional[dt.date] = Field(default=None)
    time: Optional[dt.time] = Field(default=None)
    end_time: Optional[dt.time] = Field(default=None)

    chat_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    topic_thread_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))

    sent_message_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))

    created_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)
    reminder_offset_hours: int = Field(default=24)
    reminder_sent: bool = Field(default=False)
    source: Optional[str] = Field(default="admin")
