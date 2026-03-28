import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import config
from database import Database

logger = logging.getLogger(__name__)
router = Router()


def main_menu_kb(is_admin: bool = False) -> object:
    b = InlineKeyboardBuilder()
    b.button(text="🎲 Генерировать",    callback_data="generate")
    b.button(text="👤 Профиль",          callback_data="profile")
    b.button(text="⭐ Premium",          callback_data="premium")
    b.button(text="🔗 Реферальная ссылка", callback_data="referral")
    if is_admin:
        b.button(text="⚙️ Панель админа", callback_data="admin_panel")
    b.adjust(1, 2, 1, 1) if not is_admin else b.adjust(1, 2, 1, 1, 1)
    return b.as_markup()


def _welcome_text(first_name: str, tier: str) -> str:
    return (
        f"👋 Привет, <b>{first_name}</b>!\n\n"
        f"🤖 <b>TG Username Generator</b>\n"
        f"Нахожу редкие юзернеймы в Telegram\n\n"
        f"Твой тариф: {tier}\n\n"
        f"Выбери действие:"
    )


async def _tier_badge(db: Database, user_id: int) -> str:
    from config import config as cfg
    if user_id in cfg.ADMIN_IDS:
        return "👑 Admin"
    if await db.is_premium(user_id):
        return "⭐ Premium"
    return "🆓 Free"


@router.message(CommandStart())
async def cmd_start(message: Message):
    db: Database = message.bot.db
    user = message.from_user

    # Parse referral arg
    args = message.text.split(maxsplit=1)
    referrer_id = None
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            rid = int(args[1][4:])
            if rid != user.id:
                referrer_id = rid
        except ValueError:
            pass

    existing = await db.get_user(user.id)

    if not existing:
        await db.create_user(
            user_id=user.id,
            username=user.username or "",
            first_name=user.first_name or "",
            referrer_id=referrer_id,
        )
        # Process referral bonus
        if referrer_id and await db.get_user(referrer_id):
            success = await db.add_referral(referrer_id, user.id)
            if success:
                referrer = await db.get_user(referrer_id)
                discount = referrer["referral_discount"]
                new_price = config.PREMIUM_PRICE_STARS - discount
                try:
                    await message.bot.send_message(
                        referrer_id,
                        f"🎉 По твоей ссылке зарегистрировался новый пользователь!\n"
                        f"💰 Твоя скидка на Premium: <b>{discount}⭐</b>\n"
                        f"🏷 Цена для тебя: <b>{new_price}⭐</b> (из {config.PREMIUM_PRICE_STARS}⭐)",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
    else:
        if user.username and existing.get("username") != user.username:
            await db.update_user(user.id, username=user.username)

    badge = await _tier_badge(db, user.id)
    is_admin = user.id in config.ADMIN_IDS

    await message.answer(
        _welcome_text(user.first_name, badge),
        parse_mode="HTML",
        reply_markup=main_menu_kb(is_admin),
    )


@router.callback_query(F.data == "main_menu")
async def back_to_menu(callback: CallbackQuery):
    db: Database = callback.bot.db
    user = callback.from_user
    badge = await _tier_badge(db, user.id)
    is_admin = user.id in config.ADMIN_IDS

    await callback.message.edit_text(
        _welcome_text(user.first_name, badge),
        parse_mode="HTML",
        reply_markup=main_menu_kb(is_admin),
    )


@router.callback_query(F.data == "referral")
async def show_referral(callback: CallbackQuery):
    db: Database = callback.bot.db
    user = await db.get_user(callback.from_user.id)
    bot_info = await callback.bot.get_me()
    bot_username = bot_info.username

    link = f"https://t.me/{bot_username}?start=ref_{callback.from_user.id}"
    count = user.get("referral_count", 0) if user else 0
    discount = user.get("referral_discount", 0) if user else 0
    max_disc = config.MAX_REFERRAL_DISCOUNT
    per_invite = config.REFERRAL_DISCOUNT_PER_INVITE
    base_price = config.PREMIUM_PRICE_STARS

    b = InlineKeyboardBuilder()
    b.button(text="◀️ Назад", callback_data="main_menu")

    await callback.message.edit_text(
        f"🔗 <b>Реферальная программа</b>\n\n"
        f"За каждого приглашённого — <b>−{per_invite}⭐</b> от цены Premium\n"
        f"Максимальная скидка: <b>{max_disc}⭐</b> (т.е. минимум {base_price - max_disc}⭐)\n\n"
        f"👥 Приглашено: <b>{count}</b> чел.\n"
        f"💰 Твоя скидка: <b>{discount}⭐</b>\n"
        f"🏷 Цена Premium: <b>{base_price - discount}⭐</b>\n\n"
        f"🔗 Твоя ссылка:\n<code>{link}</code>",
        parse_mode="HTML",
        reply_markup=b.as_markup(),
    )
