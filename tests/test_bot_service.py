import subprocess

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import bot_service


def test_health_and_metrics_routes():
    client = TestClient(bot_service.app)

    assert client.get("/health").json() == {"ok": True}

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "text/plain" in metrics.headers["content-type"]
    body = metrics.text
    assert "telegram_messages_sent_total" in body
    assert "telegram_send_errors_total" in body
    assert "telegram_unreachable_total" in body
    assert "telegram_request_duration_seconds" in body


def test_send_message_maps_thread_id_and_message_id(monkeypatch):
    async def fake_telegram_call(method, payload):
        assert method == "sendMessage"
        assert payload == {"chat_id": 123, "text": "hello", "message_thread_id": 456, "parse_mode": "HTML"}
        return {"ok": True, "result": {"message_id": 99}}

    monkeypatch.setattr(bot_service, "_telegram_call", fake_telegram_call)
    client = TestClient(bot_service.app)

    response = client.post("/send", json={"chat_id": 123, "thread_id": 456, "text": "hello"})

    assert response.status_code == 200
    assert response.json() == {"ok": True, "message_id": 99}


def test_send_message_with_single_photo_uses_send_photo(monkeypatch):
    async def fake_telegram_call(method, payload):
        assert method == "sendPhoto"
        assert payload["chat_id"] == 123
        assert payload["photo"] == "https://example.com/a.jpg"
        assert payload["caption"] == "hello"
        assert payload["parse_mode"] == "HTML"
        return {"ok": True, "result": {"message_id": 101}}

    monkeypatch.setattr(bot_service, "_telegram_call", fake_telegram_call)
    client = TestClient(bot_service.app)

    response = client.post(
        "/send",
        json={"chat_id": 123, "text": "hello", "photos": ["https://example.com/a.jpg"]},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "message_id": 101}


def test_send_message_with_multiple_photos_uses_media_group(monkeypatch):
    async def fake_telegram_call(method, payload):
        assert method == "sendMediaGroup"
        assert payload["chat_id"] == 123
        assert len(payload["media"]) == 2
        assert payload["media"][0]["caption"] == "hello"
        assert payload["media"][0]["parse_mode"] == "HTML"
        return {"ok": True, "result": [{"message_id": 201}, {"message_id": 202}]}

    monkeypatch.setattr(bot_service, "_telegram_call", fake_telegram_call)
    client = TestClient(bot_service.app)

    response = client.post(
        "/send",
        json={
            "chat_id": 123,
            "text": "hello",
            "photos": ["https://example.com/a.jpg", "https://example.com/b.jpg"],
        },
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "message_id": 201}


def test_send_message_with_document_uses_send_document(monkeypatch):
    calls = []

    async def fake_telegram_call(method, payload):
        calls.append((method, payload))
        return {"ok": True, "result": {"message_id": 303}}

    monkeypatch.setattr(bot_service, "_telegram_call", fake_telegram_call)
    client = TestClient(bot_service.app)

    response = client.post(
        "/send",
        json={"chat_id": 123, "text": "book", "documents": ["https://example.com/book.pdf"]},
    )

    assert response.status_code == 200
    assert calls[0][0] == "sendDocument"
    assert calls[0][1]["document"] == "https://example.com/book.pdf"
    assert calls[0][1]["caption"] == "book"
    assert calls[0][1]["parse_mode"] == "HTML"


def test_sanitize_telegram_html_keeps_supported_tags_and_escapes_text():
    from telegram_html import sanitize_telegram_html

    html = sanitize_telegram_html(
        "#Объявление\n<b>bold</b> <i>it</i> <u>un</u> <s>st</s> "
        "<span class='tg-spoiler'>hid</span> A & B <script>x</script>"
    )

    assert "<b>bold</b>" in html
    assert "<i>it</i>" in html
    assert "<u>un</u>" in html
    assert "<s>st</s>" in html
    assert "<tg-spoiler>hid</tg-spoiler>" in html
    assert "A &amp; B" in html
    assert "<script>" not in html
    assert "x" in html
    assert sanitize_telegram_html("<b><i><u><s>all</s></u></i></b>") == "<b><i><u><s>all</s></u></i></b>"
    assert sanitize_telegram_html("<code><b>x</b></code>") == "<code>x</code>"


def test_send_message_preserves_telegram_html_and_sets_parse_mode(monkeypatch):
    async def fake_telegram_call(method, payload):
        assert method == "sendMessage"
        assert payload["parse_mode"] == "HTML"
        assert payload["text"] == "<b>Hello</b> A &amp; B"
        return {"ok": True, "result": {"message_id": 11}}

    monkeypatch.setattr(bot_service, "_telegram_call", fake_telegram_call)
    client = TestClient(bot_service.app)

    response = client.post(
        "/send",
        json={"chat_id": 123, "text": "<b>Hello</b> A & B"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "message_id": 11}


def test_send_message_returns_502_for_telegram_error(monkeypatch):
    async def fake_telegram_call(method, payload):
        return {"ok": False, "description": "chat not found"}

    monkeypatch.setattr(bot_service, "_telegram_call", fake_telegram_call)
    client = TestClient(bot_service.app)

    response = client.post("/send", json={"chat_id": 123, "text": "hello"})

    assert response.status_code == 502
    assert "Telegram API error" in response.json()["detail"]


def test_create_topic_returns_thread_id(monkeypatch):
    async def fake_telegram_call(method, payload):
        assert method == "createForumTopic"
        assert payload == {"chat_id": 123, "name": "Homework"}
        return {"ok": True, "result": {"message_thread_id": 777}}

    monkeypatch.setattr(bot_service, "_telegram_call", fake_telegram_call)
    client = TestClient(bot_service.app)

    response = client.post("/create_topic", json={"chat_id": 123, "name": "Homework"})

    assert response.status_code == 200
    assert response.json() == {"ok": True, "message_thread_id": 777}


@pytest.mark.asyncio
async def test_telegram_call_falls_back_between_routes(monkeypatch):
    calls = []

    async def fake_run_curl(args):
        calls.append(args)
        if len(calls) < 3:
            return subprocess.CompletedProcess(args, returncode=28, stdout="", stderr="timeout")
        return subprocess.CompletedProcess(
            args,
            returncode=0,
            stdout='{"ok": true, "result": {"message_id": 5}}',
            stderr="",
        )

    monkeypatch.setattr(bot_service, "_run_curl", fake_run_curl)

    body = await bot_service._telegram_call("sendMessage", {"chat_id": 1, "text": "hello"})

    assert body == {"ok": True, "result": {"message_id": 5}}
    assert "-6" in calls[0]
    assert "-4" in calls[1]
    assert "--resolve" not in calls[2]


@pytest.mark.asyncio
async def test_telegram_call_raises_for_invalid_json(monkeypatch):
    async def fake_run_curl(args):
        return subprocess.CompletedProcess(args, returncode=0, stdout="not-json", stderr="")

    monkeypatch.setattr(bot_service, "_run_curl", fake_run_curl)

    with pytest.raises(HTTPException) as exc:
        await bot_service._telegram_call("sendMessage", {"chat_id": 1, "text": "hello"})

    assert exc.value.status_code == 502
    assert exc.value.detail == "Telegram returned invalid JSON"


@pytest.mark.asyncio
async def test_telegram_call_raises_after_all_routes_fail(monkeypatch):
    async def fake_run_curl(args):
        return subprocess.CompletedProcess(args, returncode=7, stdout="", stderr="unreachable")

    async def fake_sleep(seconds):
        return None

    monkeypatch.setattr(bot_service, "_run_curl", fake_run_curl)
    monkeypatch.setattr(bot_service.asyncio, "sleep", fake_sleep)

    with pytest.raises(HTTPException) as exc:
        await bot_service._telegram_call("sendMessage", {"chat_id": 1, "text": "hello"})

    assert exc.value.status_code == 502
    assert "Telegram unreachable" in exc.value.detail
