import aiosqlite
from datetime import datetime, date, timedelta
from typing import Optional


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def init(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id           INTEGER PRIMARY KEY,
                    username          TEXT    DEFAULT '',
                    first_name        TEXT    DEFAULT '',
                    is_premium        INTEGER DEFAULT 0,
                    premium_until     TEXT,
                    premium_type      TEXT    DEFAULT 'none',
                    daily_generations INTEGER DEFAULT 0,
                    last_gen_date     TEXT,
                    referrer_id       INTEGER,
                    referral_count    INTEGER DEFAULT 0,
                    referral_discount INTEGER DEFAULT 0,
                    total_generations INTEGER DEFAULT 0,
                    notified_expiry   INTEGER DEFAULT 0,
                    created_at        TEXT    DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS referrals (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    referrer_id INTEGER NOT NULL,
                    referred_id INTEGER NOT NULL,
                    created_at  TEXT    DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(referred_id)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS gen_history (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    INTEGER NOT NULL,
                    username   TEXT    NOT NULL,
                    length     INTEGER NOT NULL,
                    style      TEXT    NOT NULL DEFAULT 'random',
                    found_at   TEXT    DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Migration: add new columns if they don't exist yet
            for col, definition in [
                ("premium_type", "TEXT DEFAULT 'none'"),
            ]:
                try:
                    await db.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")
                except Exception:
                    pass
            await db.commit()

    # ─── Generic helpers ─────────────────────────────────────────────────────

    async def _fetchone(self, query: str, params: tuple = ()) -> Optional[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, params) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def _fetchall(self, query: str, params: tuple = ()) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def _execute(self, query: str, params: tuple = ()):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(query, params)
            await db.commit()

    # ─── User CRUD ───────────────────────────────────────────────────────────

    async def get_user(self, user_id: int) -> Optional[dict]:
        return await self._fetchone("SELECT * FROM users WHERE user_id = ?", (user_id,))

    async def create_user(
        self, user_id: int, username: str, first_name: str, referrer_id: Optional[int] = None
    ):
        await self._execute(
            """INSERT OR IGNORE INTO users (user_id, username, first_name, referrer_id)
               VALUES (?, ?, ?, ?)""",
            (user_id, username, first_name, referrer_id),
        )

    async def update_user(self, user_id: int, **kwargs):
        if not kwargs:
            return
        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [user_id]
        await self._execute(f"UPDATE users SET {set_clause} WHERE user_id = ?", values)

    async def get_all_user_ids(self) -> list[int]:
        rows = await self._fetchall("SELECT user_id FROM users")
        return [r["user_id"] for r in rows]

    async def get_all_users(self) -> list[dict]:
        return await self._fetchall("SELECT * FROM users")

    # ─── Premium ─────────────────────────────────────────────────────────────

    async def is_premium(self, user_id: int) -> bool:
        from config import config
        if user_id in config.ADMIN_IDS:
            return True
        user = await self.get_user(user_id)
        if not user or not user["is_premium"]:
            return False
        if not user["premium_until"]:
            return True  # lifetime
        expiry = datetime.fromisoformat(user["premium_until"])
        if expiry > datetime.now():
            return True
        await self.update_user(
            user_id, is_premium=0, premium_until=None,
            premium_type="none", notified_expiry=0,
        )
        return False

    async def is_lifetime(self, user_id: int) -> bool:
        from config import config
        if user_id in config.ADMIN_IDS:
            return True
        user = await self.get_user(user_id)
        if not user:
            return False
        return bool(user.get("is_premium")) and not user.get("premium_until")

    async def set_premium(self, user_id: int, days: int = 30):
        """
        Activate or EXTEND monthly premium.
        If the user already has an active subscription, days are added on top.
        """
        user = await self.get_user(user_id)
        now = datetime.now()

        if user and user.get("is_premium") and user.get("premium_until"):
            current_expiry = datetime.fromisoformat(user["premium_until"])
            base = max(current_expiry, now)   # extend from current expiry, not today
        else:
            base = now

        expiry = base + timedelta(days=days)
        await self.update_user(
            user_id,
            is_premium=1,
            premium_until=expiry.isoformat(),
            premium_type="monthly",
            notified_expiry=0,
        )

    async def set_premium_lifetime(self, user_id: int):
        """Activate lifetime premium (no expiry)."""
        await self.update_user(
            user_id,
            is_premium=1,
            premium_until=None,
            premium_type="lifetime",
            notified_expiry=0,
        )

    async def revoke_premium(self, user_id: int):
        await self.update_user(
            user_id, is_premium=0, premium_until=None, premium_type="none"
        )

    # ─── Referrals ───────────────────────────────────────────────────────────

    async def add_referral(self, referrer_id: int, referred_id: int) -> bool:
        from config import config
        async with aiosqlite.connect(self.db_path) as db:
            try:
                await db.execute(
                    "INSERT INTO referrals (referrer_id, referred_id) VALUES (?, ?)",
                    (referrer_id, referred_id),
                )
            except Exception:
                return False

            async with db.execute(
                "SELECT referral_count, referral_discount FROM users WHERE user_id = ?",
                (referrer_id,),
            ) as cursor:
                row = await cursor.fetchone()
            if row:
                count, discount = row
                # Cap at the larger of the two plan max discounts
                max_disc = max(config.MAX_REFERRAL_DISCOUNT, config.MAX_REFERRAL_DISCOUNT_LIFETIME)
                new_discount = min(discount + config.REFERRAL_DISCOUNT_PER_INVITE, max_disc)
                await db.execute(
                    "UPDATE users SET referral_count = ?, referral_discount = ? WHERE user_id = ?",
                    (count + 1, new_discount, referrer_id),
                )
            await db.commit()
        return True

    async def get_referrer_name(self, referrer_id: Optional[int]) -> str:
        if not referrer_id:
            return "—"
        user = await self.get_user(referrer_id)
        if not user:
            return f"#{referrer_id}"
        username = user.get("username") or ""
        if username:
            return f"@{username}"
        return user.get("first_name") or f"#{referrer_id}"

    # ─── Prices with referral discount ───────────────────────────────────────

    async def get_user_prices(self, user_id: int) -> dict:
        """Returns {'monthly': int, 'lifetime': int} after applying referral discount."""
        from config import config
        user = await self.get_user(user_id)
        discount = user.get("referral_discount", 0) if user else 0

        monthly_floor  = config.PREMIUM_PRICE_STARS  - config.MAX_REFERRAL_DISCOUNT
        lifetime_floor = config.LIFETIME_PRICE_STARS - config.MAX_REFERRAL_DISCOUNT_LIFETIME

        monthly  = max(config.PREMIUM_PRICE_STARS  - discount, monthly_floor)
        lifetime = max(config.LIFETIME_PRICE_STARS - discount, lifetime_floor)
        return {"monthly": monthly, "lifetime": lifetime}

    # kept for backwards compat
    async def get_user_price(self, user_id: int) -> int:
        p = await self.get_user_prices(user_id)
        return p["monthly"]

    # ─── Daily generations ───────────────────────────────────────────────────

    async def get_daily_generations(self, user_id: int) -> int:
        user = await self.get_user(user_id)
        if not user:
            return 0
        today = date.today().isoformat()
        if user.get("last_gen_date") != today:
            return 0
        return user.get("daily_generations") or 0

    async def increment_generations(self, user_id: int, count: int):
        user = await self.get_user(user_id)
        if not user:
            return
        today = date.today().isoformat()
        new_daily = count if user.get("last_gen_date") != today else (
            (user.get("daily_generations") or 0) + count
        )
        total = (user.get("total_generations") or 0) + count
        await self.update_user(
            user_id,
            daily_generations=new_daily,
            last_gen_date=today,
            total_generations=total,
        )

    # ─── Generation history ──────────────────────────────────────────────────

    async def add_to_history(self, user_id: int, usernames: list[str], length: int, style: str):
        """Save newly found free usernames to history, keeping only the latest HISTORY_LIMIT."""
        from config import config
        if not usernames:
            return
        async with aiosqlite.connect(self.db_path) as db:
            for u in usernames:
                await db.execute(
                    "INSERT INTO gen_history (user_id, username, length, style) VALUES (?, ?, ?, ?)",
                    (user_id, u, length, style),
                )
            # Prune old entries beyond the limit
            await db.execute(
                """DELETE FROM gen_history WHERE user_id = ? AND id NOT IN (
                       SELECT id FROM gen_history WHERE user_id = ?
                       ORDER BY id DESC LIMIT ?
                   )""",
                (user_id, user_id, config.HISTORY_LIMIT),
            )
            await db.commit()

    async def get_history(self, user_id: int, limit: int = 50) -> list[dict]:
        return await self._fetchall(
            """SELECT username, length, style, found_at
               FROM gen_history WHERE user_id = ?
               ORDER BY id DESC LIMIT ?""",
            (user_id, limit),
        )

    async def clear_history(self, user_id: int):
        await self._execute("DELETE FROM gen_history WHERE user_id = ?", (user_id,))

    # ─── Stats & scheduler ───────────────────────────────────────────────────

    async def get_stats(self) -> dict:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM users") as c:
                total = (await c.fetchone())[0]
            async with db.execute(
                "SELECT COUNT(*) FROM users WHERE is_premium = 1 AND (premium_until IS NULL OR premium_until > ?)",
                (datetime.now().isoformat(),),
            ) as c:
                premium = (await c.fetchone())[0]
            async with db.execute(
                "SELECT COUNT(*) FROM users WHERE premium_type = 'lifetime'"
            ) as c:
                lifetime = (await c.fetchone())[0]
            today = date.today().isoformat()
            async with db.execute(
                "SELECT COUNT(*) FROM users WHERE last_gen_date = ?", (today,)
            ) as c:
                active_today = (await c.fetchone())[0]
            async with db.execute(
                "SELECT COALESCE(SUM(daily_generations), 0) FROM users WHERE last_gen_date = ?",
                (today,),
            ) as c:
                gens_today = (await c.fetchone())[0]
        return {
            "total": total,
            "premium": premium,
            "lifetime": lifetime,
            "active_today": active_today,
            "gens_today": gens_today,
        }

    async def get_expiring_soon(self) -> list[dict]:
        now = datetime.now()
        in_3_days = (now + timedelta(days=3)).isoformat()
        return await self._fetchall(
            """SELECT * FROM users
               WHERE is_premium = 1
                 AND premium_until IS NOT NULL
                 AND premium_until BETWEEN ? AND ?
                 AND notified_expiry = 0""",
            (now.isoformat(), in_3_days),
        )
