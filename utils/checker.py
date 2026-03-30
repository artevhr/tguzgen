"""
Username availability checker.

Two-pass approach:
  1. Telegram Bot API  – bot.get_chat()
     • Returns the chat object if the username is a *public* entity (bot, channel, public group).
     • Private accounts are INVISIBLE to the Bot API even when their username is taken —
       so "chat not found" is a necessary but not sufficient signal for "free".
  2. Fragment marketplace  – fragment.com API
     • Usernames listed for auction (active, sold, reserved) cannot be self-registered
       via @BotFather / Settings, so we treat them as taken.

Combined logic:
  taken by getChat  → False  (definitely taken)
  found on Fragment → False  (reserved / for sale / sold)
  neither           → True   (best-effort "free"; private account occupancy is unknowable)
"""

import asyncio
import logging
import aiohttp
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

logger = logging.getLogger(__name__)

_FRAGMENT_API = "https://fragment.com/api"
_FRAGMENT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

_session: aiohttp.ClientSession | None = None


def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        timeout = aiohttp.ClientTimeout(total=6)
        _session = aiohttp.ClientSession(headers=_FRAGMENT_HEADERS, timeout=timeout)
    return _session


async def close_session():
    """Call on bot shutdown to free the aiohttp session."""
    global _session
    if _session and not _session.closed:
        await _session.close()
        _session = None

async def fragment_check_free(username: str) -> bool:
    """
    Lightweight Fragment-only check for free-tier use.
    Returns True if the username is NOT found on Fragment (probably free from marketplace side).
    Fast — just one HTTP call, no Telegram API involved.
    """
    return not await _fragment_is_taken(username)


# ─── Fragment check ──────────────────────────────────────────────────────────

async def _fragment_is_taken(username: str) -> bool:
    """
    Returns True if the username appears on Fragment (active auction, sold, or reserved).
    Fails open (returns False) on any network / parse error.
    """
    username_lower = username.lower()
    session = _get_session()
    for filt in ("active", "sold"):
        try:
            params = {
                "method": "searchAuctions",
                "query": username_lower,
                "filter": filt,
            }
            async with session.get(_FRAGMENT_API, params=params) as resp:
                if resp.status != 200:
                    continue
                data = await resp.json(content_type=None)
                for item in data.get("auctions") or []:
                    item_name = (item.get("username") or "").lstrip("@").lower()
                    if item_name == username_lower:
                        logger.debug(f"@{username} found on Fragment (filter={filt})")
                        return True
        except asyncio.TimeoutError:
            logger.debug(f"Fragment timeout for @{username}")
        except Exception as e:
            logger.debug(f"Fragment check error for @{username}: {e}")
    return False


# ─── Telegram Bot API check ──────────────────────────────────────────────────

async def _tg_is_taken(bot: Bot, username: str) -> bool | None:
    """
    True  → definitely taken (public entity found via getChat)
    False → not found — could still be a private account with that username
    None  → unexpected API error, treat conservatively as taken
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
        logger.debug(f"Unexpected error checking @{username}: {e}")
        return None


# ─── Combined public API ─────────────────────────────────────────────────────

async def check_username(bot: Bot, username: str) -> bool:
    """
    Returns True if the username appears to be available.

    Pass 1 — Telegram Bot API (catches all public entities)
    Pass 2 — Fragment marketplace (catches reserved / auction names)
    """
    tg = await _tg_is_taken(bot, username)
    if tg is True or tg is None:
        return False  # taken or error

    # Not found via Bot API — check Fragment before declaring free
    if await _fragment_is_taken(username):
        return False

    return True


# ─── Batch finder ────────────────────────────────────────────────────────────

async def find_free_usernames(
    bot: Bot,
    length: int,
    target_count: int,
    generate_fn,
    progress_callback=None,
    delay: float = 0.4,
) -> list[str]:
    """
    Keeps generating and checking usernames until `target_count` free ones are found.
    `generate_fn(length: int) -> str`
    """
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
