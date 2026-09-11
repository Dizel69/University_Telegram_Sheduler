import pytest

import dm_bot


@pytest.mark.asyncio
async def test_group_commands_are_refused(monkeypatch):
    calls = []

    async def fake_tg(method, payload, raise_on_not_ok=False):
        calls.append((method, payload))
        return {"ok": True}

    monkeypatch.setattr(dm_bot, "tg", fake_tg)
    await dm_bot.handle_message(
        {
            "chat": {"id": -100123, "type": "supergroup"},
            "from": {"id": 42},
            "text": "/start",
            "message_id": 9,
        }
    )
    assert calls
    assert calls[0][0] == "sendMessage"
    assert "личк" in calls[0][1]["text"].lower()


@pytest.mark.asyncio
async def test_group_plain_text_is_ignored(monkeypatch):
    calls = []

    async def fake_tg(method, payload, raise_on_not_ok=False):
        calls.append((method, payload))
        return {"ok": True}

    monkeypatch.setattr(dm_bot, "tg", fake_tg)
    await dm_bot.handle_message(
        {
            "chat": {"id": -100123, "type": "group"},
            "from": {"id": 42},
            "text": "привет",
            "message_id": 9,
        }
    )
    assert calls == []


@pytest.mark.asyncio
async def test_private_start_asks_login(monkeypatch):
    sent = []

    async def fake_tg(method, payload, raise_on_not_ok=False):
        sent.append((method, payload))
        return {"ok": True}

    async def fake_backend(method, path, json=None, params=None):
        class R:
            status_code = 200

            def json(self):
                if path.endswith("/me"):
                    return {"user": None}
                return {"ok": True}

        return R()

    monkeypatch.setattr(dm_bot, "tg", fake_tg)
    monkeypatch.setattr(dm_bot, "backend_call", fake_backend)
    await dm_bot.handle_start(10, 99)
    assert any("логин" in (p.get("text") or "").lower() for _, p in sent)


@pytest.mark.asyncio
async def test_login_success_sends_menu_then_mirror_question(monkeypatch):
    sent = []

    async def fake_tg(method, payload, raise_on_not_ok=False):
        sent.append((method, payload))
        return {"ok": True}

    monkeypatch.setattr(dm_bot, "tg", fake_tg)
    await dm_bot._after_login_success(10, {"short_name": "Иванов И."}, ask_mirror=True)

    assert len(sent) == 2
    assert sent[0][1]["reply_markup"]["keyboard"][0][0]["text"] == "Сегодня"
    assert sent[1][1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "mr:1"


@pytest.mark.asyncio
async def test_homework_callback_ignores_foreign_user(monkeypatch):
    calls = []

    async def fake_tg(method, payload, raise_on_not_ok=False):
        calls.append((method, payload))
        return {"ok": True}

    async def fake_backend(method, path, json=None, params=None):
        raise AssertionError("backend should not mark homework for foreign callback")

    monkeypatch.setattr(dm_bot, "tg", fake_tg)
    monkeypatch.setattr(dm_bot, "backend_call", fake_backend)
    await dm_bot.handle_callback(
        {
            "id": "cb1",
            "from": {"id": 2},
            "data": "hw:15:1",
            "message": {"chat": {"id": 2, "type": "private"}, "message_id": 3, "text": "ДЗ"},
        }
    )
    assert calls[0][0] == "answerCallbackQuery"
    assert all(c[0] != "editMessageText" for c in calls)
