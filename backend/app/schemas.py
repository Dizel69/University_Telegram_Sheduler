from pydantic import BaseModel, validator
from typing import Optional
from datetime import date as date_type, time as time_type


class EventCreate(BaseModel):
    type: str
    subject: Optional[str] = None
    title: Optional[str] = None
    body: str
    date: Optional[date_type] = None
    time: Optional[time_type] = None
    end_time: Optional[time_type] = None
    chat_id: Optional[int] = None
    topic_thread_id: Optional[int] = None
    reminder_offset_hours: int = 24

    @validator('date', pre=True)
    def _empty_date_to_none(cls, v):
        # convert empty strings to None so Pydantic doesn't try to coerce them
        if v == "" or v is None:
            return None
        return v

    @validator('time', pre=True)
    def _empty_time_to_none(cls, v):
        if v == "" or v is None:
            return None
        return v


class EventPublic(BaseModel):
    id: int
    type: str
    subject: Optional[str] = None
    title: Optional[str] = None
    body: str
    date: Optional[date_type] = None
    time: Optional[time_type] = None
    end_time: Optional[time_type] = None
    chat_id: Optional[int] = None
    topic_thread_id: Optional[int] = None
    sent_message_id: Optional[int] = None
    source: Optional[str] = None

    class Config:
        orm_mode = True
