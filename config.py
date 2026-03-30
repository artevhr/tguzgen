import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ADMIN_IDS: list[int] = list(map(int, os.getenv("ADMIN_IDS", "0").split(",")))
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "bot.db")

    # Monthly premium
    PREMIUM_PRICE_STARS: int = 89
    MAX_REFERRAL_DISCOUNT: int = 49          # max discount for monthly (floor = 40⭐)

    # Lifetime premium
    LIFETIME_PRICE_STARS: int = 119
    MAX_REFERRAL_DISCOUNT_LIFETIME: int = 40  # max discount for lifetime (floor = 79⭐)

    REFERRAL_DISCOUNT_PER_INVITE: int = 5
    FREE_DAILY_LIMIT: int = 30
    SUBSCRIPTION_DAYS: int = 30

    HISTORY_LIMIT: int = 50   # max saved usernames per user

config = Config()
