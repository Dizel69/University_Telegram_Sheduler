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


def _freeze_msk(monkeypatch, moment: datetime) -> None:
    from app import bot_internal_routes

    monkeypatch.setattr(bot_internal_routes, "now_msk", lambda: moment)
    monkeypatch.setattr(bot_internal_routes, "today_msk", lambda: moment.date())


def _msk(year, month, day, hour, minute) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=ZoneInfo("Europe/Moscow"))


def test_lesson_slots_keep_first_pair_and_select_all_is_snapshot(backend_client, backend_engine, monkeypatch):
    _freeze_msk(monkeypatch, _msk(2026, 9, 21, 9, 0))
    monday = date(2026, 9, 21)
    assert monday.weekday() == 0

    with Session(backend_engine) as session:
        user = _student(session, telegram_id=710, login="slots_user")
        rows = [
            Event(type="schedule", subject="Неклассические логики", body="лекция", date=monday, time=time(14, 0), room="200"),
            Event(type="schedule", subject="Неклассические логики", body="вторая", date=monday, time=time(15, 55), room="201"),
            Event(type="exam_control", subject="Неклассические логики", body="экзамен", date=monday, time=time(9, 0), room="ЭКЗ"),
            Event(type="transfer", subject="Неклассические логики", body="перенос", date=monday, time=time(8, 0), room="ПЕР"),
            Event(
                type="schedule",
                subject="Методы искусственного интеллекта",
                body="подключение https://meetings.tversu.ru/j/1",
                date=date(2026, 9, 22),
                time=time(15, 55),
            ),
            Event(
                type="schedule",
                subject="Методы искусственного интеллекта",
                body="третья",
                date=date(2026, 9, 22),
                time=time(17, 45),
                room="10",
            ),
            Event(type="schedule", subject="МОЗИ", body="1", date=date(2026, 9, 26), time=time(10, 15), room="12"),
            Event(type="schedule", subject="МОЗИ", body="2", date=date(2026, 9, 26), time=time(12, 10), room="13"),
            Event(type="schedule", subject="МОЗИ", body="3", date=date(2026, 9, 26), time=time(14, 0), room="14"),
            Event(
                type="schedule",
                subject="Вебинар",
                body="online",
                date=date(2026, 9, 23),
                time=time(12, 0),
                room="https://meetings.tversu.ru/j/2",
            ),
        ]
        for row in rows:
            session.add(row)
        session.commit()
        tid = user.telegram_id

    me = backend_client.get("/internal/bot/me", params={"telegram_id": tid}, headers=INTERNAL)
    assert me.status_code == 200
    payload = me.json()["user"]
    assert payload["dm_lesson_soon"] is False
    assert payload["dm_lesson_offset_minutes"] == 5
    assert payload["dm_transfer_eve"] is False
    assert payload["dm_lesson_all"] is False
    slots = {row["key"]: row for row in payload["lesson_slots"]}
    assert set(slots) == {
        "неклассические логики|0|14:00",
        "методы искусственного интеллекта|1|15:55",
        "вебинар|2|12:00",
        "мози|5|10:15",
    }
    assert slots["неклассические логики|0|14:00"]["place_label"] == "ауд 200"
    assert slots["неклассические логики|0|14:00"]["weekday_label"] == "Пн"
    ai = slots["методы искусственного интеллекта|1|15:55"]
    assert ai["place_label"] == "ссылка"
    assert ai["link"] == "https://meetings.tversu.ru/j/1"
    assert "17:45" not in ai["time"]
    webinar = slots["вебинар|2|12:00"]
    assert webinar["place_label"] == "ссылка"
    assert webinar["room"] is None
    assert "ауд" not in webinar["place_label"]
    assert slots["мози|5|10:15"]["time"] == "10:15"
    assert not any(row["time"] in {"12:10", "17:45", "09:00"} for row in slots.values())
    assert not any(row["room"] in {"201", "10", "13", "14", "ЭКЗ", "ПЕР"} for row in slots.values())

    selected = backend_client.patch(
        "/internal/bot/settings",
        json={"telegram_id": tid, "dm_lesson_all": True},
        headers=INTERNAL,
    )
    assert selected.status_code == 200
    chosen = selected.json()["user"]
    assert chosen["dm_lesson_all"] is True
    assert set(chosen["dm_lesson_slot_keys"]) == set(slots)

    quiet = backend_client.get("/internal/bot/due-personal", headers=INTERNAL).json()
    assert quiet["lesson_soon"] == []

    _freeze_msk(monkeypatch, _msk(2026, 9, 22, 15, 50))
    armed = backend_client.patch(
        "/internal/bot/settings",
        json={"telegram_id": tid, "dm_lesson_soon": True, "dm_lesson_offset_minutes": 5},
        headers=INTERNAL,
    )
    assert armed.status_code == 200
    soon = backend_client.get("/internal/bot/due-personal", headers=INTERNAL).json()["lesson_soon"]
    assert len(soon) == 1
    assert soon[0]["telegram_id"] == tid
    assert "https://meetings.tversu.ru/j/1" in soon[0]["text"]
    assert "через 5 мин" in soon[0]["text"]
    assert "15:55" in soon[0]["text"]
    assert "17:45" not in soon[0]["text"]
    assert "ауд http" not in soon[0]["text"]

    _freeze_msk(monkeypatch, _msk(2026, 9, 21, 9, 0))
    with Session(backend_engine) as session:
        session.add(
            Event(
                type="schedule",
                subject="Новая дисциплина",
                body="ещё не было",
                date=date(2026, 9, 24),
                time=time(9, 0),
                room="1",
            )
        )
        session.commit()

    again = backend_client.get("/internal/bot/me", params={"telegram_id": tid}, headers=INTERNAL).json()["user"]
    assert "новая дисциплина|3|09:00" not in again["dm_lesson_slot_keys"]
    assert again["dm_lesson_all"] is False

    refreshed = backend_client.patch(
        "/internal/bot/settings",
        json={"telegram_id": tid, "dm_lesson_all": True},
        headers=INTERNAL,
    )
    assert "новая дисциплина|3|09:00" in refreshed.json()["user"]["dm_lesson_slot_keys"]

    bad = backend_client.patch(
        "/internal/bot/settings",
        json={"telegram_id": tid, "dm_lesson_offset_minutes": 15},
        headers=INTERNAL,
    )
    assert bad.status_code == 400


def test_lesson_soon_offset_skips_later_pair_same_day(backend_client, backend_engine, monkeypatch):
    monday = date(2026, 9, 21)
    with Session(backend_engine) as session:
        user = _student(
            session,
            telegram_id=720,
            login="soon_user",
            dm_lesson_soon=True,
            dm_lesson_offset_minutes=5,
            dm_lesson_slot_keys=[
                "неклассические логики|0|14:00",
                "дискретная математика|0|14:01",
            ],
        )
        session.add(Event(type="schedule", subject="Неклассические логики", body="1", date=monday, time=time(14, 0), room="200"))
        session.add(Event(type="schedule", subject="Неклассические логики", body="2", date=monday, time=time(15, 55), room="201"))
        session.add(Event(type="schedule", subject="Дискретная математика", body="1", date=monday, time=time(14, 1), room="202"))
        session.commit()
        user_id = user.id

    def due_at(hour, minute, offset):
        _freeze_msk(monkeypatch, _msk(2026, 9, 21, hour, minute))
        patched = backend_client.patch(
            "/internal/bot/settings",
            json={"telegram_id": 720, "dm_lesson_offset_minutes": offset, "dm_lesson_soon": True},
            headers=INTERNAL,
        )
        assert patched.status_code == 200
        response = backend_client.get("/internal/bot/due-personal", headers=INTERNAL)
        assert response.status_code == 200
        items = response.json()["lesson_soon"]
        assert all(item["telegram_id"] > 0 for item in items)
        assert all("chat_id" not in item for item in items)
        return items

    at_30 = due_at(13, 30, 30)
    assert [item["text"] for item in at_30 if "логик" in item["text"].lower() or "Логик" in item["text"]]
    assert len(at_30) == 1
    assert "14:00" in at_30[0]["text"]
    assert "через 30 мин" in at_30[0]["text"]
    assert "ауд 200" in at_30[0]["text"]
    assert "15:55" not in at_30[0]["text"]

    assert due_at(13, 33, 30) == []
    at_10 = due_at(13, 50, 10)
    assert len(at_10) == 1
    assert "через 10 мин" in at_10[0]["text"]
    assert "14:00" in at_10[0]["text"]
    assert due_at(13, 50, 5) == []

    at_5 = due_at(13, 55, 5)
    assert len(at_5) == 1
    assert "через 5 мин" in at_5[0]["text"]
    assert "14:00" in at_5[0]["text"]

    both = due_at(13, 56, 5)
    assert len(both) == 2
    assert {item["dedupe_key"] for item in both} == {
        "2026-09-21|неклассические логики|0|14:00",
        "2026-09-21|дискретная математика|0|14:01",
    }
    assert all("15:55" not in item["text"] for item in both)

    assert due_at(15, 50, 5) == []

    first = due_at(13, 55, 5)[0]
    marked = backend_client.post(
        "/internal/bot/mark-personal-sent",
        json={
            "user_id": user_id,
            "kind": "lesson_soon",
            "dedupe_key": first["dedupe_key"],
            "event_id": first["event_id"],
        },
        headers=INTERNAL,
    )
    assert marked.status_code == 200
    again = due_at(13, 55, 5)
    assert all(item["dedupe_key"] != first["dedupe_key"] for item in again)


def test_transfer_eve_is_personal_and_schedule_ping_still_fires(backend_client, backend_engine, monkeypatch):
    with Session(backend_engine) as session:
        user = _student(
            session,
            telegram_id=730,
            login="transfer_user",
            dm_transfer_eve=True,
            dm_lesson_soon=True,
            dm_lesson_offset_minutes=5,
            dm_lesson_slot_keys=["теория графов|1|11:20"],
        )
        _student(
            session,
            login="transfer_offline",
            dm_transfer_eve=True,
            dm_lesson_soon=True,
            dm_lesson_slot_keys=["теория графов|1|11:20"],
        )
        _student(
            session,
            telegram_id=-100555,
            login="transfer_group",
            dm_transfer_eve=True,
            dm_lesson_soon=True,
            dm_lesson_slot_keys=["теория графов|1|11:20"],
        )
        _student(session, telegram_id=731, login="transfer_off", dm_transfer_eve=False, dm_lesson_soon=False)
        moved = Event(
            type="transfer",
            subject="Теория графов",
            body="НЕ_ДУБЛИРОВАТЬ_УТРО https://meetings.tversu.ru/move/1",
            date=date(2026, 9, 22),
            time=time(11, 20),
            room="405",
            reminder_sent=True,
            chat_id=-100555,
        )
        session.add(moved)
        session.add(
            Event(
                type="schedule",
                subject="Теория графов",
                body="обычная пара",
                date=date(2026, 9, 22),
                time=time(11, 20),
                room="405",
            )
        )
        session.commit()
        session.refresh(moved)
        transfer_id = moved.id
        user_id = user.id

    _freeze_msk(monkeypatch, _msk(2026, 9, 21, 16, 59))
    early = backend_client.get("/internal/bot/due-personal", headers=INTERNAL).json()
    assert early["transfer_eve"] == []

    _freeze_msk(monkeypatch, _msk(2026, 9, 21, 17, 0))
    due = backend_client.get("/internal/bot/due-personal", headers=INTERNAL).json()
    assert len(due["transfer_eve"]) == 1
    item = due["transfer_eve"][0]
    assert item["telegram_id"] == 730
    assert item["telegram_id"] > 0
    assert item["kind"] == "transfer_eve"
    assert item["dedupe_key"] == str(transfer_id)
    assert item["event_id"] == transfer_id
    assert "Перенос" in item["text"]
    assert "Теория графов" in item["text"]
    assert "22.09.2026" in item["text"]
    assert "11:20" in item["text"]
    assert "ауд 405" in item["text"]
    assert "https://meetings.tversu.ru/move/1" in item["text"]
    assert "НЕ_ДУБЛИРОВАТЬ_УТРО" not in item["text"]
    assert "Расписание" not in item["text"]
    assert due["lesson_soon"] == []
    assert all(row["user_id"] == user_id for row in due["transfer_eve"])

    group = backend_client.get("/events/due_reminders")
    assert group.status_code == 200
    assert transfer_id not in {row["id"] for row in group.json()}

    _freeze_msk(monkeypatch, _msk(2026, 9, 22, 17, 0))
    day_of = backend_client.get("/internal/bot/due-personal", headers=INTERNAL).json()
    assert day_of["transfer_eve"] == []

    _freeze_msk(monkeypatch, _msk(2026, 9, 22, 11, 15))
    lesson = backend_client.get("/internal/bot/due-personal", headers=INTERNAL).json()["lesson_soon"]
    assert len(lesson) == 1
    assert lesson[0]["telegram_id"] == 730
    assert "Теория графов" in lesson[0]["text"]
    assert "через 5 мин" in lesson[0]["text"]
    assert "ауд 405" in lesson[0]["text"]


def test_logout_resets_lesson_and_transfer_flags(backend_client, backend_engine):
    with Session(backend_engine) as session:
        user = _student(session, telegram_id=740, login="logout_slots")
        login_name = user.login

    patched = backend_client.patch(
        "/internal/bot/settings",
        json={
            "telegram_id": 740,
            "dm_lesson_soon": True,
            "dm_lesson_offset_minutes": 30,
            "dm_transfer_eve": True,
            "dm_morning_schedule": True,
        },
        headers=INTERNAL,
    )
    assert patched.status_code == 200

    out = backend_client.post("/internal/bot/logout", json={"telegram_id": 740}, headers=INTERNAL)
    assert out.status_code == 200
    with Session(backend_engine) as session:
        saved = session.exec(select(User).where(User.login == login_name)).one()
        assert saved.telegram_id is None
        assert not saved.dm_lesson_soon
        assert saved.dm_lesson_offset_minutes == 5
        assert not saved.dm_lesson_slot_keys
        assert not saved.dm_transfer_eve
        assert not saved.dm_morning_schedule
        assert not saved.dm_homework_reminder
