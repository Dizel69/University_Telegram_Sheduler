def canonical_event_type(t: str) -> str:
    """
    Возвращает каноничный английский токен для известных типов событий.
    """
    if not t:
        return t
    n = str(t).lower().strip()
    if "перенос" in n or "transfer" in n:
        return "transfer"
    if "домаш" in n or "homework" in n:
        return "homework"
    if "exam_control" in n or "контрольн" in n or "экзамен" in n:
        return "exam_control"
    if "распис" in n or "schedule" in n:
        return "schedule"
    if "объяв" in n or "announcement" in n:
        return "announcement"
    return n
