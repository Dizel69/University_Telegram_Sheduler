import asyncio
import json
import logging
import os
import socket
from typing import Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import aiohttp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bot-service")

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN хранится в переменных окружения")

API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

app = FastAPI(title="Сервис бота М15")
_session: aiohttp.ClientSession | None = None


TELEGRAM_HOST = "api.telegram.org"
# IPv6 адрес, который у тебя гарантированно работает (проверено curl)
TELEGRAM_IPV6 = os.getenv("TELEGRAM_API_IPV6", "2001:67c:4e8:f004::9")


class _StaticResolver(aiohttp.abc.AbstractResolver):
    def __init__(self, mapping: dict[str, str]):
        self._mapping = mapping

    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: int = socket.AF_INET,
    ) -> list[dict[str, Any]]:
        if host in self._mapping:
            ip = self._mapping[host]
            return [
                {
                    "hostname": host,
                    "host": ip,
                    "port": port,
                    "family": socket.AF_INET6,
                    "proto": 0,
                    "flags": 0,
                }
            ]
        # fallback на системный резолвер
        infos = await asyncio.get_running_loop().getaddrinfo(
            host, port, family=family, type=socket.SOCK_STREAM
        )
        out: list[dict[str, Any]] = []
        for fam, _type, proto, _canon, sockaddr in infos:
            addr = sockaddr[0]
            out.append(
                {
                    "hostname": host,
                    "host": addr,
                    "port": port,
                    "family": fam,
                    "proto": proto,
                    "flags": 0,
                }
            )
        return out

    async def close(self) -> None:
        return None


@app.on_event("startup")
async def _startup() -> None:
    # В нашей сети IPv4 до Telegram не работает, поэтому фиксируем IPv6.
    # Это важно: иначе клиент может выбирать IPv4 и ловить ConnectTimeout.
    global _session
    timeout = aiohttp.ClientTimeout(total=120, connect=15, sock_read=90)
    resolver = _StaticResolver({TELEGRAM_HOST: TELEGRAM_IPV6})
    connector = aiohttp.TCPConnector(
        resolver=resolver,
        family=socket.AF_INET6,
        ttl_dns_cache=300,
        use_dns_cache=True,
    )
    _session = aiohttp.ClientSession(timeout=timeout, connector=connector)


@app.on_event("shutdown")
async def _shutdown() -> None:
    global _session
    if _session is not None:
        await _session.close()
        _session = None


def _get_session() -> aiohttp.ClientSession:
    if _session is None:
        # На случай, если startup не отработал (например, при тестах).
        timeout = aiohttp.ClientTimeout(total=120, connect=15, sock_read=90)
        resolver = _StaticResolver({TELEGRAM_HOST: TELEGRAM_IPV6})
        connector = aiohttp.TCPConnector(
            resolver=resolver,
            family=socket.AF_INET6,
            ttl_dns_cache=300,
            use_dns_cache=True,
        )
        return aiohttp.ClientSession(timeout=timeout, connector=connector)
    return _session


class SendRequest(BaseModel):
    """Запрос на отправку сообщения."""
    chat_id: int
    thread_id: int | None = None
    text: str


class CreateTopicRequest(BaseModel):
    """Запрос на создание темы в чате."""
    chat_id: int
    name: str


@app.post("/send")
async def send_message(req: SendRequest):
    """Отправляет сообщение в Telegram и возвращает ID сообщения."""
    try:
        logger.info("POST /send payload: %s", req.dict())
        payload: dict[str, object] = {"chat_id": req.chat_id, "text": req.text}
        if req.thread_id is not None:
            payload["message_thread_id"] = req.thread_id

        url = f"{API_BASE}/sendMessage"
        session = _get_session()
        async with session.post(url, json=payload) as resp:
            text = await resp.text()
            if resp.status != 200:
                logger.warning(
                    "Telegram send non-200: status=%s body=%s",
                    resp.status,
                    text,
                )
                raise HTTPException(
                    status_code=502,
                    detail=f"Telegram HTTP {resp.status}: {text}",
                )

        try:
            body = json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning("Telegram send invalid JSON: %s", e)
            raise HTTPException(
                status_code=502,
                detail="Telegram returned invalid JSON",
            )

        if not body.get("ok"):
            logger.warning("Telegram API error payload: %s", body)
            raise HTTPException(
                status_code=502,
                detail=f"Telegram API error: {body}",
            )

        msg = body.get("result") or {}
        message_id = msg.get("message_id")
        logger.info("Telegram send OK: message_id=%s chat_id=%s", message_id, req.chat_id)
        return {"ok": True, "message_id": message_id}
    except HTTPException:
        raise
    except Exception as e:
        # Не логируем URL (там BOT_TOKEN), поэтому только тип/текст исключения.
        logger.exception("Unexpected send failure: %s", type(e).__name__)
        raise HTTPException(status_code=500, detail="Unexpected bot-service error")


@app.post("/create_topic")
async def create_topic(req: CreateTopicRequest):
    """
    Создаёт форум/тему в супергруппе и возвращает её message_thread_id.
    Требуется, чтобы бот был админом с правами управления темами.
    """
    try:
        logger.info("POST /create_topic payload: %s", req.dict())

        payload = {"chat_id": req.chat_id, "name": req.name}
        url = f"{API_BASE}/createForumTopic"
        session = _get_session()
        async with session.post(url, json=payload) as resp:
            text = await resp.text()
            if resp.status != 200:
                logger.warning(
                    "Telegram create_topic non-200: status=%s body=%s",
                    resp.status,
                    text,
                )
                raise HTTPException(
                    status_code=502,
                    detail=f"Telegram HTTP {resp.status}: {text}",
                )

        try:
            body = json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning("Telegram create_topic invalid JSON: %s", e)
            raise HTTPException(
                status_code=502,
                detail="Telegram returned invalid JSON",
            )

        if not body.get("ok"):
            logger.warning("Telegram API error payload (create_topic): %s", body)
            raise HTTPException(
                status_code=502,
                detail=f"Telegram API error: {body}",
            )

        result_obj = body.get("result") or {}
        thread_id = result_obj.get("message_thread_id")
        logger.info("Create topic result message_thread_id: %s", thread_id)
        return {"ok": True, "message_thread_id": thread_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unexpected create_topic failure: %s", type(e).__name__)
        raise HTTPException(status_code=500, detail="Unexpected bot-service error")


@app.get("/")
async def root():
    return {"service": "bot-service", "status": "ok"}


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/metrics")
async def metrics():
    # Не поддерживает Prometheus-метрики, но явный ответ уменьшает шум от 404.
    return {"ok": False, "detail": "metrics_not_implemented"}
