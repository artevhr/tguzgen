"""
Username availability checker.

Step 1 — Telegram Bot API (getChat)
    • Нашли чат               → занято
    • "chat not found" и т.п. → переходим к шагу 2
    • Сетевая ошибка / flood  → 1 повтор, потом пропускаем кандидат

Step 2 — Fragment searchAuctions API (только active)
    • Fragment закрыт Cloudflare — прямой page fetch не работает.
    • API /api?method=searchAuctions работает без JS-челленджа.
    • Проверяем только filter=active (точное совпадение имени).
    • sold/cancelled не проверяем: если продан — новый владелец уже
      виден через TG API; если отменён — ник свободен.
"""

import asyncio
import logging
import aiohttp
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter

logger = logging.getLogger(__name__)

_FRAGMENT_API = "https://fragment.com/api"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, */*",
    "Referer": "https://fragment.com/",
}

_session: aiohttp.ClientSession | None = None


def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            headers=_HEADERS,
            timeout=aiohttp.ClientTimeout(total=8),
        )
    return _session


async def close_session():
    global _session
    if _session and not _session.closed:
        await _session.close()
        _session = None


# ─── Fragment API ─────────────────────────────────────────────────────────────

async def _fragment_is_active_auction(username: str) -> bool:
    """
    Возвращает True если ник прямо сейчас выставлен на активный аукцион Fragment.
    Использует только searchAuctions API (page fetch блокируется Cloudflare).
    Точное совпадение имени — не substring.
    """
    uname = username.lower()
    session = _get_session()
    try:
        params = {
            "method": "searchAuctions",
            "query": uname,
            "filter": "active",
        }
        async with session.get(_FRAGMENT_API, params=params) as resp:
            if resp.status != 200:
                logger.debug(f"@{username}: Fragment API status {resp.status}")
                return False
            data = await resp.json(content_type=None)
            for item in data.get("auctions") or []:
                item_name = (item.get("username") or "").lstrip("@").lower()
                if item_name == uname:
                    logger.debug(f"@{username}: active auction on Fragment")
                    return True
    except asyncio.TimeoutError:
        logger.debug(f"@{username}: Fragment API timeout")
    except Exception as e:
        logger.debug(f"@{username}: Fragment API error: {e}")
    return False


# ─── Telegram Bot API ─────────────────────────────────────────────────────────

async def _tg_is_taken(bot: Bot, username: str) -> bool | None:
    """
    True  → точно занято (публичный чат/аккаунт найден)
    False → TG говорит "не занято" → идём в Fragment
    None  → временная ошибка → пропускаем кандидат (не блокируем)
    """
    for attempt in range(2):
        try:
            await bot.get_chat(f"@{username}")
            return True

        except TelegramRetryAfter as e:
            if attempt == 0:
                await asyncio.sleep(e.retry_after + 1)
                continue
            return None

        except TelegramBadRequest as e:
            txt = str(e).lower()
            # Явно не занято
            if (
                "chat not found" in txt
                or "username_not_occupied" in txt
                or "username not occupied" in txt
            ):
                return False
            # Невалидный формат — не может быть зарегистрирован
            if "username_invalid" in txt or "invalid username" in txt:
                return True
            # Всё остальное — временная/неизвестная ошибка
            logger.debug(f"@{username}: unexpected TelegramBadRequest: {e}")
            return None

        except Exception as e:
            if attempt == 0:
                await asyncio.sleep(0.5)
                continue
            logger.debug(f"@{username}: TG network error: {e}")
            return None

    return None


# ─── Combined check ───────────────────────────────────────────────────────────

async def check_username(bot: Bot, username: str) -> bool:
    """
    True  → ник похоже свободен
    False → занят (TG API или Fragment active auction)
    """
    tg = await _tg_is_taken(bot, username)

    if tg is True:
        return False   # точно занято через TG

    if tg is None:
        return False   # временная ошибка → пропускаем кандидат

    # tg is False → TG не нашёл публичный чат
    # Приватные аккаунты TG API не видит — для них ничего не сделать.
    # Проверяем только активный аукцион Fragment.
    if await _fragment_is_active_auction(username):
        return False

    return True


# ─── Batch finder (Premium) ───────────────────────────────────────────────────

async def find_free_usernames(
    bot: Bot,
    length: int,
    target_count: int,
    generate_fn,
    progress_callback=None,
    delay: float = 0.4,
) -> list[str]:
    found: list[str] = []
    seen:  set[str]  = set()
    max_attempts = target_count * 25
    attempts = 0

    while len(found) < target_count and attempts < max_attempts:
        username = generate_fn(length)
        if username in seen:
            continue
        seen.add(username)
        attempts += 1

        if await check_username(bot, username):
            found.append(username)
            if progress_callback:
                await progress_callback(len(found), target_count)

        await asyncio.sleep(delay)

    return found
