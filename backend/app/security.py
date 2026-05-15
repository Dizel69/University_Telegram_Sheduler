import os
from datetime import datetime, timedelta

import bcrypt
import jwt

JWT_SECRET = os.getenv("JWT_SECRET", "dev-change-me-in-production")
JWT_ALG = "HS256"
JWT_EXPIRE_DAYS = int(os.getenv("JWT_EXPIRE_DAYS", "7"))


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user_id: int) -> str:
    exp = datetime.utcnow() + timedelta(days=JWT_EXPIRE_DAYS)
    payload = {"sub": str(user_id), "exp": exp}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def decode_token(token: str) -> int | None:
    try:
        data = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
        sub = data.get("sub")
        if sub is None:
            return None
        return int(sub)
    except Exception:
        return None
