from pydantic import BaseModel
from typing import Optional
from datetime import date, time


class EventCreate(BaseModel):
    type: str
    subject: Optional[str] = None
    title: Optional[str] = None
    body: str
    date: Optional[date] = None
    time: Optional[time] = None
    chat_id: Optional[int] = None
    topic_thread_id: Optional[int] = None
    reminder_offset_hours: Optional[int] = 24


class EventPublic(BaseModel):
    id: int
    type: str
    subject: Optional[str] = None
    title: Optional[str] = None
    body: str
    date: Optional[date] = None
    time: Optional[time] = None
    chat_id: Optional[int] = None
    topic_thread_id: Optional[int] = None
    sent_message_id: Optional[int] = None
    source: Optional[str] = None

    class Config:
        orm_mode = True
