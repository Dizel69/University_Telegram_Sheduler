import os
import sys
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine


ROOT = Path(__file__).resolve().parents[1]
for service_dir in ("backend", "bot", "worker"):
    path = str(ROOT / service_dir)
    if path not in sys.path:
        sys.path.insert(0, path)


os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("BOT_TOKEN", "123456:test-token")
os.environ.setdefault("DEFAULT_CHAT_ID", "100500")
os.environ.setdefault("BOT_SERVICE_URL", "http://bot-service.test")
os.environ.setdefault("BACKEND_URL", "http://backend.test")


@pytest.fixture()
def backend_engine(monkeypatch):
    from app import account_routes, calendar_highlight_routes, crud, database, deps, main, models, teacher_routes  # noqa: F401
    from app.models import CalendarDayRangeHighlight  # noqa: F401 — register table in metadata

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    for module in (database, crud, deps, account_routes, calendar_highlight_routes, main, teacher_routes):
        monkeypatch.setattr(module, "engine", engine, raising=False)

    main.app.dependency_overrides.clear()
    yield engine
    main.app.dependency_overrides.clear()
    SQLModel.metadata.drop_all(engine)


@pytest.fixture()
def db_session(backend_engine):
    with Session(backend_engine) as session:
        yield session


@pytest.fixture()
def backend_client(backend_engine):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        yield client
