import os
from sqlmodel import SQLModel, create_engine, Session
from typing import Generator

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./dev.db")

# echo=False для менее разговорчивого лога; включи True при отладке
engine = create_engine(DATABASE_URL, echo=False)


def init_db() -> None:
    """
    Создаёт таблицы, если их нет.
    Вызывается при старте приложения.
    """
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    """
    Контекстный генератор сессии для зависимостей FastAPI.
    """
    with Session(engine) as session:
        yield session
