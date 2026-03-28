import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ADMIN_IDS: list[int] = list(map(int, os.getenv("ADMIN_IDS", "0").split(",")))
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "bot.db")

    PREMIUM_PRICE_STARS: int = 89
    MAX_REFERRAL_DISCOUNT: int = 49
    REFERRAL_DISCOUNT_PER_INVITE: int = 5
    FREE_DAILY_LIMIT: int = 30
    SUBSCRIPTION_DAYS: int = 30
    FREE_AVAILABLE_RATIO: float = 0.30   # 30% shown as "free" for free-tier users

config = Config()
