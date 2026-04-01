"""
Username availability checker.

Step 1 — Telegram Bot API (getChat)
    • Нашли чат               → ЗАНЯТО
    • "chat not found" и т.п. → переходим к Fragment
    • Ошибка / rate limit     → SKIP (не сжигает попытку в find_free_usernames)

Step 2 — Fragment searchAuctions?filter=active
    • Точное совпадение имени → ЗАНЯТО
    • Не нашли                → СВОБОДНО

Fragment page fetch не используем — блокируется Cloudflare.
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

# Специальный sentinel — означает "пропусти кандидат, не считай попытку"
_SKIP = object()

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


# ─── Fragment ─────────────────────────────────────────────────────────────────

async def _fragment_is_active_auction(username: str) -> bool:
    """True если ник прямо сейчас на активном аукционе Fragment."""
    uname = username.lower()
    session = _get_session()
    try:
        params = {"method": "searchAuctions", "query": uname, "filter": "active"}
        async with session.get(_FRAGMENT_API, params=params) as resp:
            if resp.status != 200:
                return False  # fail-open: при ошибке считаем свободным
            data = await resp.json(content_type=None)
            for item in data.get("auctions") or []:
                item_name = (item.get("username") or "").lstrip("@").lower()
                if item_name == uname:
                    logger.debug(f"@{username}: active auction on Fragment")
                    return True
    except asyncio.TimeoutError:
        logger.debug(f"@{username}: Fragment timeout (skip)")
    except Exception as e:
        logger.debug(f"@{username}: Fragment error: {e}")
    return False


# ─── Telegram API ─────────────────────────────────────────────────────────────

async def _tg_check(bot: Bot, username: str):
    """
    Возвращает:
      True    → занято
      False   → не найдено в TG (идём в Fragment)
      _SKIP   → временная ошибка/rate limit, пропустить кандидат
    """
    try:
        await bot.get_chat(f"@{username}")
        return True  # нашли → занято

    except TelegramRetryAfter as e:
        wait = min(e.retry_after + 1, 30)
        logger.debug(f"@{username}: flood wait {wait}s")
        await asyncio.sleep(wait)
        # Повторяем один раз после ожидания
        try:
            await bot.get_chat(f"@{username}")
            return True
        except TelegramBadRequest as e2:
            txt = str(e2).lower()
            if "chat not found" in txt or "username_not_occupied" in txt or "username not occupied" in txt:
                return False
            return _SKIP
        except Exception:
            return _SKIP

    except TelegramBadRequest as e:
        txt = str(e).lower()
        if (
            "chat not found" in txt
            or "username_not_occupied" in txt
            or "username not occupied" in txt
        ):
            return False  # не занято → идём в Fragment
        if "username_invalid" in txt or "invalid username" in txt:
            return True   # технически недоступен
        # Неизвестная ошибка — пропускаем кандидат
        logger.debug(f"@{username}: unexpected BadRequest: {e}")
        return _SKIP

    except Exception as e:
        logger.debug(f"@{username}: TG error: {e}")
        return _SKIP  # сетевая ошибка — пропускаем


# ─── Public check ─────────────────────────────────────────────────────────────

async def check_username(bot: Bot, username: str) -> bool:
    """
    True  → похоже свободен
    False → занят или активный аукцион

    Примечание: при _SKIP возвращает False (для free-tier это нормально —
    в premium-tier _SKIP обрабатывается отдельно через check_username_full).
    """
    result = await _tg_check(bot, username)
    if result is True:
        return False
    if result is _SKIP:
        return False  # в free-tier просто пропускаем кандидат

    # result is False → TG не нашёл, проверяем Fragment
    if await _fragment_is_active_auction(username):
        return False

    return True


# ─── Premium batch finder ─────────────────────────────────────────────────────

async def find_free_usernames(
    bot: Bot,
    length: int,
    target_count: int,
    generate_fn,
    progress_callback=None,
    delay: float = 0.35,
) -> list[str]:
    """
    Ищет `target_count` свободных юзернеймов.

    Ключевое отличие от check_username:
    - _SKIP (ошибка/rate limit) НЕ сжигает попытку (attempts не растёт)
    - max_attempts считает только реально проверенные кандидаты
    - При flood wait пауза уже внутри _tg_check, просто продолжаем
    """
    found:    list[str] = []
    seen:     set[str]  = set()
    attempts  = 0          # только реальные проверки (не ошибки)
    skips     = 0          # счётчик подряд идущих ошибок
    max_attempts = target_count * 30  # достаточно для любой длины
    max_skips    = 50      # если 50 подряд ошибок — что-то не так, выходим

    while len(found) < target_count and attempts < max_attempts and skips < max_skips:
        username = generate_fn(length)
        if username in seen:
            continue
        seen.add(username)

        tg_result = await _tg_check(bot, username)

        if tg_result is _SKIP:
            skips += 1
            await asyncio.sleep(delay)
            continue  # не считаем попытку!

        skips = 0   # сбрасываем счётчик ошибок
        attempts += 1

        if tg_result is True:
            # занято через TG
            await asyncio.sleep(delay)
            continue

        # tg_result is False → проверяем Fragment
        fragment_taken = await _fragment_is_active_auction(username)
        if fragment_taken:
            await asyncio.sleep(delay)
            continue

        # Свободен!
        found.append(username)
        if progress_callback:
            await progress_callback(len(found), target_count)

        await asyncio.sleep(delay)

    if skips >= max_skips:
        logger.warning(f"find_free_usernames: hit max_skips={max_skips}, TG API issues?")

    return found
