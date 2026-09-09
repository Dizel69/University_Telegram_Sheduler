import html
import logging
import os
import time
from collections import defaultdict, deque

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from app.deps import optional_logged_in_user
from app.models import User
from app.schemas import FeedbackCreate

router = APIRouter(tags=["feedback"])
logger = logging.getLogger("feedback")

BOT_SERVICE_URL = os.getenv("BOT_SERVICE_URL", "http://bot:8081")

KIND_LABELS = {
    "bug": "🐛 Баг",
    "suggestion": "💡 Предложение",
}

_RATE_WINDOW_SEC = 600
_RATE_MAX = 5
_hits: dict[str, deque[float]] = defaultdict(deque)


def _feedback_chat_id() -> int | None:
    raw = (os.getenv("FEEDBACK_CHAT_ID") or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _rate_limit(ip: str) -> None:
    now = time.monotonic()
    q = _hits[ip]
    while q and now - q[0] > _RATE_WINDOW_SEC:
        q.popleft()
    if len(q) >= _RATE_MAX:
        raise HTTPException(status_code=429, detail="Слишком много сообщений, попробуйте позже")
    q.append(now)


def _esc(value: str) -> str:
    return html.escape(value, quote=False)


def _sender_label(user: User | None) -> str | None:
    if not user:
        return None
    parts = [user.last_name, user.first_name]
    if user.middle_name:
        parts.append(user.middle_name)
    name = " ".join(p for p in parts if p)
    login = (user.login or "").strip()
    if login:
        return f"{name} ({login})" if name else login
    return name or None


def _build_telegram_text(payload: FeedbackCreate, user: User | None) -> str:
    lines = [
        f"<b>{KIND_LABELS[payload.kind]}</b>",
        f"<b>{_esc(payload.title)}</b>",
        "",
        _esc(payload.body),
    ]
    meta: list[str] = []
    sender = _sender_label(user)
    if sender:
        meta.append(f"От: {_esc(sender)}")
    if payload.contact:
        meta.append(f"Контакт: {_esc(payload.contact)}")
    if payload.page:
        meta.append(f"Страница: <code>{_esc(payload.page)}</code>")
    if meta:
        lines.append("")
        lines.extend(meta)
    text = "\n".join(lines)
    return text[:4090]


@router.post("/feedback")
async def submit_feedback(
    payload: FeedbackCreate,
    request: Request,
    user: User | None = Depends(optional_logged_in_user),
):
    """
    Публичная обратная связь. Уходит в личный чат с ботом (FEEDBACK_CHAT_ID),
    не в групповую беседу расписания.
    """
    chat_id = _feedback_chat_id()
    if chat_id is None:
        raise HTTPException(
            status_code=503,
            detail="Обратная связь ещё не настроена (нужен FEEDBACK_CHAT_ID)",
        )
    if chat_id < 0:
        logger.warning(
            "FEEDBACK_CHAT_ID=%s похож на группу; для лички с ботом нужен положительный user id",
            chat_id,
        )

    client_ip = request.client.host if request.client else "unknown"
    _rate_limit(client_ip)

    bot_payload = {
        "chat_id": chat_id,
        "text": _build_telegram_text(payload, user),
    }
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(f"{BOT_SERVICE_URL}/send", json=bot_payload, timeout=15.0)
        except httpx.RequestError as exc:
            logger.warning("feedback bot-service unreachable: %s", exc)
            raise HTTPException(status_code=502, detail="Не удалось связаться с ботом") from exc

    if resp.status_code >= 400:
        detail_text = ""
        try:
            detail_text = str(resp.json())
        except Exception:
            detail_text = resp.text or ""
        logger.warning("feedback telegram send failed: %s %s", resp.status_code, detail_text[:400])
        lowered = detail_text.lower()
        if "can't initiate conversation" in lowered or "bot was blocked" in lowered:
            raise HTTPException(
                status_code=502,
                detail="Бот не может написать в личку: откройте бота в Telegram, нажмите /start и проверьте FEEDBACK_CHAT_ID",
            )
        raise HTTPException(status_code=502, detail="Не удалось отправить сообщение в Telegram")

    try:
        data = resp.json()
    except Exception:
        data = {}
    return {"ok": True, "message_id": data.get("message_id")}
