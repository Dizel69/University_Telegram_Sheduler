"""Маршруты для карточек преподавателей (CRUD из админки)."""
import datetime as dt
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.database import engine
from app.deps import require_admin
from app.models import TeacherProfile
from app.schemas import (
    TeacherProfileCreate,
    TeacherProfilePublic,
    TeacherProfileUpdate,
)

router = APIRouter(tags=["teacher-profiles"])


def _to_public(row: TeacherProfile) -> dict:
    return {
        "id": row.id,
        "full_name": row.full_name,
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


@router.post("/teacher-profiles", response_model=TeacherProfilePublic)
def create_teacher_profile(
    payload: TeacherProfileCreate, _admin=Depends(require_admin)
):
    """Создать карточку преподавателя (только администратор)."""
    with Session(engine) as session:
        row = TeacherProfile(
            full_name=payload.full_name,
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
