import asyncio
import logging
import random
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import config
from database import Database
from utils.generator import generate_username, generate_batch
from utils.checker import find_free_usernames

logger = logging.getLogger(__name__)
router = Router()


class GenerateStates(StatesGroup):
    choosing_length = State()
    choosing_count  = State()


# ─── Keyboards ──────────────────────────────────────────────────────────────

def length_kb() -> object:
    b = InlineKeyboardBuilder()
    for length in [4, 5, 6, 8, 10, 12]:
        b.button(text=str(length), callback_data=f"gl_{length}")
    b.button(text="✏️ Своя длина", callback_data="gl_custom")
    b.button(text="◀️ Назад",      callback_data="main_menu")
    b.adjust(3, 3, 1, 1)
    return b.as_markup()


def count_kb(is_premium: bool) -> object:
    b = InlineKeyboardBuilder()
    if is_premium:
        for cnt in [5, 10, 20, 50]:
            b.button(text=str(cnt), callback_data=f"gc_{cnt}")
        b.button(text="✏️ Своё кол-во", callback_data="gc_custom")
        b.button(text="◀️ Назад",        callback_data="gen_back_length")
        b.adjust(4, 1, 1)
    else:
        for cnt in [5, 10, 20]:
            b.button(text=str(cnt), callback_data=f"gc_{cnt}")
        b.button(text="30 (макс)", callback_data="gc_30")
        b.button(text="◀️ Назад",  callback_data="gen_back_length")
        b.adjust(4, 1)
    return b.as_markup()


def back_kb(cb: str) -> object:
    b = InlineKeyboardBuilder()
    b.button(text="◀️ Назад", callback_data=cb)
    return b.as_markup()


# ─── Entry ──────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "generate")
async def start_generate(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(GenerateStates.choosing_length)
    await state.update_data(msg_id=callback.message.message_id)
    await callback.message.edit_text(
        "📏 <b>Шаг 1 / 2 — Длина юзернейма</b>\n\n"
        "Telegram принимает от 5 до 32 символов.\n"
        "Очень короткие (2–4) практически всегда заняты.",
        parse_mode="HTML",
        reply_markup=length_kb(),
    )


# ─── Length step ────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("gl_"), GenerateStates.choosing_length)
async def pick_length(callback: CallbackQuery, state: FSMContext):
    db: Database = callback.bot["db"]
    val = callback.data[3:]

    if val == "custom":
        await callback.message.edit_text(
            "✏️ Введи длину (2–32):",
            reply_markup=back_kb("generate"),
        )
        return

    length = int(val)
    await state.update_data(length=length)
    is_prem = await db.is_premium(callback.from_user.id)
    await state.set_state(GenerateStates.choosing_count)
    await callback.message.edit_text(
        f"📊 <b>Шаг 2 / 2 — Количество</b>\n\nДлина: <b>{length}</b>",
        parse_mode="HTML",
        reply_markup=count_kb(is_prem),
    )


@router.message(GenerateStates.choosing_length)
async def custom_length_msg(message: Message, state: FSMContext):
    db: Database = message.bot["db"]
    try:
        length = int(message.text.strip())
        if not 2 <= length <= 32:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи число от 2 до 32")
        await message.delete()
        return

    try:
        await message.delete()
    except Exception:
        pass

    data = await state.get_data()
    is_prem = await db.is_premium(message.from_user.id)
    await state.update_data(length=length)
    await state.set_state(GenerateStates.choosing_count)

    msg_id = data.get("msg_id")
    text = f"📊 <b>Шаг 2 / 2 — Количество</b>\n\nДлина: <b>{length}</b>"
    if msg_id:
        try:
            await message.bot.edit_message_text(
                text,
                chat_id=message.chat.id,
                message_id=msg_id,
                parse_mode="HTML",
                reply_markup=count_kb(is_prem),
            )
            return
        except Exception:
            pass
    sent = await message.answer(text, parse_mode="HTML", reply_markup=count_kb(is_prem))
    await state.update_data(msg_id=sent.message_id)


@router.callback_query(F.data == "gen_back_length", GenerateStates.choosing_count)
async def back_to_length(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GenerateStates.choosing_length)
    await callback.message.edit_text(
        "📏 <b>Шаг 1 / 2 — Длина юзернейма</b>\n\n"
        "Telegram принимает от 5 до 32 символов.\n"
        "Очень короткие (2–4) практически всегда заняты.",
        parse_mode="HTML",
        reply_markup=length_kb(),
    )


# ─── Count step ─────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("gc_"), GenerateStates.choosing_count)
async def pick_count(callback: CallbackQuery, state: FSMContext):
    db: Database = callback.bot["db"]
    val = callback.data[3:]

    if val == "custom":
        await callback.message.edit_text(
            "✏️ Введи количество юзернеймов (1–200):",
            reply_markup=back_kb("gen_back_length"),
        )
        return

    count = int(val)
    data = await state.get_data()
    length = data.get("length", 6)
    await state.clear()

    await _run_generation(callback.bot, db, callback.from_user.id, length, count, callback.message)


@router.message(GenerateStates.choosing_count)
async def custom_count_msg(message: Message, state: FSMContext):
    db: Database = message.bot["db"]
    is_prem = await db.is_premium(message.from_user.id)
    try:
        count = int(message.text.strip())
        if count < 1:
            raise ValueError
        if not is_prem:
            count = min(count, config.FREE_DAILY_LIMIT)
        else:
            count = min(count, 200)
    except ValueError:
        await message.answer("❌ Введи число от 1 до 200")
        try:
            await message.delete()
        except Exception:
            pass
        return

    data = await state.get_data()
    length = data.get("length", 6)
    msg_id = data.get("msg_id")
    await state.clear()

    try:
        await message.delete()
    except Exception:
        pass

    # Use the original bot message to edit, or send new
    if msg_id:
        try:
            bot_msg = type("FakeMsg", (), {
                "chat": message.chat,
                "message_id": msg_id,
                "bot": message.bot,
            })()

            class FakeEditableMsg:
                def __init__(self):
                    self.chat = message.chat
                    self.message_id = msg_id
                    self.bot = message.bot

                async def edit_text(self, text, **kwargs):
                    await message.bot.edit_message_text(
                        text, chat_id=message.chat.id, message_id=msg_id, **kwargs
                    )

            await _run_generation(message.bot, db, message.from_user.id, length, count, FakeEditableMsg())
            return
        except Exception:
            pass
    sent = await message.answer("⏳ Обрабатываю…")
    await _run_generation(message.bot, db, message.from_user.id, length, count, sent)


# ─── Core generation logic ──────────────────────────────────────────────────

async def _run_generation(bot: Bot, db: Database, user_id: int, length: int, count: int, editable_msg):
    is_prem = await db.is_premium(user_id)

    # Free-tier daily limit check
    if not is_prem:
        daily_used = await db.get_daily_generations(user_id)
        remaining = config.FREE_DAILY_LIMIT - daily_used
        if remaining <= 0:
            b = InlineKeyboardBuilder()
            b.button(text="⭐ Купить Premium", callback_data="premium")
            b.button(text="◀️ Назад",          callback_data="main_menu")
            b.adjust(1)
            await editable_msg.edit_text(
                "⛔ <b>Дневной лимит исчерпан</b>\n\n"
                f"Free тариф: {config.FREE_DAILY_LIMIT} генераций в сутки.\n"
                "Обновится завтра или купи Premium для безлимита.",
                parse_mode="HTML",
                reply_markup=b.as_markup(),
            )
            return
        count = min(count, remaining)

    if is_prem:
        await _generate_premium(bot, db, user_id, length, count, editable_msg)
    else:
        await _generate_free(db, user_id, length, count, editable_msg)


async def _generate_free(db: Database, user_id: int, length: int, count: int, editable_msg):
    """Free tier: generate usernames, label ~30% as available (not actually checked)."""
    usernames = generate_batch(length, count)
    n_avail = max(1, round(len(usernames) * config.FREE_AVAILABLE_RATIO))
    avail_idx = set(random.sample(range(len(usernames)), min(n_avail, len(usernames))))

    lines = []
    for i, u in enumerate(usernames):
        if i in avail_idx:
            lines.append(f"✅ @{u}")
        else:
            lines.append(f"❌ @{u}")

    result_text = "\n".join(lines)
    b = InlineKeyboardBuilder()
    b.button(text="🔄 Ещё раз",     callback_data="generate")
    b.button(text="⭐ Premium",     callback_data="premium")
    b.button(text="◀️ Главное меню", callback_data="main_menu")
    b.adjust(2, 1)

    await db.increment_generations(user_id, count)

    daily_used = await db.get_daily_generations(user_id)
    remaining = max(0, config.FREE_DAILY_LIMIT - daily_used)

    await editable_msg.edit_text(
        f"🎲 <b>Результат генерации</b> (длина: {length}, кол-во: {count})\n\n"
        f"{result_text}\n\n"
        f"🆓 <i>Free тариф — точность не гарантирована.\n"
        f"Осталось генераций сегодня: {remaining}</i>\n"
        f"💡 <b>Premium</b> — только реально свободные юзернеймы!",
        parse_mode="HTML",
        reply_markup=b.as_markup(),
    )


async def _generate_premium(bot: Bot, db: Database, user_id: int, length: int, count: int, editable_msg):
    """Premium tier: actually check each username via Telegram API."""
    await editable_msg.edit_text(
        f"⏳ <b>Ищу свободные юзернеймы…</b>\n\n"
        f"Длина: {length} | Нужно найти: {count}\n"
        f"Это может занять немного времени.",
        parse_mode="HTML",
    )

    checked_count = [0]
    last_edit = [0.0]

    async def progress_cb(found: int, target: int):
        import time
        now = time.time()
        if now - last_edit[0] < 2.0:
            return
        last_edit[0] = now
        checked_count[0] = found
        try:
            await editable_msg.edit_text(
                f"⏳ <b>Ищу свободные юзернеймы…</b>\n\n"
                f"Длина: {length} | Найдено: {found} / {target}\n"
                f"Проверяю кандидатов…",
                parse_mode="HTML",
            )
        except Exception:
            pass

    found = await find_free_usernames(
        bot=bot,
        length=length,
        target_count=count,
        generate_fn=generate_username,
        progress_callback=progress_cb,
        delay=0.35,
    )

    b = InlineKeyboardBuilder()
    b.button(text="🔄 Ещё раз",      callback_data="generate")
    b.button(text="◀️ Главное меню",  callback_data="main_menu")
    b.adjust(2)

    if not found:
        await editable_msg.edit_text(
            "😔 <b>Не удалось найти свободные юзернеймы</b>\n\n"
            "Попробуй другую длину — чем больше символов, тем выше шанс найти свободный.",
            parse_mode="HTML",
            reply_markup=b.as_markup(),
        )
        return

    await db.increment_generations(user_id, len(found))

    lines = "\n".join(f"✅ @{u}" for u in found)
    await editable_msg.edit_text(
        f"🎲 <b>Результат генерации</b> (длина: {length})\n\n"
        f"{lines}\n\n"
        f"⭐ <b>Premium</b> — все юзернеймы проверены и свободны!\n"
        f"<i>Найдено: {len(found)} из {count} запрошенных</i>",
        parse_mode="HTML",
        reply_markup=b.as_markup(),
    )
