"""
Идемпотентные добавочные изменения схемы БД после SQLModel.metadata.create_all.

Новые таблицы под модели (например attendance_mark) создаются через create_all
при деплое. Сюда переносим только «дельты» к уже существующим таблицам:
ALTER TABLE ADD COLUMN и т.п., когда продовая база создана более старым кодом.
"""

from sqlalchemy import text


def apply_additive_schema_migrations(engine) -> None:
    """
    Вызывается из init_db() сразу после create_all().
    Любой шаг делается идемпотентно (IF NOT EXISTS или try/except на SQLite).
    """
    try:
        dialect = engine.dialect.name
        if dialect == "postgresql":
            stmts = [
                "ALTER TABLE event ADD COLUMN IF NOT EXISTS end_time time",
                "ALTER TABLE event ADD COLUMN IF NOT EXISTS room TEXT",
                "ALTER TABLE event ADD COLUMN IF NOT EXISTS teacher TEXT",
                "ALTER TABLE event ADD COLUMN IF NOT EXISTS series_id TEXT",
                "ALTER TABLE event ADD COLUMN IF NOT EXISTS lesson_type TEXT",
                "ALTER TABLE event ADD COLUMN IF NOT EXISTS semester TEXT",
            ]
            with engine.begin() as conn:
                for sql in stmts:
                    conn.execute(text(sql))
            return

        # SQLite: ADD COLUMN IF NOT EXISTS — с 3.35+; на старых — тихий сбой по одной колонке
        if dialect == "sqlite":
            alters = [
                "ALTER TABLE event ADD COLUMN end_time TEXT",
                "ALTER TABLE event ADD COLUMN room TEXT",
                "ALTER TABLE event ADD COLUMN teacher TEXT",
                "ALTER TABLE event ADD COLUMN series_id TEXT",
                "ALTER TABLE event ADD COLUMN lesson_type TEXT",
                "ALTER TABLE event ADD COLUMN semester TEXT",
            ]
            for sql in alters:
                try:
                    with engine.begin() as conn:
                        conn.execute(text(sql))
                except Exception:
                    pass
    except Exception:
        pass
