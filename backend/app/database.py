import os
from sqlmodel import SQLModel, create_engine, Session
from typing import Generator

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./dev.db")

# echo=False для менее разговорчивого лога; включи True при отладке
engine = create_engine(DATABASE_URL, echo=False)


def init_db() -> None:
    """
    Создаёт таблицы в БД, если их нет.
    Вызывается при старте приложения.
    """
    SQLModel.metadata.create_all(engine)
    # Попытка добавить колонны, если их нет (безопасно для sqlite и postgres)
    try:
        with engine.connect() as conn:
            dialect = engine.dialect.name
            if dialect == 'postgresql':
                # PostgreSQL поддерживает IF NOT EXISTS
                conn.execute("ALTER TABLE event ADD COLUMN IF NOT EXISTS end_time time")
                conn.execute("ALTER TABLE event ADD COLUMN IF NOT EXISTS room TEXT")
                conn.execute("ALTER TABLE event ADD COLUMN IF NOT EXISTS teacher TEXT")
                conn.execute("ALTER TABLE event ADD COLUMN IF NOT EXISTS series_id TEXT")
            else:
                # SQLite / другие БД: попытка добавить колонны, игнорируем ошибки
                conn.execute("ALTER TABLE event ADD COLUMN end_time TEXT")
                conn.execute("ALTER TABLE event ADD COLUMN room TEXT")
                conn.execute("ALTER TABLE event ADD COLUMN teacher TEXT")
                conn.execute("ALTER TABLE event ADD COLUMN series_id TEXT")
    except Exception:
        # некритично; если схема уже есть или БД не позволяет, игнорируем
        pass


def get_session() -> Generator[Session, None, None]:
    """
    Генератор сессии для зависимостей FastAPI.
    """
    with Session(engine) as session:
        yield session
