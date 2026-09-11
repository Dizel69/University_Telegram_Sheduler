from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from app.models import Event, HomeworkCompletion, User
from app.security import hash_password


INTERNAL = {"X-INTERNAL-TOKEN": "test-admin-token"}


def _student(session, **kwargs) -> User:
    defaults = dict(
        last_name="Иванов",
        first_name="Иван",
        login="ivan_bot",
        password_hash=hash_password("secret"),
        is_admin=False,
        is_owner=False,
    )
    defaults.update(kwargs)
    user = User(**defaults)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def test_internal_bot_requires_token(backend_client):
    assert backend_client.get("/internal/bot/me", params={"telegram_id": 1}).status_code == 401


def test_bot_login_bind_and_conflict(backend_client, backend_engine):
    with Session(backend_engine) as session:
        user = _student(session)
        other = _student(session, login="petr_bot", last_name="Петров", first_name="Пётр")
        other.telegram_id = 100
        session.add(other)
        session.commit()
        login_name = user.login

    denied = backend_client.post(
        "/internal/bot/login",
        json={"telegram_id": 200, "login": login_name, "password": "wrong"},
        headers=INTERNAL,
    )
    assert denied.status_code == 401

    ok = backend_client.post(
        "/internal/bot/login",
        json={"telegram_id": 200, "login": login_name, "password": "secret"},
        headers=INTERNAL,
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["ok"] is True
    assert body["ask_mirror"] is True
    assert body["user"]["short_name"] == "Иванов И."
    assert body["user"]["telegram_id"] == 200

    clash = backend_client.post(
        "/internal/bot/login",
        json={"telegram_id": 100, "login": login_name, "password": "secret"},
        headers=INTERNAL,
    )
    assert clash.status_code == 409

    rebound = backend_client.post(
        "/internal/bot/login",
        json={"telegram_id": 201, "login": login_name, "password": "secret"},
        headers=INTERNAL,
    )
    assert rebound.status_code == 200
    assert rebound.json()["need_rebind"] is True

    confirmed = backend_client.post(
        "/internal/bot/login",
        json={"telegram_id": 201, "login": login_name, "password": "secret", "confirm_rebind": True},
        headers=INTERNAL,
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["user"]["telegram_id"] == 201

    out = backend_client.post("/internal/bot/logout", json={"telegram_id": 201}, headers=INTERNAL)
    assert out.status_code == 200
    me = backend_client.get("/internal/bot/me", params={"telegram_id": 201}, headers=INTERNAL)
    assert me.json()["user"] is None


def test_bot_homework_done_idempotent(backend_client, backend_engine):
    with Session(backend_engine) as session:
        user = _student(session, telegram_id=300)
        hw = Event(type="homework", subject="Math", body="Read chapter one", date=date.today())
        session.add(hw)
        session.commit()
        session.refresh(hw)
        event_id = hw.id
        tid = user.telegram_id

    listed = backend_client.get("/internal/bot/homework", params={"telegram_id": tid}, headers=INTERNAL)
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["event_id"] == event_id

    first = backend_client.post(
        f"/internal/bot/homework/{event_id}/done",
        json={"telegram_id": tid},
        headers=INTERNAL,
    )
    second = backend_client.post(
        f"/internal/bot/homework/{event_id}/done",
        json={"telegram_id": tid},
        headers=INTERNAL,
    )
    assert first.status_code == 200
    assert second.status_code == 200
    with Session(backend_engine) as session:
        rows = session.exec(select(HomeworkCompletion)).all()
        assert len(rows) == 1

    listed2 = backend_client.get("/internal/bot/homework", params={"telegram_id": tid}, headers=INTERNAL)
    assert listed2.json()["items"] == []


def test_due_personal_homework_not_group_and_skips_completed(backend_client, backend_engine, monkeypatch):
    from app import bot_internal_routes

    class _Frozen:
        @staticmethod
        def now(tz=None):
            return datetime(2026, 9, 10, 12, 0, tzinfo=ZoneInfo("Europe/Moscow"))

        @staticmethod
        def strptime(value, fmt):
            return datetime.strptime(value, fmt)

    monkeypatch.setattr(bot_internal_routes, "now_msk", lambda: _Frozen.now())
    monkeypatch.setattr(bot_internal_routes, "today_msk", lambda: date(2026, 9, 10))

    with Session(backend_engine) as session:
        user = _student(
            session,
            telegram_id=400,
            dm_homework_reminder=True,
            dm_homework_offset_hours=24,
            dm_morning_schedule=True,
        )
        open_hw = Event(
            type="homework",
            subject="Algo",
            body="Solve",
            date=date(2026, 9, 11),
            time=time(12, 0),
        )
        done_hw = Event(
            type="homework",
            subject="Done",
            body="Already",
            date=date(2026, 9, 11),
            time=time(12, 0),
        )
        lesson = Event(
            type="schedule",
            subject="Math",
            body="Lecture",
            date=date(2026, 9, 10),
            time=time(9, 0),
            end_time=time(10, 30),
            room="101",
            teacher="Ada",
        )
        session.add(open_hw)
        session.add(done_hw)
        session.add(lesson)
        session.commit()
        session.refresh(open_hw)
        session.refresh(done_hw)
        session.refresh(user)
        session.add(HomeworkCompletion(user_id=user.id, event_id=done_hw.id))
        session.commit()
        open_id = open_hw.id

    due = backend_client.get("/internal/bot/due-personal", headers=INTERNAL)
    assert due.status_code == 200
    data = due.json()
    assert len(data["morning"]) == 1
    assert data["morning"][0]["telegram_id"] == 400
    assert data["morning"][0]["telegram_id"] > 0
    hw_ids = [x["event_id"] for x in data["homework"]]
    assert hw_ids == [open_id]
    assert all(x["telegram_id"] == 400 for x in data["homework"])


def test_mirror_posts_only_when_flag(backend_client, backend_engine, monkeypatch):
    from app import main

    class _FakeBotResponse:
        status_code = 200
        text = '{"message_id": 777}'

        def json(self):
            return {"message_id": 777}

    class _FakeAsyncClient:
        calls = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json, timeout):
            self.calls.append({"url": url, "json": json, "timeout": timeout})
            return _FakeBotResponse()

    _FakeAsyncClient.calls = []
    monkeypatch.setattr(main.httpx, "AsyncClient", _FakeAsyncClient)

    with Session(backend_engine) as session:
        _student(session, telegram_id=500, dm_mirror_posts=True, login="mirror_on")
        _student(session, telegram_id=501, dm_mirror_posts=False, login="mirror_off")

    response = backend_client.post(
        "/events/send",
        headers={"X-ADMIN-TOKEN": "test-admin-token"},
        json={
            "type": "announcement",
            "subject": "General",
            "body": "Important update",
            "date": "2026-05-21",
            "time": "10:15",
            "chat_id": 222,
        },
    )
    assert response.status_code == 200
    chats = [c["json"]["chat_id"] for c in _FakeAsyncClient.calls]
    assert 222 in chats
    assert 500 in chats
    assert 501 not in chats
    assert chats.count(500) == 1


def test_bot_feedback_goes_to_feedback_chat(backend_client, backend_engine, monkeypatch):
    from app import bot_internal_routes

    class _Resp:
        status_code = 200

        def json(self):
            return {"message_id": 1}

    class _Client:
        calls = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json, timeout):
            self.calls.append({"url": url, "json": json})
            return _Resp()

    _Client.calls = []
    monkeypatch.setattr(bot_internal_routes.httpx, "AsyncClient", _Client)

    with Session(backend_engine) as session:
        _student(session, telegram_id=600, login="fb_user")

    resp = backend_client.post(
        "/internal/bot/feedback",
        json={"telegram_id": 600, "text": "Кнопка ДЗ не обновляется после отметки"},
        headers=INTERNAL,
    )
    assert resp.status_code == 200
    assert _Client.calls[0]["json"]["chat_id"] == 777000
    text = _Client.calls[0]["json"]["text"]
    assert "Telegram" in text
    assert "fb_user" in text
    assert "600" in text
    assert "Иванов" in text
    assert "222" not in text
