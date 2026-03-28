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

PAYLOAD_PREFIX = "premium_1month_"


@router.callback_query(F.data == "premium")
async def show_premium_info(callback: CallbackQuery):
    db: Database = callback.bot.db
    uid = callback.from_user.id
    is_prem = await db.is_premium(uid)
    price = await db.get_user_price(uid)
    user = await db.get_user(uid)
    discount = user.get("referral_discount", 0) if user else 0

    b = InlineKeyboardBuilder()
    if not is_prem:
        b.button(
            text=f"⭐ Купить Premium — {price} звёзд",
            callback_data="buy_premium",
        )
        b.button(text="🔗 Получить скидку (реферал)", callback_data="referral")
    b.button(text="◀️ Назад", callback_data="main_menu")
    b.adjust(1)

    discount_line = f"\n💰 Твоя скидка: <b>{discount}⭐</b>" if discount else ""

    if is_prem:
        status_text = (
            "✅ У тебя уже активен <b>Premium</b>!\n\n"
            "Пользуйся безлимитной генерацией только свободных юзернеймов."
        )
    else:
        status_text = (
            f"🆓 <b>Free тариф</b>\n"
            f"• До {config.FREE_DAILY_LIMIT} генераций в день\n"
            f"• 30% результатов — свободные (не гарантировано)\n\n"
            f"⭐ <b>Premium — {price} звёзд / месяц</b>{discount_line}\n"
            f"• Безлимитные генерации\n"
            f"• <b>Только реально свободные</b> юзернеймы\n"
            f"• Проверка через Telegram API в реальном времени"
        )

    await callback.message.edit_text(
        f"⭐ <b>Premium подписка</b>\n\n{status_text}",
        parse_mode="HTML",
        reply_markup=b.as_markup(),
    )


@router.callback_query(F.data == "buy_premium")
async def buy_premium(callback: CallbackQuery):
    db: Database = callback.bot.db
    uid = callback.from_user.id
    price = await db.get_user_price(uid)

    await callback.bot.send_invoice(
        chat_id=uid,
        title="⭐ Premium подписка — 1 месяц",
        description=(
            "Безлимитная генерация только свободных юзернеймов в Telegram. "
            "Проверка через Telegram API в реальном времени."
        ),
        payload=f"{PAYLOAD_PREFIX}{uid}",
        currency="XTR",
        prices=[LabeledPrice(label="Premium (1 мес.)", amount=price)],
    )
    await callback.answer()


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    """Always approve — validation happens in successful_payment."""
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message):
    db: Database = message.bot.db
    uid = message.from_user.id
    payload = message.successful_payment.invoice_payload

    if not payload.startswith(PAYLOAD_PREFIX):
        logger.warning(f"Unknown payment payload: {payload}")
        return

    await db.set_premium(uid, days=config.SUBSCRIPTION_DAYS)

    b = InlineKeyboardBuilder()
    b.button(text="🎲 Генерировать", callback_data="generate")
    b.button(text="◀️ Главное меню",  callback_data="main_menu")
    b.adjust(2)

    await message.answer(
        f"🎉 <b>Premium активирован!</b>\n\n"
        f"Подписка действует <b>{config.SUBSCRIPTION_DAYS} дней</b>.\n\n"
        f"Теперь тебе доступна:\n"
        f"• Безлимитная генерация\n"
        f"• Только реально свободные юзернеймы\n\n"
        f"Жми 🎲 и находи редкие имена!",
        parse_mode="HTML",
        reply_markup=b.as_markup(),
    )
    logger.info(f"Premium activated for user {uid}")
