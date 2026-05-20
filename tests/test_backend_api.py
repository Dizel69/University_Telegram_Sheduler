from datetime import date, time, timedelta

from sqlmodel import Session, select

from app.models import AttendanceMark, Event, HomeworkCompletion, User


ADMIN_HEADERS = {"X-ADMIN-TOKEN": "test-admin-token"}


def _login_admin(client):
    response = client.post("/auth/login", json={"login": "admin", "password": "test-admin-token"})
    assert response.status_code == 200
    return response.json()["access_token"]


def test_event_lifecycle_and_calendar_filter(backend_client, backend_engine):
    create_response = backend_client.post(
        "/events",
        headers=ADMIN_HEADERS,
        json={
            "type": "Домашнее задание",
            "subject": "Math",
            "body": "Solve problems",
            "date": "2026-05-20",
            "time": "12:30",
            "semester": "2",
        },
    )
    assert create_response.status_code == 200
    created = create_response.json()
    assert created["type"] == "homework"
    assert created["semester"] == "Второй семестр"

    event_id = created["id"]

    events_response = backend_client.get("/events")
    assert events_response.status_code == 200
    assert [event["id"] for event in events_response.json()] == [event_id]

    calendar_response = backend_client.get("/calendar", params={"start": "2026-05-01", "end": "2026-05-31", "type": "homework"})
    assert calendar_response.status_code == 200
    assert calendar_response.json()[0]["id"] == event_id

    update_response = backend_client.put(
        f"/events/{event_id}",
        headers=ADMIN_HEADERS,
        json={"room": "101", "teacher": "Dr. Smith"},
    )
    assert update_response.status_code == 200
    assert update_response.json() == {"ok": True}

    with Session(backend_engine) as session:
        updated = session.get(Event, event_id)
        assert updated.room == "101"
        assert updated.teacher == "Dr. Smith"

    delete_response = backend_client.delete(f"/events/{event_id}", headers=ADMIN_HEADERS)
    assert delete_response.status_code == 200

    missing_response = backend_client.delete(f"/events/{event_id}", headers=ADMIN_HEADERS)
    assert missing_response.status_code == 404


def test_due_reminders_and_mark_sent(backend_client, backend_engine):
    with Session(backend_engine) as session:
        due = Event(
            type="homework",
            body="Due soon",
            date=date.today() + timedelta(days=1),
            time=time(9, 0),
            reminder_offset_hours=48,
            chat_id=123,
            topic_thread_id=456,
        )
        not_due = Event(
            type="homework",
            body="Later",
            date=date.today() + timedelta(days=3),
            time=time(9, 0),
            reminder_offset_hours=1,
        )
        session.add(due)
        session.add(not_due)
        session.commit()
        session.refresh(due)
        due_id = due.id

    reminders_response = backend_client.get("/events/due_reminders")
    assert reminders_response.status_code == 200
    reminders = reminders_response.json()
    assert [event["id"] for event in reminders] == [due_id]
    assert reminders[0]["chat_id"] == 123
    assert reminders[0]["thread_id"] == 456

    mark_response = backend_client.post(f"/events/{due_id}/mark_reminder_sent")
    assert mark_response.status_code == 200

    with Session(backend_engine) as session:
        assert session.get(Event, due_id).reminder_sent is True

    assert backend_client.post("/events/9999/mark_reminder_sent").status_code == 404


def test_auth_me_and_homework_completion_flow(backend_client, backend_engine):
    token = _login_admin(backend_client)
    auth_headers = {"Authorization": f"Bearer {token}"}

    me_response = backend_client.get("/auth/me", headers=auth_headers)
    assert me_response.status_code == 200
    assert me_response.json()["login"] == "admin"

    with Session(backend_engine) as session:
        homework = Event(type="homework", body="Read chapter", date=date.today())
        schedule = Event(type="schedule", body="Lecture", date=date.today())
        session.add(homework)
        session.add(schedule)
        session.commit()
        session.refresh(homework)
        session.refresh(schedule)
        homework_id = homework.id
        schedule_id = schedule.id

    first_mark = backend_client.post(f"/homework-completion/{homework_id}", headers=auth_headers)
    duplicate_mark = backend_client.post(f"/homework-completion/{homework_id}", headers=auth_headers)
    invalid_mark = backend_client.post(f"/homework-completion/{schedule_id}", headers=auth_headers)

    assert first_mark.status_code == 200
    assert duplicate_mark.status_code == 200
    assert invalid_mark.status_code == 400

    list_response = backend_client.get("/homework-completion", headers=auth_headers)
    assert list_response.json() == {"event_ids": [homework_id]}

    with Session(backend_engine) as session:
        rows = session.exec(select(HomeworkCompletion)).all()
        assert len(rows) == 1

    remove_response = backend_client.delete(f"/homework-completion/{homework_id}", headers=auth_headers)
    assert remove_response.status_code == 200
    assert backend_client.get("/homework-completion", headers=auth_headers).json() == {"event_ids": []}


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


def test_create_and_send_uses_bot_service_and_stores_message_id(backend_client, backend_engine, monkeypatch):
    from app import main

    _FakeAsyncClient.calls = []
    monkeypatch.setattr(main.httpx, "AsyncClient", _FakeAsyncClient)

    response = backend_client.post(
        "/events/send",
        headers=ADMIN_HEADERS,
        json={
            "type": "announcement",
            "subject": "General",
            "body": "Important update",
            "date": "2026-05-21",
            "chat_id": 222,
            "topic_thread_id": 333,
        },
    )

    assert response.status_code == 200
    event_id = response.json()["id"]
    assert _FakeAsyncClient.calls == [
        {
            "url": "http://bot-service.test/send",
            "json": {
                "chat_id": 222,
                "thread_id": 333,
                "text": "#Объявление\n#General\nImportant update\nСсылка в календаре: http://127.0.0.1:3000/calendar/m15/event/1",
            },
            "timeout": 10.0,
        }
    ]

    with Session(backend_engine) as session:
        assert session.get(Event, event_id).sent_message_id == 777


def test_owner_user_management(backend_client):
    token = _login_admin(backend_client)
    headers = {"Authorization": f"Bearer {token}"}

    create_response = backend_client.post(
        "/owner/users",
        headers=headers,
        json={
            "last_name": "Ivanov",
            "first_name": "Ivan",
            "login": "ivan",
            "password": "pass",
            "is_admin": False,
        },
    )
    assert create_response.status_code == 200
    user_id = create_response.json()["id"]

    list_response = backend_client.get("/owner/users", headers=headers)
    assert {user["login"] for user in list_response.json()} == {"admin", "ivan"}

    patch_response = backend_client.patch(
        f"/owner/users/{user_id}",
        headers=headers,
        json={"first_name": "Petr", "is_admin": True},
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["first_name"] == "Petr"
    assert patch_response.json()["is_admin"] is True

    delete_response = backend_client.delete(f"/owner/users/{user_id}", headers=headers)
    assert delete_response.status_code == 200

    admin_delete_response = backend_client.delete("/owner/users/1", headers=headers)
    assert admin_delete_response.status_code == 400


def test_attendance_board_and_marks(backend_client, backend_engine):
    day = date(2026, 5, 19)
    with Session(backend_engine) as session:
        session.add(
            Event(
                type="schedule",
                subject="Math",
                body="Lecture",
                date=day,
            )
        )
        session.commit()

    denied = backend_client.get("/admin/attendance", params={"date": day.isoformat()})
    assert denied.status_code in (401, 403)

    board = backend_client.get(
        "/admin/attendance",
        params={"date": day.isoformat()},
        headers=ADMIN_HEADERS,
    )
    assert board.status_code == 200
    data = board.json()
    assert data["date"] == day.isoformat()
    assert "Math" in data["subjects"]
    assert len(data["users"]) >= 1
    user_id = data["users"][0]["id"]

    set_n = backend_client.put(
        "/admin/attendance",
        headers=ADMIN_HEADERS,
        json={"user_id": user_id, "subject": "Math", "date": day.isoformat(), "mark": "N"},
    )
    assert set_n.status_code == 200

    board2 = backend_client.get(
        "/admin/attendance",
        params={"date": day.isoformat()},
        headers=ADMIN_HEADERS,
    )
    assert board2.json()["marks"] == [{"user_id": user_id, "subject": "Math", "mark": "N"}]

    set_b = backend_client.put(
        "/admin/attendance",
        headers=ADMIN_HEADERS,
        json={"user_id": user_id, "subject": "Math", "date": day.isoformat(), "mark": "Б"},
    )
    assert set_b.status_code == 200

    with Session(backend_engine) as session:
        row = session.exec(select(AttendanceMark)).first()
        assert row.mark == "B"

    clear = backend_client.put(
        "/admin/attendance",
        headers=ADMIN_HEADERS,
        json={"user_id": user_id, "subject": "Math", "date": day.isoformat(), "mark": None},
    )
    assert clear.status_code == 200
    assert backend_client.get(
        "/admin/attendance",
        params={"date": day.isoformat()},
        headers=ADMIN_HEADERS,
    ).json()["marks"] == []
