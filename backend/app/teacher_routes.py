"""Маршруты для карточек преподавателей (CRUD из админки)."""
import datetime as dt
import re
from typing import Iterable, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.database import engine
from app.deps import require_admin
from app.models import Event, TeacherProfile
from app.schemas import (
    TeacherProfileCreate,
    TeacherProfilePublic,
    TeacherProfileUpdate,
)

router = APIRouter(tags=["teacher-profiles"])


def _clean_name(value: Optional[str]) -> str:
    text = str(value or "").replace("\u00a0", " ").strip()
    return re.sub(r"\s+", " ", text)


def _event_subject_name(ev: Event) -> str:
    return _clean_name(getattr(ev, "subject", None) or getattr(ev, "title", None))


def _merge_subjects(existing: Iterable[str], additions: Iterable[str]) -> List[str]:
    """Объединяет списки предметов без учёта регистра, убирает дубли, сортирует."""
    result: List[str] = []
    seen = set()
    for s in list(existing or []) + list(additions or []):
        name = _clean_name(s)
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(name)
    result.sort(key=lambda s: s.casefold())
    return result


def touch_teacher_profile(teacher: Optional[str], subject: Optional[str]) -> None:
    """
    Гарантирует наличие карточки преподавателя и дополняет список её предметов.
    Вызывается при создании/обновлении события. Никогда не перезаписывает
    заполненные вручную поля (кафедра, связь, описание) и не роняет запрос.
    """
    name = _clean_name(teacher)
    if not name:
        return
    subj = _clean_name(subject)
    key = name.casefold()
    try:
        with Session(engine) as session:
            profiles = session.exec(select(TeacherProfile)).all()
            profile = next(
                (p for p in profiles if _clean_name(p.full_name).casefold() == key),
                None,
            )
            if profile is None:
                session.add(
                    TeacherProfile(full_name=name, subjects=[subj] if subj else [])
                )
                session.commit()
                return
            if subj:
                merged = _merge_subjects(profile.subjects, [subj])
                if merged != list(profile.subjects or []):
                    profile.subjects = merged
                    profile.updated_at = dt.datetime.utcnow()
                    session.add(profile)
                    session.commit()
    except Exception:
        # Авто-синхронизация не должна мешать сохранению события
        pass


def sync_teacher_profiles_from_events() -> dict:
    """
    Создаёт карточки для всех преподавателей из событий и дополняет их предметы.
    Заполненные вручную поля не трогаются. Возвращает статистику.
    """
    with Session(engine) as session:
        mapping: dict = {}
        for ev in session.exec(select(Event)).all():
            name = _clean_name(ev.teacher)
            if not name:
                continue
            entry = mapping.setdefault(name.casefold(), {"name": name, "subjects": set()})
            subj = _event_subject_name(ev)
            if subj:
                entry["subjects"].add(subj)

        profiles = session.exec(select(TeacherProfile)).all()
        by_key = {_clean_name(p.full_name).casefold(): p for p in profiles}

        created = 0
        updated = 0
        for key, entry in mapping.items():
            profile = by_key.get(key)
            if profile is None:
                session.add(
                    TeacherProfile(
                        full_name=entry["name"],
                        subjects=_merge_subjects([], entry["subjects"]),
                    )
                )
                created += 1
            else:
                merged = _merge_subjects(profile.subjects, entry["subjects"])
                if merged != list(profile.subjects or []):
                    profile.subjects = merged
                    profile.updated_at = dt.datetime.utcnow()
                    session.add(profile)
                    updated += 1
        session.commit()
    return {"ok": True, "created": created, "updated": updated, "teachers_in_events": len(mapping)}


def _to_public(row: TeacherProfile) -> dict:
    return {
        "id": row.id,
        "full_name": row.full_name,
        "academic_degree": row.academic_degree,
        "position": row.position,
        "department": row.department,
        "contact": row.contact,
        "subjects": list(row.subjects or []),
        "bio": row.bio,
    }


@router.get("/teacher-profiles", response_model=List[TeacherProfilePublic])
def list_teacher_profiles():
    """Список карточек преподавателей (доступен всем для отображения)."""
    with Session(engine) as session:
        rows = session.exec(
            select(TeacherProfile).order_by(TeacherProfile.full_name)
        ).all()
    return [_to_public(r) for r in rows]


@router.post("/teacher-profiles/sync")
def sync_teacher_profiles(_admin=Depends(require_admin)):
    """Заполнить карточки преподавателей на основе истории событий (только админ)."""
    return sync_teacher_profiles_from_events()


@router.post("/teacher-profiles", response_model=TeacherProfilePublic)
def create_teacher_profile(
    payload: TeacherProfileCreate, _admin=Depends(require_admin)
):
    """Создать карточку преподавателя (только администратор)."""
    with Session(engine) as session:
        row = TeacherProfile(
            full_name=payload.full_name,
            academic_degree=payload.academic_degree,
            position=payload.position,
            department=payload.department,
            contact=payload.contact,
            subjects=payload.subjects or [],
            bio=payload.bio,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _to_public(row)


@router.put("/teacher-profiles/{profile_id}", response_model=TeacherProfilePublic)
def update_teacher_profile(
    profile_id: int,
    payload: TeacherProfileUpdate,
    _admin=Depends(require_admin),
):
    """Обновить карточку преподавателя (только администратор)."""
    data = payload.dict(exclude_unset=True)
    with Session(engine) as session:
        row = session.get(TeacherProfile, profile_id)
        if not row:
            raise HTTPException(status_code=404, detail="Преподаватель не найден")
        for field, value in data.items():
            if field == "subjects" and value is None:
                continue
            setattr(row, field, value)
        row.updated_at = dt.datetime.utcnow()
        session.add(row)
        session.commit()
        session.refresh(row)
        return _to_public(row)


@router.delete("/teacher-profiles/{profile_id}")
def delete_teacher_profile(profile_id: int, _admin=Depends(require_admin)):
    """Удалить карточку преподавателя (только администратор)."""
    with Session(engine) as session:
        row = session.get(TeacherProfile, profile_id)
        if not row:
            raise HTTPException(status_code=404, detail="Преподаватель не найден")
        session.delete(row)
        session.commit()
    return {"ok": True, "deleted": profile_id}
