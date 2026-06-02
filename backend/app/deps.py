import os
import datetime as dt
from typing import Optional

from fastapi import Header, HTTPException
from sqlmodel import Session
from sqlalchemy import text

from app.database import engine
from app.models import User
from app.security import decode_token

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")


def _touch_last_seen(session: Session, uid: int) -> None:
    """Обновляет last_seen_at не чаще раза в минуту, чтобы не перегружать БД."""
    try:
        session.execute(
            text(
                """
                UPDATE app_user
                SET last_seen_at = CURRENT_TIMESTAMP
                WHERE id = :uid
                  AND (last_seen_at IS NULL OR last_seen_at < :cutoff)
                """
            ),
            {"uid": uid, "cutoff": dt.datetime.utcnow() - dt.timedelta(minutes=1)},
        )
        session.commit()
    except Exception:
        session.rollback()


def require_admin_token_header(x_admin_token: Optional[str] = Header(None)) -> bool:
    """
    Только проверка X-ADMIN-TOKEN (для /admin/validate и старого входа по секрету).
    """
    if not ADMIN_TOKEN:
        raise HTTPException(
            status_code=403,
            detail="Администраторские действия выключены для этого экземпляра",
        )
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Неверный токен администратора")
    return True


def _bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    p = authorization.strip()
    if p.lower().startswith("bearer "):
        return p[7:].strip()
    return None


def require_logged_in_user(authorization: Optional[str] = Header(None)) -> User:
    token = _bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Нужна авторизация")
    uid = decode_token(token)
    if uid is None:
        raise HTTPException(status_code=401, detail="Сессия недействительна")
    with Session(engine) as session:
        user = session.get(User, uid)
        if not user:
            raise HTTPException(status_code=401, detail="Пользователь не найден")
        _touch_last_seen(session, uid)
        return user


def require_admin(
    x_admin_token: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
):
    if ADMIN_TOKEN and x_admin_token == ADMIN_TOKEN:
        return
    token = _bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Нужны права администратора")
    uid = decode_token(token)
    if uid is None:
        raise HTTPException(status_code=401, detail="Нужны права администратора")
    with Session(engine) as session:
        user = session.get(User, uid)
        if not user or not user.is_admin:
            raise HTTPException(status_code=403, detail="Нужны права администратора")
        _touch_last_seen(session, uid)


def require_owner(
    x_admin_token: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
):
    if ADMIN_TOKEN and x_admin_token == ADMIN_TOKEN:
        return
    token = _bearer(authorization)
    if not token:
        raise HTTPException(status_code=403, detail="Только владелец может управлять пользователями")
    uid = decode_token(token)
    if uid is None:
        raise HTTPException(status_code=403, detail="Только владелец может управлять пользователями")
    with Session(engine) as session:
        user = session.get(User, uid)
        if not user or not user.is_owner:
            raise HTTPException(status_code=403, detail="Только владелец может управлять пользователями")
        _touch_last_seen(session, uid)
