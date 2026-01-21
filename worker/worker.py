import os
import httpx
from apscheduler.schedulers.blocking import BlockingScheduler
from datetime import datetime

BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")
BOT_SERVICE_URL = os.getenv("BOT_SERVICE_URL", "http://bot:8081")
POLL_INTERVAL = int(os.getenv("WORKER_POLL_INTERVAL", "60"))

scheduler = BlockingScheduler()

@scheduler.scheduled_job('interval', seconds=POLL_INTERVAL)
def check_and_send():
    print(datetime.utcnow().isoformat(), "Worker: checking reminders")
    try:
        with httpx.Client() as client:
            r = client.get(f"{BACKEND_URL}/events/due_reminders", timeout=10.0)
            r.raise_for_status()
            events = r.json()
            for ev in events:
                date = ev.get("date")
                # trim title so whitespace-only titles are treated as empty
                title = (ev.get("title") or "").strip()
                body = ev.get("body") or ""
                # compose message: include title only if present, include body if present
                text = f"⏰ Напоминание: завтра ({date})"
                if title:
                    text += f" — {title}"
                if body:
                    text += f"\n{body}"
                payload = {
                    "chat_id": ev.get("chat_id"),
                    "thread_id": ev.get("thread_id"),
                    "text": text
                }
                try:
                    resp = client.post(f"{BOT_SERVICE_URL}/send", json=payload, timeout=10.0)
                    resp.raise_for_status()
                    # Отмечаем как отправленное
                    client.post(f"{BACKEND_URL}/events/{ev.get('id')}/mark_reminder_sent", timeout=5.0)
                except Exception as e:
                    print("❌ Worker: ошибка отправки напоминания для события", ev.get("id"), e)
    except Exception as e:
        print("⚠️ Worker check failed:", e)

if __name__ == '__main__':
    print("✅ Worker запущен, опрашивает каждые", POLL_INTERVAL, "секунд")
    scheduler.start()
