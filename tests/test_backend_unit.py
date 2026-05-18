from datetime import datetime, timedelta

import jwt

from app.schemas import EventCreate, EventPublic
from app.security import JWT_ALG, JWT_SECRET, create_access_token, decode_token, hash_password, verify_password
from app.semester_utils import SECOND_SEMESTER_LABEL, legacy_semester_migrations, normalize_semester_label
from app.type_utils import canonical_event_type


def test_canonical_event_type_handles_known_aliases():
    assert canonical_event_type("Домашнее задание") == "homework"
    assert canonical_event_type("экзамен по математике") == "exam_control"
    assert canonical_event_type("контрольная") == "exam_control"
    assert canonical_event_type("Расписание") == "schedule"
    assert canonical_event_type("важное объявление") == "announcement"
    assert canonical_event_type("перенос пары") == "transfer"
    assert canonical_event_type("День рождения") == "birthday"


def test_canonical_event_type_returns_normalized_unknown_value():
    assert canonical_event_type("  Custom Type  ") == "custom type"
    assert canonical_event_type("") == ""


def test_normalize_semester_label_maps_legacy_values():
    assert normalize_semester_label("2") == SECOND_SEMESTER_LABEL
    assert normalize_semester_label("2 семестр") == SECOND_SEMESTER_LABEL
    assert normalize_semester_label("3 семестр") == "Третий семестр"
    assert normalize_semester_label("  Весна 2026  ") == "Весна 2026"
    assert normalize_semester_label("") is None
    assert normalize_semester_label(None) is None


def test_legacy_semester_migrations_are_stable_pairs():
    migrations = dict(legacy_semester_migrations())

    assert migrations["2"] == SECOND_SEMESTER_LABEL
    assert migrations["4 семестр"] == "Четвёртый семестр"


def test_password_hash_and_verify_roundtrip():
    password_hash = hash_password("secret")

    assert password_hash != "secret"
    assert verify_password("secret", password_hash) is True
    assert verify_password("wrong", password_hash) is False
    assert verify_password("secret", "not-a-bcrypt-hash") is False


def test_access_token_decode_roundtrip():
    token = create_access_token(42)

    assert decode_token(token) == 42
    assert decode_token("bad-token") is None


def test_decode_token_rejects_expired_and_missing_subject_tokens():
    expired = jwt.encode(
        {"sub": "42", "exp": datetime.utcnow() - timedelta(seconds=1)},
        JWT_SECRET,
        algorithm=JWT_ALG,
    )
    missing_sub = jwt.encode(
        {"exp": datetime.utcnow() + timedelta(minutes=1)},
        JWT_SECRET,
        algorithm=JWT_ALG,
    )

    assert decode_token(expired) is None
    assert decode_token(missing_sub) is None


def test_event_create_normalizes_empty_dates_times_and_semester():
    event = EventCreate(
        type="homework",
        body="Read chapter 1",
        date="",
        time="",
        end_time="",
        semester="2",
    )

    assert event.date is None
    assert event.time is None
    assert event.end_time is None
    assert event.semester == SECOND_SEMESTER_LABEL


def test_event_public_normalizes_legacy_semester_label():
    event = EventPublic(
        id=1,
        type="homework",
        body="Read chapter 1",
        semester="3 семестр",
    )

    assert event.semester == "Третий семестр"
