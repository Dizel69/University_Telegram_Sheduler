"""Личный Telegram-бот: long polling, логин, меню, ДЗ, настройки, ОС.

Исходящие вызовы только через bot_service._telegram_call (IPv6/IPv4 fallback).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

import httpx
from menu_keyboard import menu_keyboard
from telegram_html import sanitize_telegram_html

logger = logging.getLogger("bot-service.dm")

BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")
INTERNAL_TOKEN = (os.getenv("INTERNAL_SERVICE_TOKEN") or os.getenv("ADMIN_TOKEN") or "").strip()
GROUP_REFUSAL = "Напишите мне в личку."

BTN_TO_CMD = {
    "сегодня": "/сегодня",
    "завтра": "/завтра",
    "пара": "/пара",
    "дз": "/дз",
    "неделя": "/неделя",
    "настройки": "/настройки",
    "обратная связь": "/feedback",
    "/help": "/help",
    "/помощь": "/help",
}

MENU_COMMANDS = {
    "/сегодня",
    "/завтра",
    "/пара",
    "/дз",
    "/неделя",
    "/настройки",
    "/help",
    "/feedback",
    "/выход",
    "/start",
}

last_poll_ok_at: Optional[float] = None
polling_enabled = False


def _auth_headers() -> dict[str, str]:
    if not INTERNAL_TOKEN:
        return {}
    return {"X-INTERNAL-TOKEN": INTERNAL_TOKEN}


async def backend_call(method: str, path: str, *, json: dict | None = None, params: dict | None = None) -> httpx.Response:
    async with httpx.AsyncClient() as client:
        return await client.request(
            method,
            f"{BACKEND_URL}{path}",
            json=json,
            params=params,
            headers=_auth_headers(),
            timeout=20.0,
        )


async def tg(method: str, payload: dict, *, raise_on_not_ok: bool = False) -> dict:
    from bot_service import _telegram_call

    body = await _telegram_call(method, payload)
    if raise_on_not_ok and not body.get("ok"):
        logger.warning("Telegram %s not ok: %s", method, body)
    return body


async def send_text(
    chat_id: int,
    text: str,
    *,
    reply_markup: dict | None = None,
    reply_to: int | None = None,
    keep_menu: bool = False,
) -> dict:
    if keep_menu and reply_markup is None:
        reply_markup = menu_keyboard()
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": sanitize_telegram_html(text),
        "parse_mode": "HTML",
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    if reply_to is not None:
        payload["reply_to_message_id"] = reply_to
    body = await tg("sendMessage", payload)
    if body.get("ok"):
        return body
    logger.warning("sendMessage not ok chat=%s: %s", chat_id, body)
    markup = payload.get("reply_markup")
    if isinstance(markup, dict) and markup.get("is_persistent"):
        payload["reply_markup"] = menu_keyboard(persistent=False)
        body = await tg("sendMessage", payload)
        if body.get("ok"):
            return body
        logger.warning("sendMessage retry without is_persistent failed: %s", body)
    return body


async def delete_message(chat_id: int, message_id: int) -> None:
    try:
        await tg("deleteMessage", {"chat_id": chat_id, "message_id": message_id})
    except Exception:
        logger.info("deleteMessage skipped chat=%s msg=%s", chat_id, message_id)


def _cmd_from_text(text: str) -> Optional[str]:
    raw = (text or "").strip()
    if not raw:
        return None
    if raw.startswith("/"):
        token = raw.split()[0]
        token = token.split("@", 1)[0].lower()
        return token
    mapped = BTN_TO_CMD.get(raw.lower())
    return mapped


def _is_private(chat: dict) -> bool:
    return (chat.get("type") or "") == "private"


def _from_user(update_obj: dict) -> Optional[dict]:
    return update_obj.get("from") or update_obj.get("from_user")


async def _dialog(telegram_id: int) -> dict:
    resp = await backend_call("GET", "/internal/bot/dialog", params={"telegram_id": telegram_id})
    if resp.status_code >= 400:
        return {"state": "idle", "user": None}
    return resp.json()


async def _set_dialog(
    telegram_id: int,
    state: str,
    *,
    pending_login: str | None = None,
    login_message_id: int | None = None,
    pending_user_id: int | None = None,
) -> None:
    await backend_call(
        "PUT",
        "/internal/bot/dialog",
        json={
            "telegram_id": telegram_id,
            "state": state,
            "pending_login": pending_login,
            "login_message_id": login_message_id,
            "pending_user_id": pending_user_id,
        },
    )


def _mirror_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "Да, дублировать", "callback_data": "mr:1"},
                {"text": "Нет, только беседа", "callback_data": "mr:0"},
            ]
        ]
    }


def _hw_keyboard(event_id: int, url: str, telegram_id: int, *, done: bool = False) -> dict:
    row = []
    if not done:
        row.append({"text": "Сделано", "callback_data": f"hw:{event_id}:{telegram_id}"})
    row.append({"text": "Открыть на сайте", "url": url})
    return {"inline_keyboard": [row]}


def _settings_keyboard(user: dict) -> dict:
    def mark(on: bool) -> str:
        return "вкл" if on else "выкл"

    offset = int(user.get("dm_homework_offset_hours") or 24)
    offset_row = []
    for hours in (24, 12, 3, 1):
        prefix = "• " if hours == offset else ""
        offset_row.append({"text": f"{prefix}{hours}ч", "callback_data": f"st:o:{hours}"})
    return {
        "inline_keyboard": [
            [{"text": f"Зеркало постов: {mark(user.get('dm_mirror_posts'))}", "callback_data": "st:p:t"}],
            [{"text": f"Утреннее расписание: {mark(user.get('dm_morning_schedule'))}", "callback_data": "st:m:t"}],
            [{"text": f"Напоминание о ДЗ: {mark(user.get('dm_homework_reminder'))}", "callback_data": "st:h:t"}],
            offset_row,
            [{"text": "Выйти из аккаунта", "callback_data": "st:out"}],
        ]
    }


def _settings_html(user: dict) -> str:
    morning = user.get("morning_time") or "07:30"
    return (
        "<b>Настройки</b>\n"
        f"Зеркало постов из беседы: {'да' if user.get('dm_mirror_posts') else 'нет'}\n"
        f"Утреннее расписание ({morning} МСК): {'да' if user.get('dm_morning_schedule') else 'нет'}\n"
        f"Напоминание о незакрытом ДЗ: {'да' if user.get('dm_homework_reminder') else 'нет'}\n"
        f"За сколько часов: {int(user.get('dm_homework_offset_hours') or 24)}\n\n"
        "Если на сегодня пар нет, утреннее сообщение не отправляем."
    )


async def _require_user(telegram_id: int) -> Optional[dict]:
    resp = await backend_call("GET", "/internal/bot/me", params={"telegram_id": telegram_id})
    if resp.status_code >= 400:
        return None
    data = resp.json() or {}
    return data.get("user")


async def _send_menu(chat_id: int, text: str) -> None:
    await send_text(chat_id, text, reply_markup=menu_keyboard())


async def _ask_login(chat_id: int, telegram_id: int) -> None:
    await _set_dialog(telegram_id, "wait_login")
    await send_text(chat_id, "Введите логин с сайта")


async def _after_login_success(chat_id: int, user: dict, ask_mirror: bool) -> None:
    hello = f"Здравствуйте, {user.get('short_name') or 'студент'}."
    await _send_menu(chat_id, hello)
    if ask_mirror:
        await send_text(
            chat_id,
            "Хотите получать в этот чат копии сообщений, которые бот публикует в беседу группы "
            "(расписание, ДЗ, объявления)? Напоминания из общего чата сюда дублироваться не будут.",
            reply_markup=_mirror_keyboard(),
        )


async def handle_start(chat_id: int, telegram_id: int) -> None:
    user = await _require_user(telegram_id)
    if user:
        await _set_dialog(telegram_id, "idle")
        await _after_login_success(chat_id, user, ask_mirror=not user.get("dm_mirror_asked"))
        return
    await _ask_login(chat_id, telegram_id)


async def handle_logout(chat_id: int, telegram_id: int) -> None:
    await backend_call("POST", "/internal/bot/logout", json={"telegram_id": telegram_id})
    await send_text(
        chat_id,
        "Аккаунт отвязан. Напишите /start, чтобы войти снова.",
        reply_markup={"remove_keyboard": True},
    )


async def handle_login_text(chat_id: int, telegram_id: int, text: str, message_id: int, dialog: dict) -> None:
    state = dialog.get("state") or "idle"
    if state == "wait_login":
        login = text.strip()
        await _set_dialog(telegram_id, "wait_password", pending_login=login, login_message_id=message_id)
        await send_text(chat_id, "Введите пароль")
        return
    if state == "wait_password":
        login = dialog.get("pending_login") or ""
        login_msg_id = dialog.get("login_message_id")
        resp = await backend_call(
            "POST",
            "/internal/bot/login",
            json={"telegram_id": telegram_id, "login": login, "password": text},
        )
        await delete_message(chat_id, message_id)
        if login_msg_id:
            await delete_message(chat_id, int(login_msg_id))
        if resp.status_code == 401:
            await _set_dialog(telegram_id, "wait_login")
            await send_text(chat_id, "Неверный логин или пароль. Введите логин с сайта")
            return
        if resp.status_code == 409:
            await _set_dialog(telegram_id, "idle")
            await send_text(chat_id, resp.json().get("detail") or "Этот Telegram уже занят.")
            return
        if resp.status_code >= 400:
            await _set_dialog(telegram_id, "wait_login")
            await send_text(chat_id, "Не получилось войти. Попробуйте /start ещё раз.")
            return
        data = resp.json()
        if data.get("need_rebind"):
            await send_text(
                chat_id,
                data.get("message") or "Нужно подтверждение перепривязки.",
                reply_markup={
                    "inline_keyboard": [[{"text": "Перепривязать", "callback_data": "rb:1"}]]
                },
            )
            return
        user = data.get("user") or {}
        await _after_login_success(chat_id, user, ask_mirror=bool(data.get("ask_mirror")))


async def _auth_or_login(chat_id: int, telegram_id: int) -> Optional[dict]:
    user = await _require_user(telegram_id)
    if user:
        return user
    await send_text(chat_id, "Сначала войдите: /start")
    return None


async def handle_menu_command(chat_id: int, telegram_id: int, cmd: str) -> None:
    if cmd in {"/сегодня", "/завтра", "/пара", "/дз", "/неделя", "/настройки", "/feedback"}:
        if not await _auth_or_login(chat_id, telegram_id):
            return
    if cmd == "/сегодня":
        resp = await backend_call("GET", "/internal/bot/day", params={"telegram_id": telegram_id})
        await send_text(chat_id, (resp.json() or {}).get("html") or "Не удалось загрузить день.", keep_menu=True)
        return
    if cmd == "/завтра":
        resp = await backend_call(
            "GET", "/internal/bot/day", params={"telegram_id": telegram_id, "offset": 1}
        )
        await send_text(chat_id, (resp.json() or {}).get("html") or "Не удалось загрузить день.", keep_menu=True)
        return
    if cmd == "/пара":
        resp = await backend_call("GET", "/internal/bot/next-lesson", params={"telegram_id": telegram_id})
        await send_text(chat_id, (resp.json() or {}).get("html") or "Не удалось найти пару.", keep_menu=True)
        return
    if cmd == "/неделя":
        resp = await backend_call("GET", "/internal/bot/week", params={"telegram_id": telegram_id})
        await send_text(chat_id, (resp.json() or {}).get("html") or "Не удалось загрузить неделю.", keep_menu=True)
        return
    if cmd == "/дз":
        await _send_homework_list(chat_id, telegram_id)
        return
    if cmd == "/настройки":
        await _send_settings(chat_id, telegram_id)
        return
    if cmd == "/feedback":
        await _set_dialog(telegram_id, "wait_feedback")
        await send_text(chat_id, "Напишите одним сообщением баг или идею. /start или «Настройки» отменят отправку.")
        return
    if cmd == "/help":
        await send_text(
            chat_id,
            "Меню внизу экрана: Сегодня, Завтра, Пара, ДЗ, Неделя, Настройки, Обратная связь.\n"
            "Команды: /сегодня /завтра /пара /дз /неделя /настройки /выход /start",
            reply_markup=menu_keyboard(),
        )
        return
    if cmd == "/выход":
        await handle_logout(chat_id, telegram_id)


async def _send_homework_list(chat_id: int, telegram_id: int) -> None:
    resp = await backend_call("GET", "/internal/bot/homework", params={"telegram_id": telegram_id})
    data = resp.json() or {}
    items = data.get("items") or []
    if not items:
        await send_text(chat_id, data.get("html") or "Открытых ДЗ нет.", keep_menu=True)
        return
    await send_text(chat_id, data.get("html") or "<b>Открытые ДЗ</b>", keep_menu=True)
    for item in items:
        await send_text(
            chat_id,
            item.get("html") or "",
            reply_markup=_hw_keyboard(item["event_id"], item.get("url") or "", telegram_id),
        )


async def _send_settings(chat_id: int, telegram_id: int, *, message_id: int | None = None) -> None:
    user = await _require_user(telegram_id)
    if not user:
        await send_text(chat_id, "Сначала войдите: /start")
        return
    html = _settings_html(user)
    markup = _settings_keyboard(user)
    if message_id:
        await tg(
            "editMessageText",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": sanitize_telegram_html(html),
                "parse_mode": "HTML",
                "reply_markup": markup,
            },
        )
        return
    await send_text(chat_id, html, reply_markup=markup)


async def handle_callback(cb: dict) -> None:
    data = (cb.get("data") or "").strip()
    from_user = _from_user(cb) or {}
    telegram_id = from_user.get("id")
    msg = cb.get("message") or {}
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    message_id = msg.get("message_id")
    cb_id = cb.get("id")
    if not telegram_id or not chat_id:
        return

    if data.startswith("hw:"):
        parts = data.split(":")
        if len(parts) < 3:
            await tg("answerCallbackQuery", {"callback_query_id": cb_id})
            return
        try:
            event_id = int(parts[1])
            owner_tid = int(parts[2])
        except ValueError:
            await tg("answerCallbackQuery", {"callback_query_id": cb_id})
            return
        if owner_tid != int(telegram_id):
            await tg("answerCallbackQuery", {"callback_query_id": cb_id})
            return
        resp = await backend_call(
            "POST",
            f"/internal/bot/homework/{event_id}/done",
            json={"telegram_id": int(telegram_id)},
        )
        if resp.status_code == 401:
            await tg("answerCallbackQuery", {"callback_query_id": cb_id, "text": "Нет доступа"})
            return
        await tg("answerCallbackQuery", {"callback_query_id": cb_id, "text": "Отметили"})
        old_text = (msg.get("text") or "")
        url = ""
        markup = msg.get("reply_markup") or {}
        for row in markup.get("inline_keyboard") or []:
            for btn in row:
                if btn.get("url"):
                    url = btn["url"]
        new_html = (old_text + "\n✓ сделано").strip() if "✓ сделано" not in old_text else old_text
        await tg(
            "editMessageText",
            {
                "chat_id": int(chat_id),
                "message_id": message_id,
                "text": sanitize_telegram_html(new_html),
                "parse_mode": "HTML",
                "reply_markup": _hw_keyboard(event_id, url, int(telegram_id), done=True) if url else None,
            },
        )
        return

    if data.startswith("mr:"):
        on = data.endswith("1")
        await backend_call(
            "PATCH",
            "/internal/bot/settings",
            json={"telegram_id": int(telegram_id), "dm_mirror_posts": on, "dm_mirror_asked": True},
        )
        await tg("answerCallbackQuery", {"callback_query_id": cb_id})
        await _send_menu(int(chat_id), "Сохранили. Меню внизу экрана.")
        return

    if data == "rb:1":
        dialog = await _dialog(int(telegram_id))
        pending_login = dialog.get("pending_login")
        await tg("answerCallbackQuery", {"callback_query_id": cb_id})
        await _set_dialog(
            int(telegram_id),
            "wait_password_rebind",
            pending_login=pending_login,
            pending_user_id=dialog.get("pending_user_id"),
        )
        await send_text(int(chat_id), "Чтобы перепривязать, введите пароль ещё раз.")
        return

    if data.startswith("st:"):
        user = await _require_user(int(telegram_id))
        if not user:
            await tg("answerCallbackQuery", {"callback_query_id": cb_id, "text": "Сначала /start"})
            return
        parts = data.split(":")
        patch: dict[str, Any] = {"telegram_id": int(telegram_id)}
        if data == "st:out":
            await tg("answerCallbackQuery", {"callback_query_id": cb_id})
            await handle_logout(int(chat_id), int(telegram_id))
            return
        if parts[1] == "p":
            patch["dm_mirror_posts"] = not bool(user.get("dm_mirror_posts"))
        elif parts[1] == "m":
            patch["dm_morning_schedule"] = not bool(user.get("dm_morning_schedule"))
        elif parts[1] == "h":
            patch["dm_homework_reminder"] = not bool(user.get("dm_homework_reminder"))
        elif parts[1] == "o":
            patch["dm_homework_offset_hours"] = int(parts[2])
        await backend_call("PATCH", "/internal/bot/settings", json=patch)
        await tg("answerCallbackQuery", {"callback_query_id": cb_id})
        await _send_settings(int(chat_id), int(telegram_id), message_id=message_id)
        return

    await tg("answerCallbackQuery", {"callback_query_id": cb_id})


async def handle_message(message: dict) -> None:
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    from_user = _from_user(message) or {}
    telegram_id = from_user.get("id")
    text = message.get("text") or ""
    message_id = message.get("message_id")
    if not chat_id or not telegram_id:
        return

    if not _is_private(chat):
        cmd = _cmd_from_text(text)
        if cmd:
            await send_text(int(chat_id), GROUP_REFUSAL, reply_to=message_id)
        return

    dialog = await _dialog(int(telegram_id))
    state = dialog.get("state") or "idle"
    cmd = _cmd_from_text(text)

    if state == "wait_feedback":
        if cmd in {"/start", "/настройки"} or (text or "").strip().lower() == "настройки":
            await _set_dialog(int(telegram_id), "idle")
            if cmd == "/start":
                await handle_start(int(chat_id), int(telegram_id))
            else:
                await handle_menu_command(int(chat_id), int(telegram_id), "/настройки")
            return
        if cmd and cmd in MENU_COMMANDS:
            await _set_dialog(int(telegram_id), "idle")
            if cmd == "/выход":
                await handle_logout(int(chat_id), int(telegram_id))
            elif cmd == "/feedback":
                await handle_menu_command(int(chat_id), int(telegram_id), cmd)
            else:
                await handle_menu_command(int(chat_id), int(telegram_id), cmd)
            return
        resp = await backend_call(
            "POST",
            "/internal/bot/feedback",
            json={"telegram_id": int(telegram_id), "text": text},
        )
        if resp.status_code == 401:
            await send_text(int(chat_id), "Сначала войдите: /start")
            return
        if resp.status_code >= 400:
            detail = ""
            try:
                detail = str((resp.json() or {}).get("detail") or "")
            except Exception:
                detail = ""
            await send_text(int(chat_id), detail or "Не получилось отправить, попробуйте ещё раз.")
            return
        await send_text(int(chat_id), "Отправили, спасибо.", keep_menu=True)
        return

    if cmd == "/start":
        await handle_start(int(chat_id), int(telegram_id))
        return
    if cmd == "/выход":
        await handle_logout(int(chat_id), int(telegram_id))
        return

    if state in {"wait_login", "wait_password", "wait_password_rebind"} and not cmd:
        if state == "wait_password_rebind":
            login = dialog.get("pending_login") or ""
            resp = await backend_call(
                "POST",
                "/internal/bot/login",
                json={
                    "telegram_id": int(telegram_id),
                    "login": login,
                    "password": text,
                    "confirm_rebind": True,
                },
            )
            await delete_message(int(chat_id), int(message_id))
            if resp.status_code >= 400:
                await send_text(int(chat_id), "Не получилось перепривязать. /start")
                return
            data = resp.json()
            await _after_login_success(int(chat_id), data.get("user") or {}, ask_mirror=bool(data.get("ask_mirror")))
            return
        await handle_login_text(int(chat_id), int(telegram_id), text, int(message_id), dialog)
        return

    if cmd:
        await handle_menu_command(int(chat_id), int(telegram_id), cmd)
        return

    if not await _require_user(int(telegram_id)):
        await send_text(int(chat_id), "Чтобы пользоваться ботом, напишите /start и войдите логином с сайта.")
        return
    await send_text(int(chat_id), "Выберите пункт меню внизу экрана или /help", keep_menu=True)


async def handle_update(update: dict) -> None:
    if "callback_query" in update:
        await handle_callback(update["callback_query"])
        return
    if "message" in update:
        msg = update["message"]
        chat = msg.get("chat") or {}
        if (chat.get("type") or "") != "private":
            await handle_message(msg)
            return
        text = msg.get("text") or ""
        from_user = _from_user(msg) or {}
        tid = from_user.get("id")
        if tid:
            dialog = await _dialog(int(tid))
            if (dialog.get("state") or "").startswith("wait_password"):
                logger.info("update message chat=%s (password hidden)", chat.get("id"))
                await handle_message(msg)
                return
        logger.info("update message chat=%s text=%s", chat.get("id"), (text or "")[:80])
        await handle_message(msg)


async def poll_loop() -> None:
    global last_poll_ok_at, polling_enabled
    import time

    from bot_service import _telegram_call

    polling_enabled = True
    offset = 0
    try:
        await _telegram_call("deleteWebhook", {"drop_pending_updates": False})
    except Exception as exc:
        logger.warning("deleteWebhook: %s", exc)

    logger.info("Telegram long polling started")
    while True:
        try:
            body = await _telegram_call(
                "getUpdates",
                {
                    "offset": offset,
                    "timeout": 25,
                    "allowed_updates": ["message", "callback_query"],
                },
                long_poll=True,
            )
            if body.get("ok"):
                last_poll_ok_at = time.time()
                for upd in body.get("result") or []:
                    offset = int(upd.get("update_id") or 0) + 1
                    try:
                        await handle_update(upd)
                    except Exception:
                        logger.exception("handle_update failed")
            else:
                logger.warning("getUpdates not ok: %s", body)
                description = str((body.get("description") or "")).lower()
                if "conflict" in description or "webhook" in description:
                    try:
                        await _telegram_call("deleteWebhook", {"drop_pending_updates": False})
                    except Exception:
                        logger.exception("deleteWebhook after conflict")
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            polling_enabled = False
            raise
        except Exception:
            logger.exception("getUpdates failed")
            await asyncio.sleep(3)
