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
    from app.security import hash_password

    lesson_day = date(2026, 5, 19)
    thursday = date(2026, 5, 21)
    with Session(backend_engine) as session:
        math_morning = Event(
            type="schedule",
            subject="Разметка",
            body="1-я пара",
            date=thursday,
            time=time(9, 0),
        )
        math_afternoon = Event(
            type="schedule",
            subject="Разметка",
            body="2-я пара",
            date=thursday,
            time=time(11, 40),
        )
        session.add(math_morning)
        session.add(math_afternoon)
        session.add(
            Event(
                type="schedule",
                subject="Math",
                body="Lecture",
                date=lesson_day,
            )
        )
        session.add(
            Event(
                type="transfer",
                subject="Языки разметки",
                body="Перенесено с понедельника",
                date=date(2026, 5, 22),
            )
        )
        student = User(
            last_name="Stud",
            first_name="Test",
            login="stu_att",
            password_hash=hash_password("secret"),
            is_admin=False,
            is_owner=False,
        )
        subadmin = User(
            last_name="SubAdm",
            first_name="Test",
            login="subadm_att",
            password_hash=hash_password("secret"),
            is_admin=True,
            is_owner=False,
        )
        owner_only = User(
            last_name="Owner",
            first_name="Test",
            login="owner_att",
            password_hash=hash_password("secret"),
            is_admin=True,
            is_owner=True,
        )
        session.add(student)
        session.add(subadmin)
        session.add(owner_only)
        session.commit()
        session.refresh(student)
        session.refresh(subadmin)
        session.refresh(owner_only)
        session.refresh(math_morning)
        session.refresh(math_afternoon)
        student_id = student.id
        subadmin_id = subadmin.id
        owner_id = owner_only.id
        math_morning_id = math_morning.id
        math_afternoon_id = math_afternoon.id

    denied = backend_client.get("/admin/attendance", params={"week_start": lesson_day.isoformat()})
    assert denied.status_code in (401, 403)

    board = backend_client.get(
        "/admin/attendance",
        params={"week_start": lesson_day.isoformat()},
        headers=ADMIN_HEADERS,
    )
    assert board.status_code == 200
    data = board.json()
    assert data["week_start"] == "2026-05-18"
    assert data["week_end"] == "2026-05-24"
    logins = {u["login"] for u in data["users"]}
    assert {"stu_att", "subadm_att"}.issubset(logins)
    assert "owner_att" not in logins
    assert all(not u.get("is_owner") for u in data["users"])
    thursday_day = next(d for d in data["days"] if str(d["date"])[:10] == thursday.isoformat())
    thursday_slots = thursday_day["slots"]
    assert len(thursday_slots) == 2
    assert thursday_slots[0]["event_id"] != thursday_slots[1]["event_id"]
    assert all("Разметка" in s["label"] for s in thursday_slots)

    control_day = date(2026, 5, 20)
    with Session(backend_engine) as session:
        session.add(
            Event(
                type="schedule",
                subject="Физика",
                body="Лекция",
                date=control_day,
                time=time(10, 0),
            )
        )
        session.add(
            Event(
                type="exam_control",
                subject="Физика",
                body="Контрольная",
                date=control_day,
                time=time(10, 0),
                lesson_type="control",
            )
        )
        session.commit()

    board_ctrl = backend_client.get(
        "/admin/attendance",
        params={"week_start": control_day.isoformat()},
        headers=ADMIN_HEADERS,
    )
    ctrl_day = next(d for d in board_ctrl.json()["days"] if str(d["date"])[:10] == control_day.isoformat())
    physics_slots = [s for s in ctrl_day["slots"] if "Физика" in s["label"]]
    assert len(physics_slots) == 1
    assert "контрольная" in physics_slots[0]["label"].lower()

    with Session(backend_engine) as session:
        math_ev = session.exec(select(Event).where(Event.date == lesson_day, Event.subject == "Math")).first()
        math_event_id = math_ev.id

    owner_put = backend_client.put(
        "/admin/attendance",
        headers=ADMIN_HEADERS,
        json={"user_id": owner_id, "event_id": math_event_id, "mark": "N"},
    )
    assert owner_put.status_code == 400

    set_morning_n = backend_client.put(
        "/admin/attendance",
        headers=ADMIN_HEADERS,
        json={"user_id": student_id, "event_id": math_morning_id, "mark": "N"},
    )
    assert set_morning_n.status_code == 200

    set_afternoon_b = backend_client.put(
        "/admin/attendance",
        headers=ADMIN_HEADERS,
        json={"user_id": student_id, "event_id": math_afternoon_id, "mark": "Б"},
    )
    assert set_afternoon_b.status_code == 200

    set_subadm = backend_client.put(
        "/admin/attendance",
        headers=ADMIN_HEADERS,
        json={"user_id": subadmin_id, "event_id": math_event_id, "mark": "Б"},
    )
    assert set_subadm.status_code == 200

    board2 = backend_client.get(
        "/admin/attendance",
        params={"week_start": lesson_day.isoformat()},
        headers=ADMIN_HEADERS,
    )
    marks = board2.json()["marks"]
    assert len(marks) == 3
    assert {"user_id": student_id, "event_id": math_morning_id, "mark": "N"} in marks
    assert {"user_id": student_id, "event_id": math_afternoon_id, "mark": "B"} in marks
    assert {"user_id": subadmin_id, "event_id": math_event_id, "mark": "B"} in marks

    backend_client.put(
        "/admin/attendance",
        headers=ADMIN_HEADERS,
        json={"user_id": student_id, "event_id": math_morning_id, "mark": None},
    )

    with Session(backend_engine) as session:
        rows = session.exec(select(AttendanceMark).where(AttendanceMark.user_id == student_id)).all()
        assert len(rows) == 1
        assert rows[0].event_id == math_afternoon_id
        assert rows[0].mark == "B"

    backend_client.put(
        "/admin/attendance",
        headers=ADMIN_HEADERS,
        json={"user_id": subadmin_id, "event_id": math_event_id, "mark": None},
    )

    backend_client.put(
        "/admin/attendance",
        headers=ADMIN_HEADERS,
        json={"user_id": student_id, "event_id": math_afternoon_id, "mark": None},
    )
    assert backend_client.get(
        "/admin/attendance",
        params={"week_start": lesson_day.isoformat()},
        headers=ADMIN_HEADERS,
    ).json()["marks"] == []
