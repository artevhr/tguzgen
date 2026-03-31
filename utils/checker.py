"""
Username availability checker.

Two-pass approach:
  1. Telegram Bot API  – bot.get_chat()
  2. Fragment marketplace  – прямой фетч страницы fragment.com/username/NAME

Fragment: если страница отдаёт 200 и содержит признаки аукциона
("Bid", "Buy now", "place a bid", auction JSON) — имя на продаже → занято.
Это надёжнее чем searchAuctions, который делает нечёткий поиск.
"""

import asyncio
import logging
import re
import aiohttp
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

logger = logging.getLogger(__name__)

_FRAGMENT_BASE = "https://fragment.com"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# Признаки страницы аукциона на fragment.com/username/NAME
# Проверено на реальных страницах (coinb, durov и т.д.)
_FRAGMENT_AUCTION_MARKERS = [
    "place a bid",
    "make a bid",
    "buy now",
    "auction ended",
    "minimum bid",
    "current bid",
    "winning bid",
    "reserve price",
    "table-cell-auction",
    "ton_auctions",
    "js-auction",
    "data-bid",
    '"sold"',
    '"active"',
    "fragment-username",
]

_session: aiohttp.ClientSession | None = None


def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        timeout = aiohttp.ClientTimeout(total=8)
        connector = aiohttp.TCPConnector(ssl=True)
        _session = aiohttp.ClientSession(
            headers=_HEADERS,
            timeout=timeout,
            connector=connector,
        )
    return _session


async def close_session():
    global _session
    if _session and not _session.closed:
        await _session.close()
        _session = None


# ─── Fragment check ──────────────────────────────────────────────────────────

async def _fragment_is_taken(username: str) -> bool:
    """
    Two-pass Fragment check:
      Pass 1 — GET fragment.com/username/NAME (прямая страница ника)
      Pass 2 — API searchAuctions с точной проверкой имени (fallback)

    Returns True → имя на Fragment (занято).
    Returns False → не найдено или сетевая ошибка (fail-open).
    """
    uname = username.lower()
    session = _get_session()

    # ── Pass 1: прямая страница ──────────────────────────────────────────
    url = f"{_FRAGMENT_BASE}/username/{uname}"
    try:
        async with session.get(url, allow_redirects=True) as resp:
            if resp.status == 200:
                raw  = await resp.content.read(32768)
                html = raw.decode("utf-8", errors="replace").lower()
                for marker in _FRAGMENT_AUCTION_MARKERS:
                    if marker.lower() in html:
                        logger.debug(f"@{username}: Fragment page hit (marker={marker!r})")
                        return True
                # Страница существует но маркеров нет — имя зарезервировано/занято
                # Если видим имя на странице вместе со словом "username" — скорее всего занято
                if f"/{uname}" in html and ("username" in html or "auction" in html):
                    logger.debug(f"@{username}: Fragment page exists with username context")
                    return True
            elif resp.status not in (404, 301, 302):
                logger.debug(f"@{username}: Fragment page status {resp.status}")
    except asyncio.TimeoutError:
        logger.debug(f"@{username}: Fragment page timeout")
    except Exception as e:
        logger.debug(f"@{username}: Fragment page error: {e}")

    # ── Pass 2: searchAuctions API (точное совпадение) ───────────────────
    for filt in ("active", "sold", "cancelled"):
        try:
            params = {"method": "searchAuctions", "query": uname, "filter": filt}
            async with session.get(
                f"{_FRAGMENT_BASE}/api", params=params
            ) as resp:
                if resp.status != 200:
                    continue
                data = await resp.json(content_type=None)
                for item in data.get("auctions") or []:
                    item_name = (item.get("username") or "").lstrip("@").lower()
                    if item_name == uname:
                        logger.debug(f"@{username}: found in searchAuctions filter={filt}")
                        return True
        except asyncio.TimeoutError:
            logger.debug(f"@{username}: searchAuctions timeout (filter={filt})")
        except Exception as e:
            logger.debug(f"@{username}: searchAuctions error: {e}")

    return False


# ─── Telegram Bot API check ──────────────────────────────────────────────────

async def _tg_is_taken(bot: Bot, username: str) -> bool | None:
    """
    True  → точно занято (нашли через getChat)
    False → не найдено (может быть приватный аккаунт)
    None  → ошибка API → считаем занятым (консервативно)
    """
    try:
        await bot.get_chat(f"@{username}")
        return True
    except TelegramBadRequest as e:
        txt = str(e).lower()
        if (
            "chat not found" in txt
            or "username_not_occupied" in txt
            or "username not occupied" in txt
            or "invalid username" in txt
            or "peer_id_invalid" in txt
        ):
            return False
        logger.debug(f"TelegramBadRequest for @{username}: {e}")
        return None
    except Exception as e:
        logger.debug(f"Unexpected TG error for @{username}: {e}")
        return None


# ─── Combined check ──────────────────────────────────────────────────────────

async def check_username(bot: Bot, username: str) -> bool:
    """
    True → имя похоже на свободное.
    Проверка: Telegram Bot API, затем Fragment.
    """
    tg = await _tg_is_taken(bot, username)
    if tg is True or tg is None:
        return False

    if await _fragment_is_taken(username):
        return False

    return True


# ─── Batch finder (Premium) ──────────────────────────────────────────────────

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
    max_attempts = target_count * 20
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
