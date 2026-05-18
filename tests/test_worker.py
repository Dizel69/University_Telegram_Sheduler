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

    def __init__(self, events=None, fail_event_ids=None):
        self.events = events or []
        self.fail_event_ids = set(fail_event_ids or [])
        self.get_calls = []
        self.post_calls = []
        FakeClient.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def get(self, url, timeout):
        self.get_calls.append({"url": url, "timeout": timeout})
        return FakeResponse(self.events)

    def post(self, url, json=None, timeout=None):
        self.post_calls.append({"url": url, "json": json, "timeout": timeout})
        if url.endswith("/send") and json and json.get("event_id") in self.fail_event_ids:
            return FakeResponse(status_code=500)
        if url.endswith("/send") and json and json.get("chat_id") in self.fail_event_ids:
            return FakeResponse(status_code=500)
        return FakeResponse({"ok": True})


def _install_fake_client(monkeypatch, events, fail_event_ids=None):
    FakeClient.instances = []

    def factory():
        return FakeClient(events=events, fail_event_ids=fail_event_ids)

    monkeypatch.setattr(worker.httpx, "Client", factory)


def test_format_exam_control_reminder_includes_optional_fields():
    text = worker._format_exam_control_reminder(
        {
            "lesson_type": "exam",
            "subject": "Discrete Math",
            "room": "301",
            "teacher": "Dr. Ada",
            "body": "Bring ID",
        },
        "2026-05-20",
    )

    assert "Напоминание (2026-05-20)" in text
    assert "#Экзамен" in text
    assert "#Discrete_Math" in text
    assert "Аудитория: 301" in text
    assert "Преподаватель: Dr. Ada" in text
    assert "Bring ID" in text


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
    assert "Task" in client.post_calls[0]["json"]["text"]
    assert client.post_calls[1] == {
        "url": "http://backend.test/events/10/mark_reminder_sent",
        "json": None,
        "timeout": 5.0,
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
