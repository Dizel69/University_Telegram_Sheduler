"""Единые подписи семестров для ДЗ (синхрон с frontend/src/semesterCalendar.js)."""
from __future__ import annotations

from typing import Optional, Tuple

SECOND_SEMESTER_LABEL = "Второй семестр"

_LEGACY: dict[str, str] = {
    "2": SECOND_SEMESTER_LABEL,
    "3": "Третий семестр",
    "4": "Четвёртый семестр",
    "2 семестр": SECOND_SEMESTER_LABEL,
    "3 семестр": "Третий семестр",
    "4 семестр": "Четвёртый семестр",
}


def legacy_semester_migrations() -> Tuple[Tuple[str, str], ...]:
    """Пары (как в БД) → каноническая подпись — для одноразового UPDATE при старте."""
    return tuple(_LEGACY.items())


def normalize_semester_label(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    t = str(value).strip()
    if not t:
        return None
    return _LEGACY.get(t, t)
