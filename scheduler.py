import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot
from aiogram.utils.keyboard import InlineKeyboardBuilder

logger = logging.getLogger(__name__)


def setup_scheduler(bot: Bot, db) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Europe/Minsk")

    @scheduler.scheduled_job("interval", hours=6, id="check_expiry")
    async def check_expiring_subscriptions():
        logger.info("Scheduler: checking expiring subscriptions…")
        users = await db.get_expiring_soon()
        for user in users:
            try:
                expiry = datetime.fromisoformat(user["premium_until"])
                delta = expiry - datetime.now()
                days_left = delta.days + (1 if delta.seconds > 0 else 0)

                builder = InlineKeyboardBuilder()
                builder.button(text="⭐ Продлить Premium", callback_data="premium")

                await bot.send_message(
                    user["user_id"],
                    f"⚠️ <b>Подписка заканчивается!</b>\n\n"
                    f"Твой Premium истекает через <b>{days_left} дн.</b>\n\n"
                    f"Продли подписку, чтобы не потерять:\n"
                    f"• Генерацию только свободных юзернеймов\n"
                    f"• Безлимитные генерации",
                    parse_mode="HTML",
                    reply_markup=builder.as_markup(),
                )
                await db.update_user(user["user_id"], notified_expiry=1)
                logger.info(f"Notified user {user['user_id']} about expiry")
            except Exception as e:
                logger.warning(f"Failed to notify {user['user_id']}: {e}")

    return scheduler
