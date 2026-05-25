import os
from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy import text
from typing import Generator

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./dev.db")

# echo=False для менее разговорчивого лога; включи True при отладке
engine = create_engine(DATABASE_URL, echo=False)

# Учётная запись по умолчанию (создаётся при старте, если задан пароль в .env)
ADMIN_SEED_LOGIN = "admin"
MAX_APP_USERS = 8


def init_db() -> None:
    """
    Создаёт таблицы в БД, если их нет.
    Вызывается при старте приложения.
    """
    # Регистрация моделей для metadata
    from app.models import AttendanceMark, Event, HomeworkCompletion, SubjectSetting, TeacherSetting, User  # noqa: F401

    SQLModel.metadata.create_all(engine)
    seed_owner_if_needed()

    from app.schema_migrations import apply_additive_schema_migrations

    apply_additive_schema_migrations(engine)

    # Устаревшие метки семестра («2», «2 семестр») → канонические подписи календаря
    try:
        from app.semester_utils import legacy_semester_migrations

        with engine.begin() as conn:
            for old, new in legacy_semester_migrations():
                conn.execute(
                    text("UPDATE event SET semester = :new WHERE TRIM(semester) = :old"),
                    {"new": new, "old": old},
                )
    except Exception:
        pass


def seed_owner_if_needed() -> None:
    """
    Создаёт учётную запись владельца с логином «admin», если её ещё нет и задан пароль в .env.

    Пароль берётся из ADMIN_PASSWORD; если нет — из OWNER_PASSWORD; если нет — из ADMIN_TOKEN
    (как у старого входа по секрету), чтобы можно было использовать один уже настроенный секрет.

    Пользовательские профили и связанные данные хранятся в БД (app_user, homework_completion, attendance_mark).
    """
    from sqlmodel import select

    from app.models import User
    from app.security import hash_password

    pwd = (
        (os.getenv("ADMIN_PASSWORD") or "").strip()
        or (os.getenv("OWNER_PASSWORD") or "").strip()
        or (os.getenv("ADMIN_TOKEN") or "").strip()
    )
    if not pwd:
        return

    try:
        with Session(engine) as session:
            if session.exec(select(User).where(User.login == ADMIN_SEED_LOGIN)).first():
                return
            if len(session.exec(select(User)).all()) >= MAX_APP_USERS:
                return
            existing_owner = session.exec(select(User).where(User.is_owner == True)).first()
            assign_owner = existing_owner is None

            u = User(
                last_name="admin",
                first_name="admin",
                middle_name=None,
                birth_date=None,
                login=ADMIN_SEED_LOGIN,
                password_hash=hash_password(pwd),
                is_admin=True,
                is_owner=assign_owner,
            )
            session.add(u)
            session.commit()
    except Exception:
        pass


def get_session() -> Generator[Session, None, None]:
    """
    Генератор сессии для зависимостей FastAPI.
    """
    with Session(engine) as session:
        yield session
