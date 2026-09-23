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


def test_slot_button_shows_room_or_link_not_aud_url():
    room = dm_bot._slot_button_text(
        {
            "subject": "Неклассические логики",
            "weekday_label": "Пн",
            "time": "14:00",
            "place_label": "ауд 200",
        }
    )
    link = dm_bot._slot_button_text(
        {
            "subject": "Методы искусственного интеллекта",
            "weekday_label": "Вт",
            "time": "15:55",
            "place_label": "ссылка",
        }
    )
    assert room == "Неклассические логики Пн 14:00 ауд 200"
    assert link == "Методы искусственного интеллекта Вт 15:55 ссылка"
    assert "ауд http" not in link
    assert "https://" not in link


def test_settings_keyboard_keeps_old_toggles_and_adds_lesson_block():
    user = {
        "dm_mirror_posts": False,
        "dm_morning_schedule": True,
        "dm_homework_reminder": False,
        "dm_homework_offset_hours": 12,
        "dm_lesson_soon": False,
        "dm_lesson_offset_minutes": 5,
        "dm_lesson_all": False,
        "dm_transfer_eve": False,
        "morning_time": "07:30",
        "lesson_slots": [
            {
                "token": "abc123def456",
                "subject": "Неклассические логики",
                "weekday_label": "Пн",
                "time": "14:00",
                "place_label": "ауд 200",
                "selected": True,
            }
        ],
    }
    keyboard = dm_bot._settings_keyboard(user)
    buttons = [button for row in keyboard["inline_keyboard"] for button in row]
    callbacks = [button["callback_data"] for button in buttons]
    assert "st:p:t" in callbacks
    assert "st:m:t" in callbacks
    assert "st:h:t" in callbacks
    assert "st:o:12" in callbacks
    assert "st:ls:t" in callbacks
    assert {"st:lm:5", "st:lm:10", "st:lm:30"} <= set(callbacks)
    assert "st:la:t" in callbacks
    assert "st:lk:abc123def456" in callbacks
    assert "st:tr:t" in callbacks
    assert callbacks[-1] == "st:out"
    assert all(len(item.encode("utf-8")) <= 64 for item in callbacks)
    texts = [button["text"] for button in buttons]
    assert "✓ Неклассические логики Пн 14:00 ауд 200" in texts
    assert any(text.startswith("Утреннее расписание") for text in texts)
    assert any(text.startswith("На все пары") for text in texts)
    assert any("переносах" in text for text in texts)
    html = dm_bot._settings_html(user)
    assert "Неклассические логики" not in html
    assert "первой парой" in html


@pytest.mark.asyncio
async def test_settings_callbacks_patch_lesson_without_touching_morning(monkeypatch):
    patches = []
    user = {
        "dm_mirror_posts": False,
        "dm_morning_schedule": False,
        "dm_homework_reminder": True,
        "dm_homework_offset_hours": 24,
        "dm_lesson_soon": False,
        "dm_lesson_offset_minutes": 5,
        "dm_lesson_all": False,
        "dm_transfer_eve": False,
        "lesson_slots": [],
        "morning_time": "07:30",
    }

    async def fake_tg(method, payload, raise_on_not_ok=False):
        return {"ok": True}

    async def fake_backend(method, path, json=None, params=None):
        if method == "PATCH":
            patches.append(json)

        class R:
            status_code = 200

            def json(self):
                return {"ok": True, "user": user}

        return R()

    monkeypatch.setattr(dm_bot, "tg", fake_tg)
    monkeypatch.setattr(dm_bot, "backend_call", fake_backend)

    async def click(data):
        await dm_bot.handle_callback(
            {
                "id": "cb",
                "from": {"id": 7},
                "data": data,
                "message": {"chat": {"id": 7, "type": "private"}, "message_id": 4, "text": "Настройки"},
            }
        )

    await click("st:m:t")
    await click("st:ls:t")
    await click("st:lm:10")
    await click("st:la:t")
    await click("st:lk:abc")
    await click("st:tr:t")
    await click("st:h:t")

    assert patches[0] == {"telegram_id": 7, "dm_morning_schedule": True}
    assert patches[1] == {"telegram_id": 7, "dm_lesson_soon": True}
    assert patches[2] == {"telegram_id": 7, "dm_lesson_offset_minutes": 10}
    assert patches[3] == {"telegram_id": 7, "dm_lesson_all": True}
    assert patches[4] == {"telegram_id": 7, "dm_lesson_slot_toggle": "abc"}
    assert patches[5] == {"telegram_id": 7, "dm_transfer_eve": True}
    assert patches[6] == {"telegram_id": 7, "dm_homework_reminder": False}
