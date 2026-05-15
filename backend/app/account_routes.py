from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.database import MAX_APP_USERS, engine
from app.deps import require_logged_in_user, require_owner
from app.models import Event, HomeworkCompletion, User
from app.schemas import LoginRequest, LoginResponse, UserCreate, UserPublic, UserUpdate
from app.security import create_access_token, hash_password, verify_password
from app.type_utils import canonical_event_type

router = APIRouter(tags=["accounts"])


def _to_public(user: User) -> UserPublic:
    return UserPublic.from_orm(user)


@router.post("/auth/login", response_model=LoginResponse)
def login(body: LoginRequest):
    login_key = body.login.strip()
    if not login_key or not body.password:
        raise HTTPException(status_code=400, detail="Укажите логин и пароль")

    with Session(engine) as session:
        stmt = select(User).where(User.login == login_key)
        u = session.exec(stmt).first()
        if not u or not verify_password(body.password, u.password_hash):
            raise HTTPException(status_code=401, detail="Неверный логин или пароль")
        token = create_access_token(u.id)
        return LoginResponse(access_token=token, user=_to_public(u))


@router.get("/auth/me", response_model=UserPublic)
def auth_me(current: User = Depends(require_logged_in_user)):
    """Текущий пользователь по Bearer-токену."""
    with Session(engine) as session:
        u = session.get(User, current.id)
        if not u:
            raise HTTPException(status_code=401, detail="Пользователь не найден")
        return _to_public(u)


@router.get("/owner/users", response_model=List[UserPublic])
def list_users(_ok: None = Depends(require_owner)):
    with Session(engine) as session:
        users = session.exec(select(User).order_by(User.last_name, User.first_name)).all()
        return [_to_public(u) for u in users]


@router.post("/owner/users", response_model=UserPublic)
def create_user(payload: UserCreate, _ok: None = Depends(require_owner)):
    with Session(engine) as session:
        if len(session.exec(select(User)).all()) >= MAX_APP_USERS:
            raise HTTPException(status_code=400, detail=f"Не больше {MAX_APP_USERS} пользователей")

        ln = payload.login.strip()
        if session.exec(select(User).where(User.login == ln)).first():
            raise HTTPException(status_code=400, detail="Такой логин уже занят")

        u = User(
            last_name=payload.last_name.strip(),
            first_name=payload.first_name.strip(),
            middle_name=payload.middle_name.strip() if payload.middle_name else None,
            birth_date=payload.birth_date,
            login=ln,
            password_hash=hash_password(payload.password),
            is_admin=payload.is_admin,
            is_owner=False,
        )
        session.add(u)
        session.commit()
        session.refresh(u)
        return _to_public(u)


@router.patch("/owner/users/{user_id}", response_model=UserPublic)
def update_user(user_id: int, payload: UserUpdate, _ok: None = Depends(require_owner)):
    raw = payload.dict(exclude_unset=True)
    fields = {}
    for k, v in raw.items():
        if k == "is_admin":
            fields[k] = bool(v)
        elif v is not None:
            fields[k] = v
    if not fields:
        raise HTTPException(status_code=400, detail="Нет полей для обновления")

    with Session(engine) as session:
        u = session.get(User, user_id)
        if not u:
            raise HTTPException(status_code=404, detail="Пользователь не найден")

        if "is_admin" in fields and u.is_owner and not fields["is_admin"]:
            raise HTTPException(status_code=400, detail="У владельца должны быть права администратора")

        for key in ("last_name", "first_name", "middle_name", "birth_date", "is_admin"):
            if key in fields:
                val = fields[key]
                if key in ("last_name", "first_name") and isinstance(val, str):
                    val = val.strip()
                    if not val:
                        raise HTTPException(status_code=400, detail="Фамилия и имя не могут быть пустыми")
                setattr(u, key, val)

        if "password" in fields:
            u.password_hash = hash_password(fields["password"])

        if u.is_owner:
            u.is_admin = True

        session.add(u)
        session.commit()
        session.refresh(u)
        return _to_public(u)


@router.delete("/owner/users/{user_id}")
def delete_user(user_id: int, _ok: None = Depends(require_owner)):
    with Session(engine) as session:
        u = session.get(User, user_id)
        if not u:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        if u.is_owner:
            raise HTTPException(status_code=400, detail="Учётную запись владельца удалить нельзя")

        comps = session.exec(select(HomeworkCompletion).where(HomeworkCompletion.user_id == user_id)).all()
        for c in comps:
            session.delete(c)

        session.delete(u)
        session.commit()
    return {"ok": True}


@router.get("/homework-completion")
def list_homework_completions(current: User = Depends(require_logged_in_user)):
    with Session(engine) as session:
        rows = session.exec(select(HomeworkCompletion).where(HomeworkCompletion.user_id == current.id)).all()
        return {"event_ids": [r.event_id for r in rows]}


@router.post("/homework-completion/{event_id}")
def add_homework_completion(event_id: int, current: User = Depends(require_logged_in_user)):
    with Session(engine) as session:
        ev = session.get(Event, event_id)
        if not ev:
            raise HTTPException(status_code=404, detail="Событие не найдено")
        if canonical_event_type(ev.type or "") != "homework":
            raise HTTPException(status_code=400, detail="Можно отмечать только домашние задания")

        dup = session.exec(
            select(HomeworkCompletion).where(
                HomeworkCompletion.user_id == current.id,
                HomeworkCompletion.event_id == event_id,
            )
        ).first()
        if dup:
            return {"ok": True}

        hc = HomeworkCompletion(user_id=current.id, event_id=event_id)
        session.add(hc)
        session.commit()
    return {"ok": True}


@router.delete("/homework-completion/{event_id}")
def remove_homework_completion(event_id: int, current: User = Depends(require_logged_in_user)):
    with Session(engine) as session:
        row = session.exec(
            select(HomeworkCompletion).where(
                HomeworkCompletion.user_id == current.id,
                HomeworkCompletion.event_id == event_id,
            )
        ).first()
        if not row:
            return {"ok": True}
        session.delete(row)
        session.commit()
    return {"ok": True}
