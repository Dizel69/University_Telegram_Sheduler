import pdfplumber
import os
import re

ICON_DIR = os.getenv("PARSER_ICON_DIR", "/app/icons")
os.makedirs(ICON_DIR, exist_ok=True)

TIME_RE = re.compile(r'(\d{1,2}[:\.]\d{2})\s*(?:–|-)\s*(\d{1,2}[:\.]\d{2})')
DATE_RE = re.compile(r'(\d{1,2}[.\-]\d{1,2}[.\-]\d{2,4})')
LECTURE_WORDS = ['лекц', 'лекция', 'лек']
SEMINAR_WORDS = ['семинар', 'сем']

def extract_images_from_page(page):
    """Извлекает изображения со страницы."""
    saved = []
    return saved  # упрощено для начала, потом добавим извлечение

def simple_normalize_text(text: str) -> str:
    """Нормализует текст (удаляет переносы строк, множественные пробелы)."""
    return ' '.join(text.replace('\r', ' ').split())

def guess_type_from_text(text: str) -> str:
    """Угадывает тип события по тексту (лекция, семинар, практика)."""
    low = text.lower()
    for w in LECTURE_WORDS:
        if w in low:
            return "lecture"
    for w in SEMINAR_WORDS:
        if w in low:
            return "seminar"
    if 'практик' in low or 'лаб' in low:
        return "practice"
    return "unknown"

def extract_times(text: str):
    """Извлекает время начала и окончания из текста."""
    m = TIME_RE.search(text)
    if m:
        return m.group(1).replace('.', ':'), m.group(2).replace('.', ':')
    return None, None

def extract_date(text: str):
    """Извлекает дату из текста."""
    m = DATE_RE.search(text)
    if m:
        return m.group(1)
    return None
