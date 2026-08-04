"""Создание SQL-дампа БД и ротация файлов в папке backup."""

from __future__ import annotations

import os
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "./backup"))
BACKUP_KEEP = max(1, int(os.getenv("BACKUP_KEEP", "2")))
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./dev.db")


def _normalize_db_url(url: str) -> str:
    return (url or "").strip().replace("postgresql+psycopg2://", "postgresql://")


def list_backup_files(directory: Path | None = None) -> list[Path]:
    root = directory or BACKUP_DIR
    if not root.exists():
        return []
    files = [p for p in root.glob("backup_*.sql") if p.is_file()]
    return sorted(files, key=lambda p: p.stat().st_mtime)


def rotate_backups(directory: Path | None = None, keep: int | None = None) -> list[str]:
    """Оставляет только `keep` самых новых backup_*.sql, остальные удаляет."""
    root = directory or BACKUP_DIR
    limit = BACKUP_KEEP if keep is None else max(1, int(keep))
    files = list_backup_files(root)
    removed: list[str] = []
    while len(files) > limit:
        oldest = files.pop(0)
        try:
            oldest.unlink(missing_ok=True)
            removed.append(oldest.name)
        except OSError:
            break
    return removed


def _dump_sqlite(db_url: str, dest: Path) -> None:
    raw = db_url[len("sqlite:///") :] if db_url.startswith("sqlite:///") else ""
    if not raw or raw == ":memory:" or db_url.rstrip("/").endswith("sqlite://"):
        raise RuntimeError("In-memory SQLite нельзя бэкапить")
    db_path = Path(raw)
    if not db_path.is_absolute():
        db_path = Path.cwd() / db_path
    if not db_path.exists():
        raise RuntimeError(f"Файл SQLite не найден: {db_path}")

    conn = sqlite3.connect(str(db_path))
    try:
        with dest.open("w", encoding="utf-8") as fh:
            for line in conn.iterdump():
                fh.write(f"{line}\n")
    finally:
        conn.close()


def _dump_postgres(db_url: str, dest: Path) -> None:
    parsed = urlparse(db_url)
    if parsed.scheme not in ("postgresql", "postgres"):
        raise RuntimeError(f"Неподдерживаемый DATABASE_URL: {parsed.scheme}")

    user = unquote(parsed.username or "postgres")
    password = unquote(parsed.password or "")
    host = parsed.hostname or "localhost"
    port = str(parsed.port or 5432)
    dbname = unquote((parsed.path or "/").lstrip("/") or "m15db")

    env = os.environ.copy()
    if password:
        env["PGPASSWORD"] = password

    cmd = [
        "pg_dump",
        "-h",
        host,
        "-p",
        port,
        "-U",
        user,
        "-d",
        dbname,
        "--no-owner",
        "--no-acl",
        "-f",
        str(dest),
    ]
    try:
        subprocess.run(cmd, check=True, env=env, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError(
            "pg_dump не найден в контейнере backend (нужен пакет postgresql-client)"
        ) from exc
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or exc.stdout or str(exc)).strip()
        raise RuntimeError(f"pg_dump завершился с ошибкой: {err}") from exc


def create_backup(*, keep: int | None = None) -> dict:
    """
    Пишет dump в BACKUP_DIR/backup_YYYY-MM-DD_HHMMSS.sql и ротирует до `keep` файлов.
    """
    root = BACKUP_DIR
    root.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    filename = f"backup_{stamp}.sql"
    dest = root / filename
    # если в ту же секунду уже есть файл — добавляем миллисекунды
    if dest.exists():
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S_%f")
        filename = f"backup_{stamp}.sql"
        dest = root / filename

    url = _normalize_db_url(DATABASE_URL)
    try:
        if url.startswith("sqlite"):
            _dump_sqlite(url, dest)
        else:
            _dump_postgres(url, dest)
    except Exception:
        if dest.exists():
            dest.unlink(missing_ok=True)
        raise

    if not dest.exists() or dest.stat().st_size == 0:
        if dest.exists():
            dest.unlink(missing_ok=True)
        raise RuntimeError("Бэкап пустой или не создан")

    removed = rotate_backups(root, keep=keep)
    kept = [p.name for p in list_backup_files(root)]
    return {
        "filename": filename,
        "path": str(dest),
        "size_bytes": dest.stat().st_size,
        "kept": kept,
        "removed": removed,
    }
