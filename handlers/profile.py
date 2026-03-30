from datetime import datetime
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import config
from database import Database

router = Router()


@router.callback_query(F.data == "profile")
async def show_profile(callback: CallbackQuery):
    db: Database = callback.bot.db
    uid = callback.from_user.id
    user = await db.get_user(uid)

    if not user:
        await callback.answer("Профиль не найден. Напиши /start", show_alert=True)
        return

    is_admin  = uid in config.ADMIN_IDS
    is_prem   = await db.is_premium(uid)
    is_life   = await db.is_lifetime(uid)
    daily_used = await db.get_daily_generations(uid)

    # Tier
    if is_admin:
        tier = "Admin (Premium навсегда)"
        gens_line = "безлимит"
    elif is_life:
        tier = "Premium Навсегда"
        gens_line = "безлимит"
    elif is_prem:
        tier = "Premium"
        gens_line = "безлимит"
    else:
        tier = "Free"
        remaining = max(0, config.FREE_DAILY_LIMIT - daily_used)
        gens_line = f"{remaining} / {config.FREE_DAILY_LIMIT} сегодня"

    # Expiry
    expiry_line = ""
    if is_prem and not is_life and not is_admin and user.get("premium_until"):
        expiry_dt = datetime.fromisoformat(user["premium_until"])
        expiry_line = f"\nPremium до: <b>{expiry_dt.strftime('%d.%m.%Y')}</b>"

    total_gens     = user.get("total_generations") or 0
    referral_count = user.get("referral_count") or 0
    discount       = user.get("referral_discount") or 0
    referrer_id    = user.get("referrer_id")
    referrer_name  = await db.get_referrer_name(referrer_id)

    # History count
    history = await db.get_history(uid, limit=50)
    history_count = len(history)

    created_raw = user.get("created_at", "")
    try:
        created_str = datetime.fromisoformat(created_raw).strftime("%d.%m.%Y")
    except Exception:
        created_str = "—"

    prices = await db.get_user_prices(uid)
    tg_username = callback.from_user.username
    uname_line = f"@{tg_username}" if tg_username else "не установлен"

    b = InlineKeyboardBuilder()
    if not is_prem and not is_admin:
        b.button(text=f"Купить Premium — {prices['monthly']} звёзд / мес", callback_data="premium")
        b.button(text=f"Навсегда — {prices['lifetime']} звёзд", callback_data="premium")
    elif is_prem and not is_life and not is_admin:
        b.button(text=f"Продлить / Навсегда", callback_data="premium")
    b.button(text=f"История ({history_count})", callback_data="history")
    b.button(text="Реферальная ссылка",         callback_data="referral")
    b.button(text="Главное меню",               callback_data="main_menu")
    b.adjust(1)

    await callback.message.edit_text(
        f"<b>Личный кабинет</b>\n\n"
        f"ID: <code>{uid}</code>\n"
        f"Юзернейм: {uname_line}\n"
        f"Регистрация: {created_str}\n\n"
        f"Тариф: <b>{tier}</b>{expiry_line}\n"
        f"Генераций: {gens_line}\n"
        f"Всего генераций: {total_gens}\n\n"
        f"Приглашено: <b>{referral_count}</b> чел.\n"
        f"Скидка: <b>{discount} звёзд</b>\n"
        f"Пригласил: <b>{referrer_name}</b>",
        parse_mode="HTML",
        reply_markup=b.as_markup(),
    )
