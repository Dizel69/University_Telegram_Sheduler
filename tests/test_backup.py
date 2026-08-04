import time
from pathlib import Path

from app.backup import create_backup, list_backup_files, rotate_backups


def test_rotate_backups_keeps_only_two(tmp_path: Path):
    for name in ("backup_2026-01-01_010000.sql", "backup_2026-01-02_010000.sql", "backup_2026-01-03_010000.sql"):
        p = tmp_path / name
        p.write_text("-- dump\n", encoding="utf-8")
        time.sleep(0.01)

    removed = rotate_backups(tmp_path, keep=2)
    kept = [p.name for p in list_backup_files(tmp_path)]

    assert len(kept) == 2
    assert "backup_2026-01-01_010000.sql" in removed
    assert "backup_2026-01-01_010000.sql" not in kept
    assert "backup_2026-01-02_010000.sql" in kept
    assert "backup_2026-01-03_010000.sql" in kept


def test_create_backup_sqlite_and_rotate(tmp_path: Path, monkeypatch):
    import sqlite3

    db_path = tmp_path / "app.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE demo (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO demo(name) VALUES ('hello')")
    conn.commit()
    conn.close()

    backup_dir = tmp_path / "backup"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("BACKUP_DIR", str(backup_dir))
    monkeypatch.setenv("BACKUP_KEEP", "2")

    # reload module constants from env
    import importlib
    import app.backup as backup_mod

    importlib.reload(backup_mod)

    first = backup_mod.create_backup()
    time.sleep(0.05)
    second = backup_mod.create_backup()
    time.sleep(0.05)
    third = backup_mod.create_backup()

    files = backup_mod.list_backup_files()
    assert len(files) == 2
    assert first["filename"] not in [p.name for p in files]
    assert second["filename"] in [p.name for p in files]
    assert third["filename"] in [p.name for p in files]
    content = files[-1].read_text(encoding="utf-8")
    assert "CREATE TABLE demo" in content
    assert "hello" in content
