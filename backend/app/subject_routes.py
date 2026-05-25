import datetime as dt
import re
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Set

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app import database
from app.deps import require_admin
from app.models import Event, SubjectSetting, TeacherSetting
from app.schemas import (
    SubjectAdminList,
    SubjectAdminRow,
    SubjectAdminUpdate,
    SubjectAdminUpdateResult,
    TeacherAdminList,
    TeacherAdminRow,
    TeacherAdminUpdate,
    TeacherAdminUpdateResult,
)
from app.type_utils import canonical_event_type

router = APIRouter(tags=["subjects"])


def normalize_subject_key(value: Optional[str]) -> str:
    text = str(value or "").replace("\u00a0", " ").strip()
    text = re.sub(r"\s+", " ", text)
    return text.casefold()


def clean_subject_name(value: Optional[str]) -> str:
    text = str(value or "").replace("\u00a0", " ").strip()
    return re.sub(r"\s+", " ", text)


def event_subject_name(ev: Event) -> str:
    return clean_subject_name(ev.subject or ev.title)


def normalize_teacher_key(value: Optional[str]) -> str:
    return normalize_subject_key(value)


def clean_teacher_name(value: Optional[str]) -> str:
    return clean_subject_name(value)


def event_teacher_name(ev: Event) -> str:
    return clean_teacher_name(ev.teacher)


def _subject_settings(session: Session) -> Dict[str, SubjectSetting]:
    rows = session.exec(select(SubjectSetting)).all()
    return {row.subject_key: row for row in rows}


def _teacher_settings(session: Session) -> Dict[str, TeacherSetting]:
    rows = session.exec(select(TeacherSetting)).all()
    return {row.teacher_key: row for row in rows}


def _subject_groups(session: Session) -> Dict[str, dict]:
    groups: Dict[str, dict] = defaultdict(
        lambda: {
            "names": Counter(),
            "event_ids": set(),
            "schedule": 0,
            "homework": 0,
            "exam_control": 0,
            "transfer": 0,
            "announcement": 0,
        }
    )

    for ev in session.exec(select(Event)).all():
        name = event_subject_name(ev)
        if not name:
            continue
        key = normalize_subject_key(name)
        g = groups[key]
        g["names"][name] += 1
        if ev.id is not None:
            g["event_ids"].add(ev.id)
        kind = canonical_event_type(ev.type or "")
        if kind in ("schedule", "homework", "exam_control", "transfer", "announcement"):
            g[kind] += 1

    return groups


def _teacher_groups(session: Session) -> Dict[str, dict]:
    groups: Dict[str, dict] = defaultdict(
        lambda: {
            "names": Counter(),
            "event_ids": set(),
            "subjects": set(),
            "schedule": 0,
            "exam_control": 0,
            "transfer": 0,
        }
    )

    for ev in session.exec(select(Event)).all():
        name = event_teacher_name(ev)
        if not name:
            continue
        key = normalize_teacher_key(name)
        g = groups[key]
        g["names"][name] += 1
        if ev.id is not None:
            g["event_ids"].add(ev.id)
        subj = event_subject_name(ev)
        if subj:
            g["subjects"].add(subj)
        kind = canonical_event_type(ev.type or "")
        if kind in ("schedule", "exam_control", "transfer"):
            g[kind] += 1

    return groups


def _row_for_key(session: Session, subject_key: str) -> SubjectAdminRow:
    groups = _subject_groups(session)
    settings = _subject_settings(session)
    group = groups.get(subject_key)
    setting = settings.get(subject_key)

    if not group and not setting:
        raise HTTPException(status_code=404, detail="Предмет не найден")

    raw_names = sorted(group["names"].keys()) if group else []
    fallback_name = raw_names[0] if raw_names else (setting.display_name if setting else subject_key)
    display_name = setting.display_name if setting else fallback_name
    is_visible = setting.is_visible if setting else True

    return SubjectAdminRow(
        subject_key=subject_key,
        display_name=display_name,
        is_visible=is_visible,
        raw_names=raw_names,
        events_total=len(group["event_ids"]) if group else 0,
        schedule_count=group["schedule"] if group else 0,
        homework_count=group["homework"] if group else 0,
        exam_control_count=group["exam_control"] if group else 0,
        transfer_count=group["transfer"] if group else 0,
        announcement_count=group["announcement"] if group else 0,
    )


def _teacher_row_for_key(session: Session, teacher_key: str) -> TeacherAdminRow:
    groups = _teacher_groups(session)
    settings = _teacher_settings(session)
    group = groups.get(teacher_key)
    setting = settings.get(teacher_key)

    if not group and not setting:
        raise HTTPException(status_code=404, detail="Преподаватель не найден")

    raw_names = sorted(group["names"].keys()) if group else []
    fallback_name = raw_names[0] if raw_names else (setting.display_name if setting else teacher_key)
    display_name = setting.display_name if setting else fallback_name
    is_visible = setting.is_visible if setting else True

    return TeacherAdminRow(
        teacher_key=teacher_key,
        display_name=display_name,
        is_visible=is_visible,
        raw_names=raw_names,
        events_total=len(group["event_ids"]) if group else 0,
        schedule_count=group["schedule"] if group else 0,
        exam_control_count=group["exam_control"] if group else 0,
        transfer_count=group["transfer"] if group else 0,
        subjects=sorted(group["subjects"]) if group else [],
    )


def _visible_subject_keys(session: Session) -> Set[str]:
    return {
        row.subject_key
        for row in session.exec(select(SubjectSetting).where(SubjectSetting.is_visible == False)).all()  # noqa: E712
    }


def _hidden_teacher_keys(session: Session) -> Set[str]:
    return {
        row.teacher_key
        for row in session.exec(select(TeacherSetting).where(TeacherSetting.is_visible == False)).all()  # noqa: E712
    }


@router.get("/admin/subjects", response_model=SubjectAdminList)
def list_subjects(_admin=Depends(require_admin)):
    with Session(database.engine) as session:
        groups = _subject_groups(session)
        settings = _subject_settings(session)
        keys = set(groups.keys()) | set(settings.keys())
        rows = [_row_for_key(session, key) for key in keys]
        rows.sort(key=lambda r: (not r.is_visible, r.display_name.casefold()))
        return SubjectAdminList(subjects=rows)


@router.patch("/admin/subjects", response_model=SubjectAdminUpdateResult)
def update_subject(payload: SubjectAdminUpdate, _admin=Depends(require_admin)):
    old_key = normalize_subject_key(payload.subject_key)
    if not old_key:
        raise HTTPException(status_code=400, detail="Не указан предмет")

    with Session(database.engine) as session:
        groups = _subject_groups(session)
        settings = _subject_settings(session)
        if old_key not in groups and old_key not in settings:
            raise HTTPException(status_code=404, detail="Предмет не найден")

        current_row = _row_for_key(session, old_key)
        next_name = clean_subject_name(payload.display_name) if payload.display_name is not None else current_row.display_name
        if not next_name:
            raise HTTPException(status_code=400, detail="Название предмета не может быть пустым")

        target_key = normalize_subject_key(next_name)
        is_visible = current_row.is_visible if payload.is_visible is None else payload.is_visible
        updated_events = 0

        if payload.rename_events and target_key != old_key:
            for ev in session.exec(select(Event)).all():
                subj_key = normalize_subject_key(ev.subject)
                title_key = normalize_subject_key(ev.title) if not ev.subject else ""
                if subj_key == old_key:
                    ev.subject = next_name
                    session.add(ev)
                    updated_events += 1
                elif title_key == old_key:
                    ev.title = next_name
                    session.add(ev)
                    updated_events += 1
        elif payload.rename_events and next_name != current_row.display_name:
            for ev in session.exec(select(Event)).all():
                subj_key = normalize_subject_key(ev.subject)
                title_key = normalize_subject_key(ev.title) if not ev.subject else ""
                if subj_key == old_key:
                    ev.subject = next_name
                    session.add(ev)
                    updated_events += 1
                elif title_key == old_key:
                    ev.title = next_name
                    session.add(ev)
                    updated_events += 1

        old_setting = settings.get(old_key)
        if old_setting and old_key != target_key:
            session.delete(old_setting)
            session.flush()

        target_setting = session.exec(
            select(SubjectSetting).where(SubjectSetting.subject_key == target_key)
        ).first()
        if target_setting:
            target_setting.display_name = next_name
            target_setting.is_visible = is_visible
            target_setting.updated_at = dt.datetime.utcnow()
            session.add(target_setting)
        else:
            session.add(
                SubjectSetting(
                    subject_key=target_key,
                    display_name=next_name,
                    is_visible=is_visible,
                    updated_at=dt.datetime.utcnow(),
                )
            )

        session.commit()
        subject = _row_for_key(session, target_key)
        return SubjectAdminUpdateResult(ok=True, subject=subject, updated_events=updated_events)


@router.get("/admin/teachers", response_model=TeacherAdminList)
def list_teachers(_admin=Depends(require_admin)):
    with Session(database.engine) as session:
        groups = _teacher_groups(session)
        settings = _teacher_settings(session)
        keys = set(groups.keys()) | set(settings.keys())
        rows = [_teacher_row_for_key(session, key) for key in keys]
        rows.sort(key=lambda r: (not r.is_visible, r.display_name.casefold()))
        return TeacherAdminList(teachers=rows)


@router.patch("/admin/teachers", response_model=TeacherAdminUpdateResult)
def update_teacher(payload: TeacherAdminUpdate, _admin=Depends(require_admin)):
    old_key = normalize_teacher_key(payload.teacher_key)
    if not old_key:
        raise HTTPException(status_code=400, detail="Не указан преподаватель")

    with Session(database.engine) as session:
        groups = _teacher_groups(session)
        settings = _teacher_settings(session)
        if old_key not in groups and old_key not in settings:
            raise HTTPException(status_code=404, detail="Преподаватель не найден")

        current_row = _teacher_row_for_key(session, old_key)
        next_name = clean_teacher_name(payload.display_name) if payload.display_name is not None else current_row.display_name
        if not next_name:
            raise HTTPException(status_code=400, detail="Имя преподавателя не может быть пустым")

        target_key = normalize_teacher_key(next_name)
        is_visible = current_row.is_visible if payload.is_visible is None else payload.is_visible
        updated_events = 0

        if payload.rename_events and (target_key != old_key or next_name != current_row.display_name):
            for ev in session.exec(select(Event)).all():
                if normalize_teacher_key(ev.teacher) == old_key:
                    ev.teacher = next_name
                    session.add(ev)
                    updated_events += 1

        old_setting = settings.get(old_key)
        if old_setting and old_key != target_key:
            session.delete(old_setting)
            session.flush()

        target_setting = session.exec(
            select(TeacherSetting).where(TeacherSetting.teacher_key == target_key)
        ).first()
        if target_setting:
            target_setting.display_name = next_name
            target_setting.is_visible = is_visible
            target_setting.updated_at = dt.datetime.utcnow()
            session.add(target_setting)
        else:
            session.add(
                TeacherSetting(
                    teacher_key=target_key,
                    display_name=next_name,
                    is_visible=is_visible,
                    updated_at=dt.datetime.utcnow(),
                )
            )

        session.commit()
        teacher = _teacher_row_for_key(session, target_key)
        return TeacherAdminUpdateResult(ok=True, teacher=teacher, updated_events=updated_events)


def visible_subject_names_for_period(session: Session, start, end) -> List[str]:
    hidden = _visible_subject_keys(session)
    names: Set[str] = set()
    for ev in session.exec(
        select(Event).where(Event.date != None, Event.date >= start, Event.date <= end)  # noqa: E711
    ).all():
        name = event_subject_name(ev)
        if not name:
            continue
        if normalize_subject_key(name) in hidden:
            continue
        names.add(name)
    return sorted(names)


def hidden_teacher_names(session: Session) -> Set[str]:
    hidden = _hidden_teacher_keys(session)
    names: Set[str] = set()
    for ev in session.exec(select(Event)).all():
        name = event_teacher_name(ev)
        if name and normalize_teacher_key(name) in hidden:
            names.add(name)
    return names
