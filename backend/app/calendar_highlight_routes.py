import re
from datetime import date
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.database import engine
from app.deps import require_admin
from app.models import CalendarDayRangeHighlight
from app.schemas import CalendarDayRangeHighlightIn, CalendarDayRangeHighlightPublic

router = APIRouter(tags=["calendar"])

_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _parse_iso_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Некорректная дата в поле {field}") from exc


def _validate_item(item: CalendarDayRangeHighlightIn) -> None:
    if not _HEX_COLOR_RE.match(item.color.strip()):
        raise HTTPException(status_code=400, detail="Цвет должен быть в формате #rrggbb")
    start = _parse_iso_date(item.start, "start")
    end = _parse_iso_date(item.end, "end")
    if start > end:
        raise HTTPException(status_code=400, detail="Дата начала не может быть позже даты конца")


def _to_public(row: CalendarDayRangeHighlight) -> CalendarDayRangeHighlightPublic:
    return CalendarDayRangeHighlightPublic(
        id=row.id,
        start=row.start_date.isoformat(),
        end=row.end_date.isoformat(),
        color=row.color,
        stitch=row.stitch,
    )


@router.get("/calendar/day-range-highlights", response_model=List[CalendarDayRangeHighlightPublic])
def list_day_range_highlights():
    """Публичный список цветовых заливок диапазонов дней (для всех клиентов календаря)."""
    with Session(engine) as session:
        rows = session.exec(
            select(CalendarDayRangeHighlight).order_by(
                CalendarDayRangeHighlight.sort_order,
                CalendarDayRangeHighlight.id,
            )
        ).all()
        return [_to_public(r) for r in rows]


@router.put("/calendar/day-range-highlights", response_model=List[CalendarDayRangeHighlightPublic])
def replace_day_range_highlights(
    body: List[CalendarDayRangeHighlightIn],
    _admin: None = Depends(require_admin),
):
    """Заменить все заливки (только администратор)."""
    for item in body:
        _validate_item(item)

    with Session(engine) as session:
        for row in session.exec(select(CalendarDayRangeHighlight)).all():
            session.delete(row)
        session.commit()

        for idx, item in enumerate(body):
            start = _parse_iso_date(item.start, "start")
            end = _parse_iso_date(item.end, "end")
            session.add(
                CalendarDayRangeHighlight(
                    start_date=start,
                    end_date=end,
                    color=item.color.strip(),
                    stitch=item.stitch,
                    sort_order=idx,
                )
            )
        session.commit()

        rows = session.exec(
            select(CalendarDayRangeHighlight).order_by(
                CalendarDayRangeHighlight.sort_order,
                CalendarDayRangeHighlight.id,
            )
        ).all()
        return [_to_public(r) for r in rows]
