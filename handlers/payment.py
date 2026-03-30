import logging
from aiogram import Router, F
from aiogram.types import (
    CallbackQuery, Message,
    LabeledPrice, PreCheckoutQuery,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import config
from database import Database

logger = logging.getLogger(__name__)
router = Router()

PAYLOAD_MONTHLY  = "premium_1month_"
PAYLOAD_LIFETIME = "premium_lifetime_"


# ─── Info screen ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "premium")
async def show_premium_info(callback: CallbackQuery):
    db: Database = callback.bot.db
    uid = callback.from_user.id
    is_prem   = await db.is_premium(uid)
    is_life   = await db.is_lifetime(uid)
    prices    = await db.get_user_prices(uid)
    user      = await db.get_user(uid)
    discount  = user.get("referral_discount", 0) if user else 0

    b = InlineKeyboardBuilder()

    if not is_prem:
        b.button(
            text=f"Подписка — {prices['monthly']} звёзд / мес",
            callback_data="buy_monthly",
        )
        b.button(
            text=f"Навсегда — {prices['lifetime']} звёзд",
            callback_data="buy_lifetime",
        )
        b.button(text="Получить скидку (реферал)", callback_data="referral")
    elif not is_life:
        # Active monthly — offer upgrade to lifetime or renewal
        b.button(
            text=f"Продлить — {prices['monthly']} звёзд / мес",
            callback_data="buy_monthly",
        )
        b.button(
            text=f"Апгрейд навсегда — {prices['lifetime']} звёзд",
            callback_data="buy_lifetime",
        )

    b.button(text="Назад", callback_data="main_menu")
    b.adjust(1)

    discount_line = f"\nТвоя скидка: <b>{discount} звёзд</b>" if discount else ""

    if is_life:
        status = "У тебя <b>Premium Навсегда</b>. Ничего продлевать не нужно."
    elif is_prem:
        from datetime import datetime
        expiry = datetime.fromisoformat(user["premium_until"]).strftime("%d.%m.%Y")
        status = (
            f"Активен <b>Premium</b> до {expiry}\n\n"
            f"Продли или апгрейднись до «Навсегда»."
        )
    else:
        status = (
            f"<b>Free тариф</b>\n"
            f"• До {config.FREE_DAILY_LIMIT} генераций в день\n"
            f"• Доступность не проверяется\n\n"
            f"<b>Premium</b>{discount_line}\n"
            f"• Безлимит\n"
            f"• Только реально свободные (Telegram API + Fragment)\n"
            f"• Стиль «Созвучные» — читаемые брендовые ники\n\n"
            f"Месяц — <b>{prices['monthly']} звёзд</b>\n"
            f"Навсегда — <b>{prices['lifetime']} звёзд</b>"
        )

    await callback.message.edit_text(
        f"<b>Premium</b>\n\n{status}",
        parse_mode="HTML",
        reply_markup=b.as_markup(),
    )


# ─── Invoices ────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "buy_monthly")
async def buy_monthly(callback: CallbackQuery):
    db: Database = callback.bot.db
    uid = callback.from_user.id
    prices = await db.get_user_prices(uid)
    price = prices["monthly"]

    await callback.bot.send_invoice(
        chat_id=uid,
        title="Premium — 1 месяц",
        description=(
            "Безлимитная генерация только свободных юзернеймов. "
            "Проверка через Telegram API + Fragment. "
            "Созвучный стиль."
        ),
        payload=f"{PAYLOAD_MONTHLY}{uid}",
        currency="XTR",
        prices=[LabeledPrice(label="Premium (1 мес.)", amount=price)],
    )
    await callback.answer()


@router.callback_query(F.data == "buy_lifetime")
async def buy_lifetime(callback: CallbackQuery):
    db: Database = callback.bot.db
    uid = callback.from_user.id
    prices = await db.get_user_prices(uid)
    price = prices["lifetime"]

    await callback.bot.send_invoice(
        chat_id=uid,
        title="Premium Навсегда",
        description=(
            "Безлимитная генерация только свободных юзернеймов — навсегда, без продления."
        ),
        payload=f"{PAYLOAD_LIFETIME}{uid}",
        currency="XTR",
        prices=[LabeledPrice(label="Premium (навсегда)", amount=price)],
    )
    await callback.answer()


# ─── Checkout ────────────────────────────────────────────────────────────────

@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message):
    db: Database = message.bot.db
    uid = message.from_user.id
    payload = message.successful_payment.invoice_payload

    b = InlineKeyboardBuilder()
    b.button(text="Генерировать", callback_data="generate")
    b.button(text="Главное меню", callback_data="main_menu")
    b.adjust(2)

    if payload.startswith(PAYLOAD_LIFETIME):
        await db.set_premium_lifetime(uid)
        await message.answer(
            "<b>Premium Навсегда активирован!</b>\n\n"
            "Больше никаких продлений — пользуйся бессрочно.\n\n"
            "• Безлимитные генерации\n"
            "• Только реально свободные юзернеймы\n"
            "• Стиль «Созвучные»",
            parse_mode="HTML",
            reply_markup=b.as_markup(),
        )
        logger.info(f"Lifetime premium activated for user {uid}")

    elif payload.startswith(PAYLOAD_MONTHLY):
        await db.set_premium(uid, days=config.SUBSCRIPTION_DAYS)
        # Check how long they now have total
        user = await db.get_user(uid)
        from datetime import datetime
        expiry = datetime.fromisoformat(user["premium_until"]).strftime("%d.%m.%Y")
        await message.answer(
            f"<b>Premium активирован!</b>\n\n"
            f"Подписка активна до <b>{expiry}</b>.\n\n"
            f"• Безлимитные генерации\n"
            f"• Только реально свободные юзернеймы\n"
            f"• Стиль «Созвучные»",
            parse_mode="HTML",
            reply_markup=b.as_markup(),
        )
        logger.info(f"Monthly premium activated for user {uid}, until {expiry}")

    else:
        logger.warning(f"Unknown payment payload: {payload}")
