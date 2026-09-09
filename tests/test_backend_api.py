from datetime import date, time, timedelta

from sqlmodel import Session, select

from app.models import AttendanceMark, Event, HomeworkCompletion, SubjectSetting, TeacherSetting, User


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


def test_event_update_via_jwt_admin_updates_time(backend_client, backend_engine):
    """Админ через Bearer JWT (не X-ADMIN-TOKEN) — правка времени и подсветки дней."""
    token = _login_admin(backend_client)
    auth_headers = {"Authorization": f"Bearer {token}"}

    create_response = backend_client.post(
        "/events",
        headers=auth_headers,
        json={
            "type": "schedule",
            "body": "Lecture",
            "date": "2026-06-10",
            "time": "10:00",
            "end_time": "11:30",
        },
    )
    assert create_response.status_code == 200
    event_id = create_response.json()["id"]

    update_response = backend_client.put(
        f"/events/{event_id}",
        headers=auth_headers,
        json={"time": "14:00", "end_time": "15:30"},
    )
    assert update_response.status_code == 200
    assert update_response.json() == {"ok": True}

    with Session(backend_engine) as session:
        updated = session.get(Event, event_id)
        assert updated.time == time(14, 0)
        assert updated.end_time == time(15, 30)

    highlights_response = backend_client.put(
        "/calendar/day-range-highlights",
        headers=auth_headers,
        json=[{"start": "2026-06-01", "end": "2026-06-07", "color": "#ff0000", "stitch": True}],
    )
    assert highlights_response.status_code == 200
    assert len(highlights_response.json()) == 1


def test_due_reminders_and_mark_sent(backend_client, backend_engine):
    with Session(backend_engine) as session:
        due = Event(
            type="homework",
            body="Due soon",
            date=date.today() + timedelta(days=1),
            time=time(9, 0),
            end_time=time(10, 30),
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
    assert reminders[0]["time"] == "09:00:00"
    assert reminders[0]["end_time"] == "10:30:00"

    mark_response = backend_client.post(f"/events/{due_id}/mark_reminder_sent")
    assert mark_response.status_code == 200

    with Session(backend_engine) as session:
        assert session.get(Event, due_id).reminder_sent is True

    assert backend_client.post("/events/9999/mark_reminder_sent").status_code == 404


def test_birthdays_today_returns_full_name_and_age(backend_client, backend_engine):
    today = date.today()
    with Session(backend_engine) as session:
        session.add(
            User(
                last_name="Иванов",
                first_name="Иван",
                middle_name="Иванович",
                birth_date=date(today.year - 20, today.month, today.day),
                login="birthday-user",
                password_hash="hash",
                is_admin=False,
            )
        )
        session.commit()

    response = backend_client.get("/birthdays/today")
    assert response.status_code == 200
    data = response.json()
    assert data["chat_id"] == 100500
    assert data["thread_id"] is None
    assert len(data["birthdays"]) == 1
    assert data["birthdays"][0]["full_name"] == "Иванов Иван Иванович"
    assert data["birthdays"][0]["age"] == 20


def test_upload_file_returns_public_url(backend_client):
    import base64

    content = base64.b64encode(b"hello").decode("ascii")
    response = backend_client.post(
        "/files/upload",
        headers=ADMIN_HEADERS,
        json={"filename": "notes.txt", "content_base64": content, "content_type": "text/plain"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["kind"] == "document"
    assert data["url"].startswith("http://127.0.0.1:8000/uploads/")


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
            "time": "10:15",
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
                "text": "#Объявление\n#General\nImportant update\nВремя: 10:15\nСсылка в календаре: http://127.0.0.1:3000/calendar/m15/event/1",
            },
            "timeout": 10.0,
        }
    ]

    with Session(backend_engine) as session:
        assert session.get(Event, event_id).sent_message_id == 777


def test_send_telegram_only_does_not_persist_event(backend_client, backend_engine, monkeypatch):
    from app import main

    _FakeAsyncClient.calls = []
    monkeypatch.setattr(main.httpx, "AsyncClient", _FakeAsyncClient)

    response = backend_client.post(
        "/events/send_telegram_only",
        headers=ADMIN_HEADERS,
        json={
            "type": "announcement",
            "subject": "General",
            "body": "Flash notice",
            "date": "2026-05-21",
            "time": "10:15",
            "chat_id": 222,
            "topic_thread_id": 333,
        },
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "message_id": 777, "type": "announcement"}
    assert _FakeAsyncClient.calls == [
        {
            "url": "http://bot-service.test/send",
            "json": {
                "chat_id": 222,
                "thread_id": 333,
                "text": "#Объявление\n#General\nFlash notice\nВремя: 10:15",
            },
            "timeout": 10.0,
        }
    ]

    with Session(backend_engine) as session:
        assert session.exec(select(Event)).all() == []


def test_send_telegram_only_rejects_non_announcement(backend_client, monkeypatch):
    from app import main

    _FakeAsyncClient.calls = []
    monkeypatch.setattr(main.httpx, "AsyncClient", _FakeAsyncClient)

    response = backend_client.post(
        "/events/send_telegram_only",
        headers=ADMIN_HEADERS,
        json={
            "type": "homework",
            "subject": "Math",
            "body": "Do not send this way",
        },
    )

    assert response.status_code == 400
    assert _FakeAsyncClient.calls == []


def test_create_and_send_exam_control_includes_time(backend_client, monkeypatch):
    from app import main

    _FakeAsyncClient.calls = []
    monkeypatch.setattr(main.httpx, "AsyncClient", _FakeAsyncClient)

    response = backend_client.post(
        "/events/send",
        headers=ADMIN_HEADERS,
        json={
            "type": "exam_control",
            "lesson_type": "exam",
            "subject": "Math",
            "body": "Bring ID",
            "date": "2026-05-21",
            "time": "12:40",
            "chat_id": 222,
        },
    )

    assert response.status_code == 200
    sent_text = _FakeAsyncClient.calls[0]["json"]["text"]
    assert "Время: 12:40" in sent_text


def test_create_and_send_transfer_includes_time(backend_client, monkeypatch):
    from app import main

    _FakeAsyncClient.calls = []
    monkeypatch.setattr(main.httpx, "AsyncClient", _FakeAsyncClient)

    response = backend_client.post(
        "/events/send",
        headers=ADMIN_HEADERS,
        json={
            "type": "transfer",
            "subject": "General",
            "body": "Перенос пары на другое время",
            "date": "2026-05-21",
            "time": "08:05",
            "chat_id": 222,
        },
    )

    assert response.status_code == 200
    sent_text = _FakeAsyncClient.calls[0]["json"]["text"]
    assert "Время: 08:05" in sent_text


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
    exam_day = date(2026, 5, 21)
    with Session(backend_engine) as session:
        physics_pair = Event(
            type="schedule",
            subject="Физика",
            body="Лекция",
            date=control_day,
            time=time(10, 0),
        )
        physics_control = Event(
            type="exam_control",
            subject="Физика",
            body="Контрольная",
            date=control_day,
            time=time(10, 0),
            lesson_type="control",
        )
        physics_exam = Event(
            type="exam_control",
            subject="Физика",
            body="Экзамен",
            date=exam_day,
            time=time(12, 0),
            lesson_type="exam",
        )
        session.add(physics_pair)
        session.add(physics_control)
        session.add(physics_exam)
        session.commit()
        session.refresh(physics_control)
        physics_control_id = physics_control.id

    board_ctrl = backend_client.get(
        "/admin/attendance",
        params={"week_start": control_day.isoformat()},
        headers=ADMIN_HEADERS,
    )
    ctrl_day = next(d for d in board_ctrl.json()["days"] if str(d["date"])[:10] == control_day.isoformat())
    physics_slots = [s for s in ctrl_day["slots"] if "Физика" in s["label"]]
    assert len(physics_slots) == 1
    assert "контрольная" not in physics_slots[0]["label"].lower()
    assert "экзамен" not in physics_slots[0]["label"].lower()

    exam_col = next(d for d in board_ctrl.json()["days"] if str(d["date"])[:10] == exam_day.isoformat())
    assert all("Физика" not in s["label"] for s in exam_col["slots"])

    exam_put = backend_client.put(
        "/admin/attendance",
        headers=ADMIN_HEADERS,
        json={"user_id": student_id, "event_id": physics_control_id, "mark": "N"},
    )
    assert exam_put.status_code == 400

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


def test_analytics_dashboard(backend_client, backend_engine):
    from app.security import hash_password

    week_day = date(2026, 5, 19)
    with Session(backend_engine) as session:
        lesson = Event(
            type="schedule",
            subject="Math",
            body="Lecture",
            date=week_day,
            time=time(10, 0),
        )
        hw = Event(
            type="homework",
            subject="Math",
            body="HW1",
            date=week_day,
            semester="Второй семестр",
        )
        student = User(
            last_name="Ana",
            first_name="Lit",
            login="ana_an",
            password_hash=hash_password("x"),
            is_admin=False,
            is_owner=False,
        )
        session.add(lesson)
        session.add(hw)
        session.add(student)
        session.commit()
        session.refresh(lesson)
        session.refresh(hw)
        session.refresh(student)
        lesson_id = lesson.id
        hw_id = hw.id
        student_id = student.id

    denied = backend_client.get("/admin/analytics", params={"period": "week", "week_start": week_day.isoformat()})
    assert denied.status_code in (401, 403)

    resp = backend_client.get(
        "/admin/analytics",
        params={"period": "week", "week_start": week_day.isoformat()},
        headers=ADMIN_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["period"] == "week"
    assert data["kpi"]["lessons_in_period"] >= 1
    assert len(data["students"]) >= 1
    assert len(data["weekly_trend"]) == 8
    assert "telegram" in data
    assert "events_current_count" in data["telegram"]
    assert data["event_type_breakdown"]
    assert data["daily_load"]
    assert "homework_overview" in data
    assert "attendance_overview" in data

    backend_client.put(
        "/admin/attendance",
        headers=ADMIN_HEADERS,
        json={"user_id": student_id, "event_id": lesson_id, "mark": "N"},
    )
    student_login = backend_client.post("/auth/login", json={"login": "ana_an", "password": "x"})
    assert student_login.status_code == 200
    student_headers = {"Authorization": f"Bearer {student_login.json()['access_token']}"}
    hw_done = backend_client.post(f"/homework-completion/{hw_id}", headers=student_headers)
    assert hw_done.status_code == 200

    resp2 = backend_client.get(
        "/admin/analytics",
        params={"period": "week", "week_start": week_day.isoformat()},
        headers=ADMIN_HEADERS,
    )
    kpi = resp2.json()["kpi"]
    assert kpi["absent_marks"] >= 1
    assert kpi["homework_completion_rate"] > 0

    by_student = backend_client.get(
        "/admin/analytics",
        params={"period": "week", "week_start": week_day.isoformat(), "user_id": student_id},
        headers=ADMIN_HEADERS,
    )
    assert by_student.status_code == 200
    assert by_student.json()["user_filter"] == student_id
    assert by_student.json()["kpi"]["homework_completion_rate"] == 100.0

    by_subject = backend_client.get(
        "/admin/analytics",
        params={"period": "week", "week_start": week_day.isoformat(), "subject": "Math"},
        headers=ADMIN_HEADERS,
    )
    assert by_subject.status_code == 200
    assert by_subject.json()["subject_filter"] == "Math"
    assert "Math" in by_subject.json()["available_subjects"]
    assert by_subject.json()["subject_workload"][0]["subject"] == "Math"

    bad_subject = backend_client.get(
        "/admin/analytics",
        params={"period": "week", "week_start": week_day.isoformat(), "subject": "Несуществующий"},
        headers=ADMIN_HEADERS,
    )
    assert bad_subject.status_code == 400


def test_subjects_admin_rename_and_visibility(backend_client, backend_engine):
    lesson_day = date(2026, 5, 19)
    with Session(backend_engine) as session:
        session.add(
            Event(
                type="schedule",
                subject="Java  и Web-Программирование",
                body="Lecture",
                date=lesson_day,
                time=time(10, 0),
            )
        )
        session.add(
            Event(
                type="homework",
                subject="Java и Web-Программирование",
                body="HW",
                date=lesson_day,
            )
        )
        session.commit()

    denied = backend_client.get("/admin/subjects")
    assert denied.status_code in (401, 403)

    response = backend_client.get("/admin/subjects", headers=ADMIN_HEADERS)
    assert response.status_code == 200
    rows = response.json()["subjects"]
    row = next(r for r in rows if r["display_name"] == "Java и Web-Программирование")
    assert row["events_total"] == 2
    assert row["raw_names"] == ["Java  и Web-Программирование", "Java и Web-Программирование"]

    variant_update = backend_client.patch(
        "/admin/subjects/variant",
        headers=ADMIN_HEADERS,
        json={
            "subject_key": row["subject_key"],
            "raw_name": "Java  и Web-Программирование",
            "display_name": "Java и Web-Программирование",
        },
    )
    assert variant_update.status_code == 200
    assert variant_update.json()["updated_events"] == 1

    update = backend_client.patch(
        "/admin/subjects",
        headers=ADMIN_HEADERS,
        json={
            "subject_key": row["subject_key"],
            "display_name": "Java и Web",
            "is_visible": False,
            "rename_events": True,
        },
    )
    assert update.status_code == 200
    assert update.json()["updated_events"] == 2
    assert update.json()["subject"]["display_name"] == "Java и Web"
    assert update.json()["subject"]["is_visible"] is False

    with Session(backend_engine) as session:
        subjects = [ev.subject for ev in session.exec(select(Event)).all()]
        assert subjects == ["Java и Web", "Java и Web"]
        setting = session.exec(select(SubjectSetting)).first()
        assert setting.subject_key == "java и web"
        assert setting.is_visible is False

    analytics = backend_client.get(
        "/admin/analytics",
        params={"period": "week", "week_start": lesson_day.isoformat()},
        headers=ADMIN_HEADERS,
    )
    assert "Java и Web" not in analytics.json()["available_subjects"]


def test_teachers_admin_rename_and_visibility(backend_client, backend_engine):
    lesson_day = date(2026, 5, 19)
    with Session(backend_engine) as session:
        session.add(
            Event(
                type="schedule",
                subject="Math",
                teacher="Ivanov  I.I.",
                body="Lecture",
                date=lesson_day,
                time=time(10, 0),
            )
        )
        session.add(
            Event(
                type="exam_control",
                subject="Math",
                teacher="Ivanov I.I.",
                body="Control",
                date=lesson_day,
                time=time(12, 0),
            )
        )
        session.commit()

    denied = backend_client.get("/admin/teachers")
    assert denied.status_code in (401, 403)

    response = backend_client.get("/admin/teachers", headers=ADMIN_HEADERS)
    assert response.status_code == 200
    row = next(r for r in response.json()["teachers"] if r["display_name"] == "Ivanov I.I.")
    assert row["events_total"] == 2
    assert row["raw_names"] == ["Ivanov  I.I.", "Ivanov I.I."]
    assert row["subjects"] == ["Math"]

    variant_update = backend_client.patch(
        "/admin/teachers/variant",
        headers=ADMIN_HEADERS,
        json={
            "teacher_key": row["teacher_key"],
            "raw_name": "Ivanov  I.I.",
            "display_name": "Ivanov I.I.",
        },
    )
    assert variant_update.status_code == 200
    assert variant_update.json()["updated_events"] == 1

    update = backend_client.patch(
        "/admin/teachers",
        headers=ADMIN_HEADERS,
        json={
            "teacher_key": row["teacher_key"],
            "display_name": "Ivanov",
            "is_visible": False,
            "rename_events": True,
        },
    )
    assert update.status_code == 200
    assert update.json()["updated_events"] == 2
    assert update.json()["teacher"]["display_name"] == "Ivanov"
    assert update.json()["teacher"]["is_visible"] is False

    with Session(backend_engine) as session:
        teachers = [ev.teacher for ev in session.exec(select(Event)).all()]
        assert teachers == ["Ivanov", "Ivanov"]
        setting = session.exec(select(TeacherSetting)).first()
        assert setting.teacher_key == "ivanov"
        assert setting.is_visible is False

    analytics = backend_client.get(
        "/admin/analytics",
        params={"period": "week", "week_start": lesson_day.isoformat()},
        headers=ADMIN_HEADERS,
    )
    assert analytics.json()["teacher_workload"] == []


def test_teacher_profile_degree_and_position(backend_client):
    denied = backend_client.post(
        "/teacher-profiles",
        json={"full_name": "Иванов Иван Иванович"},
    )
    assert denied.status_code in (401, 403)

    created = backend_client.post(
        "/teacher-profiles",
        headers=ADMIN_HEADERS,
        json={
            "full_name": " Иванов Иван Иванович ",
            "academic_degree": " к.ф.-м.н. ",
            "position": " доцент ",
            "department": "Кафедра математики",
            "contact": "ivanov@uni.test",
            "bio": "Читает анализ",
        },
    )
    assert created.status_code == 200
    row = created.json()
    assert row["full_name"] == "Иванов Иван Иванович"
    assert row["academic_degree"] == "к.ф.-м.н."
    assert row["position"] == "доцент"
    assert row["department"] == "Кафедра математики"
    assert "Math" not in (row.get("subjects") or [])

    listed = backend_client.get("/teacher-profiles")
    assert listed.status_code == 200
    found = next(item for item in listed.json() if item["id"] == row["id"])
    assert found["academic_degree"] == "к.ф.-м.н."
    assert found["position"] == "доцент"

    updated = backend_client.put(
        f"/teacher-profiles/{row['id']}",
        headers=ADMIN_HEADERS,
        json={"academic_degree": "д.ф.-м.н.", "position": "профессор"},
    )
    assert updated.status_code == 200
    assert updated.json()["academic_degree"] == "д.ф.-м.н."
    assert updated.json()["position"] == "профессор"
    assert updated.json()["department"] == "Кафедра математики"

    cleared = backend_client.put(
        f"/teacher-profiles/{row['id']}",
        headers=ADMIN_HEADERS,
        json={"academic_degree": "  ", "position": ""},
    )
    assert cleared.status_code == 200
    assert cleared.json()["academic_degree"] is None
    assert cleared.json()["position"] is None


def test_feedback_requires_configured_chat_id(backend_client, monkeypatch):
    from app import feedback_routes

    monkeypatch.delenv("FEEDBACK_CHAT_ID", raising=False)
    feedback_routes._hits.clear()
    response = backend_client.post(
        "/feedback",
        json={"kind": "bug", "title": "Календарь", "body": "Не открывается карточка события"},
    )
    assert response.status_code == 503
    assert "FEEDBACK_CHAT_ID" in response.json()["detail"]


def test_feedback_rejects_short_body(backend_client, monkeypatch):
    monkeypatch.setenv("FEEDBACK_CHAT_ID", "424242")
    response = backend_client.post(
        "/feedback",
        json={"kind": "bug", "title": "Баг", "body": "мало"},
    )
    assert response.status_code == 422


def test_feedback_sends_to_private_chat_without_thread(backend_client, monkeypatch):
    from app import feedback_routes

    monkeypatch.setenv("FEEDBACK_CHAT_ID", "424242")
    feedback_routes._hits.clear()
    _FakeAsyncClient.calls = []
    monkeypatch.setattr(feedback_routes.httpx, "AsyncClient", _FakeAsyncClient)

    response = backend_client.post(
        "/feedback",
        json={
            "kind": "suggestion",
            "title": "Фильтр по преподавателю",
            "body": "Хотелось бы фильтровать пары по преподавателю",
            "page": "/#calendar",
            "contact": "tg @student",
        },
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert len(_FakeAsyncClient.calls) == 1
    sent = _FakeAsyncClient.calls[0]["json"]
    assert sent["chat_id"] == 424242
    assert "thread_id" not in sent
    assert "💡 Предложение" in sent["text"]
    assert "Фильтр по преподавателю" in sent["text"]
    assert "tg @student" in sent["text"]
    assert "/#calendar" in sent["text"]


def test_feedback_includes_logged_in_user_and_escapes_html(backend_client, monkeypatch):
    from app import feedback_routes

    monkeypatch.setenv("FEEDBACK_CHAT_ID", "424242")
    feedback_routes._hits.clear()
    _FakeAsyncClient.calls = []
    monkeypatch.setattr(feedback_routes.httpx, "AsyncClient", _FakeAsyncClient)

    token = _login_admin(backend_client)
    response = backend_client.post(
        "/feedback",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "kind": "bug",
            "title": "Падает <script>",
            "body": "Ошибка при сохранении A & B <tag>",
        },
    )
    assert response.status_code == 200
    text = _FakeAsyncClient.calls[0]["json"]["text"]
    assert "<script>" not in text
    assert "&lt;script&gt;" in text
    assert "A &amp; B" in text
    assert "admin" in text
    assert "🐛 Баг" in text
