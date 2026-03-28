import asyncio
import logging
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

logger = logging.getLogger(__name__)

# Usernames shorter than 5 chars can't actually be registered on Telegram
# but we still check them (they'll almost always be "taken").
MIN_REAL_LENGTH = 5


async def check_username(bot: Bot, username: str) -> bool:
    """
    Returns True if the username *appears* available, False if taken.
    Note: private accounts may appear free — this is a Telegram API limitation.
    """
    try:
        await bot.get_chat(f"@{username}")
        return False  # chat found → taken
    except TelegramBadRequest as e:
        txt = str(e).lower()
        if "chat not found" in txt or "username_not_occupied" in txt or "invalid username" in txt:
            return True  # not found → likely free
        logger.debug(f"TelegramBadRequest for @{username}: {e}")
        return False
    except Exception as e:
        logger.debug(f"Error checking @{username}: {e}")
        return False


async def find_free_usernames(
    bot: Bot,
    length: int,
    target_count: int,
    generate_fn,
    progress_callback=None,
    delay: float = 0.35,
) -> list[str]:
    """
    Check usernames until we find `target_count` free ones.
    Generates candidates on the fly using `generate_fn(length)`.
    """
    found: list[str] = []
    seen: set[str] = set()
    max_attempts = target_count * 15  # give up after this many API calls
    attempts = 0

    while len(found) < target_count and attempts < max_attempts:
        username = generate_fn(length)
        if username in seen:
            continue
        seen.add(username)
        attempts += 1

        is_free = await check_username(bot, username)
        if is_free:
            found.append(username)
            if progress_callback:
                await progress_callback(len(found), target_count)

        await asyncio.sleep(delay)

    return found
