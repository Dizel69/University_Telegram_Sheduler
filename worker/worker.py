import os
import time as _time
import httpx
from apscheduler.schedulers.blocking import BlockingScheduler
from datetime import datetime
from prometheus_client import start_http_server, Counter, Gauge

BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")
BOT_SERVICE_URL = os.getenv("BOT_SERVICE_URL", "http://bot:8081")
POLL_INTERVAL = int(os.getenv("WORKER_POLL_INTERVAL", "60"))
BIRTHDAY_GREETING_TIME = os.getenv("BIRTHDAY_GREETING_TIME", "00:10")
METRICS_PORT = int(os.getenv("WORKER_METRICS_PORT", "9101"))
TELEGRAM_PROBE_URL = os.getenv("TELEGRAM_PROBE_URL", "https://api.telegram.org")

# Prometheus-метрики воркера
WORKER_RUNS = Counter("worker_runs_total", "Количество циклов опроса воркера")
WORKER_REMINDERS_SENT = Counter("worker_reminders_sent_total", "Успешно отправленные напоминания")
WORKER_REMINDERS_FAILED = Counter("worker_reminders_failed_total", "Неуспешные отправки напоминаний")
WORKER_BIRTHDAYS_SENT = Counter("worker_birthday_greetings_sent_total", "Отправленные поздравления с днём рождения")
WORKER_LAST_RUN = Gauge("worker_last_run_timestamp_seconds", "Время последнего цикла (unixtime)")
WORKER_DUE_REMINDERS = Gauge("worker_due_reminders", "Сколько напоминаний были к отправке в последнем цикле")
TELEGRAM_REACHABLE = Gauge("worker_telegram_reachable", "Доступен ли Telegram из воркера (1 — да, 0 — нет)")
TELEGRAM_PROBE_LATENCY = Gauge("worker_telegram_probe_seconds", "Время отклика проверки доступности Telegram")

scheduler = BlockingScheduler()
_last_birthday_greeting_date = None


def _probe_telegram():
    """Проверяет, доступен ли Telegram напрямую из воркера, и пишет gauge."""
    started = _time.perf_counter()
    try:
        resp = httpx.get(TELEGRAM_PROBE_URL, timeout=5.0)
        TELEGRAM_REACHABLE.set(1 if resp.status_code < 500 else 0)
    except Exception as e:
        print("⚠️ Worker: Telegram недоступен:", e)
        TELEGRAM_REACHABLE.set(0)
    finally:
        TELEGRAM_PROBE_LATENCY.set(_time.perf_counter() - started)


def _age_word(age: int) -> str:
    value = abs(int(age))
    if value % 10 == 1 and value % 100 != 11:
        return "год"
    if value % 10 in (2, 3, 4) and value % 100 not in (12, 13, 14):
        return "года"
    return "лет"


def _is_birthday_window(now_local: datetime) -> bool:
    try:
        hh, mm = BIRTHDAY_GREETING_TIME.split(":", 1)
        return now_local.hour == int(hh) and now_local.minute == int(mm)
    except Exception:
        return now_local.hour == 0 and now_local.minute == 10


def _send_birthday_greetings(client: httpx.Client):
    global _last_birthday_greeting_date
    now_local = datetime.now()
    today = now_local.date().isoformat()

    if not _is_birthday_window(now_local):
        return
    if _last_birthday_greeting_date == today:
        return

    r = client.get(f"{BACKEND_URL}/birthdays/today", timeout=10.0)
    r.raise_for_status()
    data = r.json() or {}
    birthdays = data.get("birthdays") or []
    chat_id = data.get("chat_id")
    thread_id = data.get("thread_id")

    for row in birthdays:
        full_name = (row.get("full_name") or "").strip()
        age = row.get("age")
        if not full_name or age is None:
            continue
        text = (
            f"Сегодня День рождения у {full_name}.\n"
            f"Исполняется {age} {_age_word(int(age))}.\n"
            "Поздравляем с днем рождения! 🎉"
        )
        payload = {
            "chat_id": chat_id,
            "thread_id": thread_id,
            "text": text
        }
        resp = client.post(f"{BOT_SERVICE_URL}/send", json=payload, timeout=10.0)
        resp.raise_for_status()
        WORKER_BIRTHDAYS_SENT.inc()

    _last_birthday_greeting_date = today


def _format_exam_control_reminder(ev: dict, date) -> str:
    """Тот же шаблон, что и при отправке события в Telegram (контрольная / экзамен)."""
    lines = [f"⏰ Напоминание ({date})", ""]
    lt = ev.get("lesson_type")
    lines.append("#Экзамен" if lt == "exam" else "#Контрольная_работа")
    subj = ev.get("subject")
    if subj and str(subj).strip():
        lines.append("#" + str(subj).strip().replace(" ", "_"))
    room = ev.get("room")
    if room and str(room).strip():
        lines.append(f"Аудитория: {str(room).strip()}")
    teacher = ev.get("teacher")
    if teacher and str(teacher).strip():
        lines.append(f"Преподаватель: {str(teacher).strip()}")
    body = (ev.get("body") or "").strip()
    if body:
        lines.append(body)
    return "\n".join(lines)


@scheduler.scheduled_job('interval', seconds=POLL_INTERVAL)
def check_and_send():
    """Проверяет и отправляет напоминания о предстоящих событиях."""
    print(datetime.utcnow().isoformat(), "Worker: проверка напоминаний")
    WORKER_RUNS.inc()
    WORKER_LAST_RUN.set(_time.time())
    _probe_telegram()
    try:
        with httpx.Client() as client:
            try:
                _send_birthday_greetings(client)
            except Exception as e:
                print("⚠️ Worker: ошибка отправки поздравлений с днём рождения:", e)
            r = client.get(f"{BACKEND_URL}/events/due_reminders", timeout=10.0)
            r.raise_for_status()
            events = r.json()
            WORKER_DUE_REMINDERS.set(len(events) if isinstance(events, list) else 0)
            for ev in events:
                date = ev.get("date")
                ev_type = (ev.get("type") or "").lower()
                if ev_type == "exam_control":
                    text = _format_exam_control_reminder(ev, date)
                else:
                    title = (ev.get("title") or "").strip()
                    body = ev.get("body") or ""
                    room = ev.get("room") or None
                    teacher = ev.get("teacher") or None
                    text = f"⏰ Напоминание: завтра ({date})"
                    if title:
                        text += f" — {title}"
                        if room:
                            text += f" ({room})"
                    else:
                        if room:
                            text += f" — Аудитория {room}"
                    if teacher:
                        text += f"\nПреподаватель: {teacher}"
                    if body:
                        text += f"\n{body}"
                payload = {
                    "chat_id": ev.get("chat_id"),
                    "thread_id": ev.get("thread_id"),
                    "text": text
                }
                photos = ev.get("photo_urls") or []
                if photos:
                    payload["photos"] = photos
                attachments = ev.get("attachments") or []
                doc_urls = []
                photo_urls = []
                local_files = []
                for item in attachments:
                    if not isinstance(item, dict):
                        continue
                    url = str(item.get("url") or "").strip()
                    storage_key = str(item.get("storage_key") or "").strip()
                    kind = str(item.get("kind") or "").lower()
                    if not url:
                        if storage_key:
                            local_files.append({
                                "kind": kind if kind in ("photo", "document") else "document",
                                "path": f"/uploads/{storage_key}",
                                "name": item.get("name"),
                            })
                        continue
                    if kind == "photo":
                        photo_urls.append(url)
                    else:
                        doc_urls.append(url)
                    if storage_key:
                        local_files.append({
                            "kind": kind if kind in ("photo", "document") else "document",
                            "path": f"/uploads/{storage_key}",
                            "name": item.get("name"),
                        })
                if photo_urls:
                    payload["photos"] = list(dict.fromkeys((payload.get("photos") or []) + photo_urls))
                if doc_urls:
                    payload["documents"] = list(dict.fromkeys(doc_urls))
                if local_files:
                    payload["local_files"] = local_files
                try:
                    resp = client.post(f"{BOT_SERVICE_URL}/send", json=payload, timeout=10.0)
                    resp.raise_for_status()
                    client.post(f"{BACKEND_URL}/events/{ev.get('id')}/mark_reminder_sent", timeout=5.0)
                    WORKER_REMINDERS_SENT.inc()
                except Exception as e:
                    thread_id = payload.get("thread_id")
                    if thread_id is not None:
                        payload_retry = {k: v for k, v in payload.items() if k != "thread_id"}
                        try:
                            resp = client.post(f"{BOT_SERVICE_URL}/send", json=payload_retry, timeout=10.0)
                            resp.raise_for_status()
                            client.post(f"{BACKEND_URL}/events/{ev.get('id')}/mark_reminder_sent", timeout=5.0)
                            WORKER_REMINDERS_SENT.inc()
                            print("⚠️ Worker: напоминание отправлено без thread_id для события", ev.get("id"))
                            continue
                        except Exception:
                            pass
                    WORKER_REMINDERS_FAILED.inc()
                    print("❌ Worker: ошибка отправки напоминания для события", ev.get("id"), e)
    except Exception as e:
        print("⚠️ Проверка Worker не удалась:", e)

if __name__ == '__main__':
    start_http_server(METRICS_PORT)
    print("📊 Worker: метрики Prometheus на :", METRICS_PORT)
    _probe_telegram()
    print("✅ Worker запущен, опрашивает каждые", POLL_INTERVAL, "секунд")
    scheduler.start()
