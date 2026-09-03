import httpx

import worker


class FakeResponse:
    def __init__(self, data=None, status_code=200):
        self._data = data
        self.status_code = status_code

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)


class FakeClient:
    instances = []

    def __init__(self, events=None, fail_event_ids=None, birthday_payload=None):
        self.events = events or []
        self.fail_event_ids = set(fail_event_ids or [])
        self.birthday_payload = birthday_payload or {"chat_id": None, "thread_id": None, "birthdays": []}
        self.get_calls = []
        self.post_calls = []
        FakeClient.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def get(self, url, timeout):
        self.get_calls.append({"url": url, "timeout": timeout})
        if url.endswith("/birthdays/today"):
            return FakeResponse(self.birthday_payload)
        return FakeResponse(self.events)

    def post(self, url, json=None, timeout=None, headers=None):
        self.post_calls.append({"url": url, "json": json, "timeout": timeout, "headers": headers})
        if url.endswith("/send") and json and json.get("event_id") in self.fail_event_ids:
            return FakeResponse(status_code=500)
        if url.endswith("/send") and json and json.get("chat_id") in self.fail_event_ids:
            return FakeResponse(status_code=500)
        return FakeResponse({"ok": True, "filename": "backup_test.sql"})


def _install_fake_client(monkeypatch, events, fail_event_ids=None, birthday_payload=None):
    FakeClient.instances = []

    def factory():
        return FakeClient(events=events, fail_event_ids=fail_event_ids, birthday_payload=birthday_payload)

    monkeypatch.setattr(worker.httpx, "Client", factory)


def test_format_exam_control_reminder_includes_optional_fields():
    text = worker._format_exam_control_reminder(
        {
            "lesson_type": "exam",
            "subject": "Discrete Math",
            "room": "301",
            "teacher": "Dr. Ada",
            "time": "14:00:00",
            "end_time": "15:35:00",
            "body": "Bring ID",
        },
        "2026-05-20",
    )

    assert "Напоминание (2026-05-20)" in text
    assert "#Экзамен" in text
    assert "#Discrete_Math" in text
    assert "Аудитория: 301" in text
    assert "Преподаватель: Dr. Ada" in text
    assert "<b>Время проведения: 14:00 - 15:35</b>" in text
    assert "Bring ID" in text


def test_format_exam_control_reminder_omits_time_when_missing():
    text = worker._format_exam_control_reminder(
        {
            "lesson_type": "exam",
            "subject": "Algebra",
            "body": "Bring ID",
        },
        "2026-05-20",
    )

    assert "Время проведения:" not in text


def test_format_exam_control_reminder_start_time_only():
    text = worker._format_exam_control_reminder(
        {
            "lesson_type": "control",
            "time": "09:00",
            "body": "Chapter 3",
        },
        "2026-05-21",
    )

    assert "<b>Время проведения: 09:00</b>\nChapter 3" in text


def test_check_and_send_handles_empty_reminders(monkeypatch):
    _install_fake_client(monkeypatch, events=[])

    worker.check_and_send()

    client = FakeClient.instances[0]
    assert client.get_calls == [{"url": "http://backend.test/events/due_reminders", "timeout": 10.0}]
    assert client.post_calls == []


def test_check_and_send_sends_reminder_and_marks_sent(monkeypatch):
    events = [
        {
            "id": 10,
            "type": "homework",
            "title": "Task",
            "body": "Solve it",
            "date": "2026-05-20",
            "room": "101",
            "teacher": "Teacher",
            "photo_urls": ["https://example.com/1.jpg"],
            "attachments": [{"url": "https://example.com/book.pdf", "kind": "document"}],
            "chat_id": 123,
            "thread_id": 456,
        }
    ]
    _install_fake_client(monkeypatch, events=events)

    worker.check_and_send()

    client = FakeClient.instances[0]
    assert client.post_calls[0]["url"] == "http://bot-service.test/send"
    assert client.post_calls[0]["json"]["chat_id"] == 123
    assert client.post_calls[0]["json"]["thread_id"] == 456
    assert client.post_calls[0]["json"]["photos"] == ["https://example.com/1.jpg"]
    assert client.post_calls[0]["json"]["documents"] == ["https://example.com/book.pdf"]
    assert "Task" in client.post_calls[0]["json"]["text"]
    assert client.post_calls[1] == {
        "url": "http://backend.test/events/10/mark_reminder_sent",
        "json": None,
        "timeout": 5.0,
        "headers": None,
    }


def test_check_and_send_does_not_mark_failed_send(monkeypatch):
    events = [
        {
            "id": 11,
            "type": "homework",
            "body": "Will fail",
            "date": "2026-05-20",
            "chat_id": 500,
        }
    ]
    _install_fake_client(monkeypatch, events=events, fail_event_ids={500})

    worker.check_and_send()

    client = FakeClient.instances[0]
    assert len(client.post_calls) == 1
    assert client.post_calls[0]["url"] == "http://bot-service.test/send"


def test_check_and_send_continues_after_one_event_fails(monkeypatch):
    events = [
        {"id": 12, "type": "homework", "body": "fail", "date": "2026-05-20", "chat_id": 500},
        {
            "id": 13,
            "type": "exam_control",
            "lesson_type": "control",
            "subject": "Physics",
            "body": "Chapter 3",
            "date": "2026-05-21",
            "chat_id": 501,
        },
    ]
    _install_fake_client(monkeypatch, events=events, fail_event_ids={500})

    worker.check_and_send()

    client = FakeClient.instances[0]
    assert [call["url"] for call in client.post_calls] == [
        "http://bot-service.test/send",
        "http://bot-service.test/send",
        "http://backend.test/events/13/mark_reminder_sent",
    ]
    assert "#Контрольная_работа" in client.post_calls[1]["json"]["text"]


def test_check_and_send_sends_birthday_greetings_at_configured_time(monkeypatch):
    class _FakeDateTime:
        @classmethod
        def utcnow(cls):
            return cls.now()

        @classmethod
        def now(cls):
            return _RealDateTime(2026, 5, 27, 0, 10, 0)

    from datetime import datetime as _RealDateTime

    _install_fake_client(
        monkeypatch,
        events=[],
        birthday_payload={
            "chat_id": 321,
            "thread_id": 654,
            "birthdays": [
                {"full_name": "Иванов Иван Иванович", "age": 20},
            ],
        },
    )
    monkeypatch.setattr(worker, "datetime", _FakeDateTime)
    monkeypatch.setattr(worker, "BIRTHDAY_GREETING_TIME", "00:10")
    monkeypatch.setattr(worker, "_last_birthday_greeting_date", None)

    worker.check_and_send()

    client = FakeClient.instances[0]
    birthday_send = client.post_calls[0]
    assert birthday_send["url"] == "http://bot-service.test/send"
    assert birthday_send["json"]["chat_id"] == 321
    assert birthday_send["json"]["thread_id"] == 654
    assert "Сегодня День рождения у Иванов Иван Иванович." in birthday_send["json"]["text"]
    assert "Исполняется 20 лет." in birthday_send["json"]["text"]


def test_friday_db_backup_posts_to_admin_endpoint(monkeypatch):
    _install_fake_client(monkeypatch, events=[])
    monkeypatch.setattr(worker, "ADMIN_TOKEN", "secret-admin")
    monkeypatch.setattr(worker, "BACKEND_URL", "http://backend.test")

    worker.friday_db_backup()

    client = FakeClient.instances[0]
    assert len(client.post_calls) == 1
    call = client.post_calls[0]
    assert call["url"] == "http://backend.test/admin/backup"
    assert call["headers"]["X-ADMIN-TOKEN"] == "secret-admin"
