import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import config
from database import Database
from scheduler import setup_scheduler
from handlers.start    import router as start_router
from handlers.generate import router as generate_router
from handlers.profile  import router as profile_router
from handlers.payment  import router as payment_router
from handlers.admin    import router as admin_router
from handlers.history  import router as history_router
from utils.checker     import close_session

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    if not config.BOT_TOKEN:
        raise ValueError("BOT_TOKEN is not set. Check your .env file.")

    bot = Bot(token=config.BOT_TOKEN)
    dp  = Dispatcher(storage=MemoryStorage())

    db = Database(config.DATABASE_PATH)
    await db.init()
    bot.db = db  # attach as attribute

    dp.include_router(admin_router)
    dp.include_router(start_router)
    dp.include_router(generate_router)
    dp.include_router(profile_router)
    dp.include_router(payment_router)
    dp.include_router(history_router)

    scheduler = setup_scheduler(bot, db)
    scheduler.start()
    logger.info("Scheduler started")

    logger.info("Bot starting...")
    try:
        await dp.start_polling(bot, skip_updates=True)
    finally:
        scheduler.shutdown(wait=False)
        await close_session()
        await bot.session.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
