from pydantic import BaseModel, validator
from typing import Optional
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
