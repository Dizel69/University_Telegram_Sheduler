"""
Идемпотентные добавочные изменения схемы БД после SQLModel.metadata.create_all.

Новые таблицы под модели (например attendance_mark) создаются через create_all
при деплое. Сюда переносим только «дельты» к уже существующим таблицам:
ALTER TABLE ADD COLUMN и т.п., когда продовая база создана более старым кодом.
"""

from sqlalchemy import inspect, text


def _attendance_has_column(engine, column: str) -> bool:
    try:
        cols = inspect(engine).get_columns("attendance_mark")
        return any(c["name"] == column for c in cols)
    except Exception:
        return False


def _attendance_table_exists(engine) -> bool:
    return inspect(engine).has_table("attendance_mark")


def migrate_attendance_mark_schema(engine) -> None:
    """
    Старая схема: (user_id, subject, attendance_date).
    Новая: (user_id, event_id) — отдельная отметка на каждую пару в календаре.
    """
    if not _attendance_table_exists(engine):
        return
    if not _attendance_has_column(engine, "subject"):
        return

    dialect = engine.dialect.name
    try:
        with engine.begin() as conn:
            if dialect == "postgresql":
                conn.execute(text("ALTER TABLE attendance_mark ADD COLUMN IF NOT EXISTS event_id INTEGER"))
                conn.execute(
                    text(
                        """
                        UPDATE attendance_mark am
                        SET event_id = sub.id
                        FROM (
                            SELECT am2.ctid AS mark_ctid,
                                   (
                                       SELECT e.id FROM event e
                                       WHERE e.date = am2.attendance_date
                                         AND trim(coalesce(e.subject, e.title, '')) = trim(am2.subject)
                                       ORDER BY e.time NULLS LAST, e.id
                                       LIMIT 1
                                   ) AS id
                            FROM attendance_mark am2
                            WHERE am2.event_id IS NULL
                        ) sub
                        WHERE am.ctid = sub.mark_ctid AND sub.id IS NOT NULL
                        """
                    )
                )
                conn.execute(text("DELETE FROM attendance_mark WHERE event_id IS NULL"))
                conn.execute(
                    text("ALTER TABLE attendance_mark DROP CONSTRAINT IF EXISTS uq_attendance_user_subject_date")
                )
                try:
                    conn.execute(text("ALTER TABLE attendance_mark DROP COLUMN subject"))
                    conn.execute(text("ALTER TABLE attendance_mark DROP COLUMN attendance_date"))
                except Exception:
                    pass
                conn.execute(
                    text(
                        """
                        DO $$ BEGIN
                            ALTER TABLE attendance_mark
                            ADD CONSTRAINT uq_attendance_user_event UNIQUE (user_id, event_id);
                        EXCEPTION WHEN duplicate_object THEN NULL;
                        END $$
                        """
                    )
                )
            elif dialect == "sqlite":
                conn.execute(text("ALTER TABLE attendance_mark ADD COLUMN event_id INTEGER"))
                conn.execute(
                    text(
                        """
                        UPDATE attendance_mark
                        SET event_id = (
                            SELECT e.id FROM event e
                            WHERE e.date = attendance_mark.attendance_date
                              AND trim(coalesce(e.subject, e.title, '')) = trim(attendance_mark.subject)
                            ORDER BY e.time IS NULL, e.time, e.id
                            LIMIT 1
                        )
                        WHERE event_id IS NULL
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        CREATE TABLE IF NOT EXISTS attendance_mark_new (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER NOT NULL,
                            event_id INTEGER NOT NULL,
                            mark VARCHAR NOT NULL,
                            UNIQUE (user_id, event_id)
                        )
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        INSERT OR IGNORE INTO attendance_mark_new (id, user_id, event_id, mark)
                        SELECT id, user_id, event_id, mark FROM attendance_mark
                        WHERE event_id IS NOT NULL
                        """
                    )
                )
                conn.execute(text("DROP TABLE attendance_mark"))
                conn.execute(text("ALTER TABLE attendance_mark_new RENAME TO attendance_mark"))
    except Exception:
        pass


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
                "ALTER TABLE event ADD COLUMN IF NOT EXISTS photo_urls JSONB",
                "ALTER TABLE event ADD COLUMN IF NOT EXISTS attachments JSONB",
            ]
            with engine.begin() as conn:
                for sql in stmts:
                    conn.execute(text(sql))

        # SQLite: ADD COLUMN IF NOT EXISTS — с 3.35+; на старых — тихий сбой по одной колонке
        if dialect == "sqlite":
            alters = [
                "ALTER TABLE event ADD COLUMN end_time TEXT",
                "ALTER TABLE event ADD COLUMN room TEXT",
                "ALTER TABLE event ADD COLUMN teacher TEXT",
                "ALTER TABLE event ADD COLUMN series_id TEXT",
                "ALTER TABLE event ADD COLUMN lesson_type TEXT",
                "ALTER TABLE event ADD COLUMN semester TEXT",
                "ALTER TABLE event ADD COLUMN photo_urls TEXT",
                "ALTER TABLE event ADD COLUMN attachments TEXT",
            ]
            for sql in alters:
                try:
                    with engine.begin() as conn:
                        conn.execute(text(sql))
                except Exception:
                    pass

        migrate_attendance_mark_schema(engine)
    except Exception:
        pass
