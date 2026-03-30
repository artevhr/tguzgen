import asyncio
import logging
import time

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import config
from database import Database
from utils.generator import generate_username, generate_batch, generate_readable_username, generate_readable_batch
from utils.checker import find_free_usernames, check_username

logger = logging.getLogger(__name__)
router = Router()

STYLE_RANDOM   = "random"
STYLE_READABLE = "readable"


class GenerateStates(StatesGroup):
    choosing_style  = State()
    choosing_length = State()
    choosing_count  = State()


# ─── Keyboards ───────────────────────────────────────────────────────────────

def style_kb() -> object:
    b = InlineKeyboardBuilder()
    b.button(text="Случайные",  callback_data=f"gs_{STYLE_RANDOM}")
    b.button(text="Созвучные",  callback_data=f"gs_{STYLE_READABLE}")
    b.button(text="Назад",      callback_data="main_menu")
    b.adjust(2, 1)
    return b.as_markup()


def length_kb() -> object:
    b = InlineKeyboardBuilder()
    for length in [4, 5, 6, 8, 10, 12]:
        b.button(text=str(length), callback_data=f"gl_{length}")
    b.button(text="Своя длина", callback_data="gl_custom")
    b.button(text="Назад",      callback_data="gen_back_style")
    b.adjust(3, 3, 1, 1)
    return b.as_markup()


def count_kb(is_premium: bool) -> object:
    b = InlineKeyboardBuilder()
    if is_premium:
        for cnt in [5, 10, 20, 50]:
            b.button(text=str(cnt), callback_data=f"gc_{cnt}")
        b.button(text="Своё кол-во", callback_data="gc_custom")
        b.button(text="Назад",       callback_data="gen_back_length")
        b.adjust(4, 1, 1)
    else:
        for cnt in [5, 10, 20]:
            b.button(text=str(cnt), callback_data=f"gc_{cnt}")
        b.button(text="30 (макс)", callback_data="gc_30")
        b.button(text="Назад",     callback_data="gen_back_length")
        b.adjust(4, 1)
    return b.as_markup()


def back_kb(cb: str) -> object:
    b = InlineKeyboardBuilder()
    b.button(text="Назад", callback_data=cb)
    return b.as_markup()


def _style_label(style: str) -> str:
    return "Созвучные" if style == STYLE_READABLE else "Случайные"


# ─── Step 1: Style ───────────────────────────────────────────────────────────

@router.callback_query(F.data == "generate")
async def start_generate(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(GenerateStates.choosing_style)
    await state.update_data(msg_id=callback.message.message_id)
    await callback.message.edit_text(
        "<b>Шаг 1 / 3 — Стиль</b>\n\n"
        "<b>Случайные</b> — полностью рандомные комбинации букв/цифр.\n"
        "<b>Созвучные</b> — читаемые, брендовые: durove, nova, galaxi, nftlab и подобные.",
        parse_mode="HTML",
        reply_markup=style_kb(),
    )


@router.callback_query(F.data.startswith("gs_"), GenerateStates.choosing_style)
async def pick_style(callback: CallbackQuery, state: FSMContext):
    style = callback.data[3:]
    if style not in (STYLE_RANDOM, STYLE_READABLE):
        await callback.answer("Неизвестный стиль")
        return
    await state.update_data(style=style)
    await state.set_state(GenerateStates.choosing_length)
    await callback.message.edit_text(
        f"<b>Шаг 2 / 3 — Длина</b>\n\nСтиль: <b>{_style_label(style)}</b>\n\n"
        "Telegram допускает от 5 до 32 символов.\n"
        "Чем длиннее — тем больше шанс найти свободный.",
        parse_mode="HTML",
        reply_markup=length_kb(),
    )


@router.callback_query(F.data == "gen_back_style")
async def back_to_style(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GenerateStates.choosing_style)
    await callback.message.edit_text(
        "<b>Шаг 1 / 3 — Стиль</b>\n\n"
        "<b>Случайные</b> — полностью рандомные комбинации букв/цифр.\n"
        "<b>Созвучные</b> — читаемые, брендовые: durove, nova, galaxi, nftlab и подобные.",
        parse_mode="HTML",
        reply_markup=style_kb(),
    )


# ─── Step 2: Length ──────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("gl_"), GenerateStates.choosing_length)
async def pick_length(callback: CallbackQuery, state: FSMContext):
    db: Database = callback.bot.db
    val = callback.data[3:]
    data = await state.get_data()
    style = data.get("style", STYLE_RANDOM)

    if val == "custom":
        await callback.message.edit_text(
            "Введи длину (2–32):",
            reply_markup=back_kb("gen_back_style"),
        )
        return

    length = int(val)
    await state.update_data(length=length)
    is_prem = await db.is_premium(callback.from_user.id)
    await state.set_state(GenerateStates.choosing_count)
    await callback.message.edit_text(
        f"<b>Шаг 3 / 3 — Количество</b>\n\n"
        f"Стиль: <b>{_style_label(style)}</b>  |  Длина: <b>{length}</b>",
        parse_mode="HTML",
        reply_markup=count_kb(is_prem),
    )


@router.message(GenerateStates.choosing_length)
async def custom_length_msg(message: Message, state: FSMContext):
    db: Database = message.bot.db
    try:
        length = int(message.text.strip())
        if not 2 <= length <= 32:
            raise ValueError
    except ValueError:
        await message.answer("Введи число от 2 до 32")
        try:
            await message.delete()
        except Exception:
            pass
        return

    try:
        await message.delete()
    except Exception:
        pass

    data = await state.get_data()
    style = data.get("style", STYLE_RANDOM)
    is_prem = await db.is_premium(message.from_user.id)
    await state.update_data(length=length)
    await state.set_state(GenerateStates.choosing_count)

    text = (
        f"<b>Шаг 3 / 3 — Количество</b>\n\n"
        f"Стиль: <b>{_style_label(style)}</b>  |  Длина: <b>{length}</b>"
    )
    msg_id = data.get("msg_id")
    if msg_id:
        try:
            await message.bot.edit_message_text(
                text, chat_id=message.chat.id, message_id=msg_id,
                parse_mode="HTML", reply_markup=count_kb(is_prem),
            )
            return
        except Exception:
            pass
    sent = await message.answer(text, parse_mode="HTML", reply_markup=count_kb(is_prem))
    await state.update_data(msg_id=sent.message_id)


@router.callback_query(F.data == "gen_back_length", GenerateStates.choosing_count)
async def back_to_length(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    style = data.get("style", STYLE_RANDOM)
    await state.set_state(GenerateStates.choosing_length)
    await callback.message.edit_text(
        f"<b>Шаг 2 / 3 — Длина</b>\n\nСтиль: <b>{_style_label(style)}</b>",
        parse_mode="HTML",
        reply_markup=length_kb(),
    )


# ─── Step 3: Count ───────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("gc_"), GenerateStates.choosing_count)
async def pick_count(callback: CallbackQuery, state: FSMContext):
    db: Database = callback.bot.db
    val = callback.data[3:]

    if val == "custom":
        await callback.message.edit_text(
            "Введи количество юзернеймов (1–200):",
            reply_markup=back_kb("gen_back_length"),
        )
        return

    count = int(val)
    data = await state.get_data()
    length = data.get("length", 6)
    style  = data.get("style", STYLE_RANDOM)
    await state.clear()
    await _run_generation(callback.bot, db, callback.from_user.id, length, count, style, callback.message)


@router.message(GenerateStates.choosing_count)
async def custom_count_msg(message: Message, state: FSMContext):
    db: Database = message.bot.db
    is_prem = await db.is_premium(message.from_user.id)
    try:
        count = int(message.text.strip())
        if count < 1:
            raise ValueError
        count = min(count, 200) if is_prem else min(count, config.FREE_DAILY_LIMIT)
    except ValueError:
        await message.answer("Введи число от 1 до 200")
        try:
            await message.delete()
        except Exception:
            pass
        return

    data = await state.get_data()
    length = data.get("length", 6)
    style  = data.get("style", STYLE_RANDOM)
    msg_id = data.get("msg_id")
    await state.clear()

    try:
        await message.delete()
    except Exception:
        pass

    if msg_id:
        try:
            class FakeMsg:
                def __init__(self):
                    self.chat = message.chat
                    self.message_id = msg_id
                    self.bot = message.bot

                async def edit_text(self, text, **kwargs):
                    await message.bot.edit_message_text(
                        text, chat_id=message.chat.id, message_id=msg_id, **kwargs
                    )
            await _run_generation(message.bot, db, message.from_user.id, length, count, style, FakeMsg())
            return
        except Exception:
            pass

    sent = await message.answer("Обрабатываю...")
    await _run_generation(message.bot, db, message.from_user.id, length, count, style, sent)


# ─── Core logic ──────────────────────────────────────────────────────────────

async def _run_generation(
    bot: Bot, db: Database, user_id: int,
    length: int, count: int, style: str, editable_msg,
):
    is_prem = await db.is_premium(user_id)

    if not is_prem:
        daily_used = await db.get_daily_generations(user_id)
        remaining = config.FREE_DAILY_LIMIT - daily_used
        if remaining <= 0:
            b = InlineKeyboardBuilder()
            b.button(text="Купить Premium", callback_data="premium")
            b.button(text="Назад",          callback_data="main_menu")
            b.adjust(1)
            await editable_msg.edit_text(
                "<b>Дневной лимит исчерпан</b>\n\n"
                f"Free тариф: {config.FREE_DAILY_LIMIT} генераций в сутки.\n"
                "Обновится завтра или купи Premium.",
                parse_mode="HTML",
                reply_markup=b.as_markup(),
            )
            return
        count = min(count, remaining)

    if is_prem:
        await _generate_premium(bot, db, user_id, length, count, style, editable_msg)
    else:
        await _generate_free(bot, db, user_id, length, count, style, editable_msg)


async def _generate_free(
    bot: Bot, db: Database, user_id: int,
    length: int, count: int, style: str, editable_msg,
):
    """
    Free tier: generate a batch, then check ~30% of them via Telegram API + Fragment.
    Checked ones that pass → 'свободен', rest → 'занят'. No emojis.
    """
    import asyncio as _asyncio

    gen_fn = generate_readable_batch if style == STYLE_READABLE else generate_batch
    check_fn = generate_readable_username if style == STYLE_READABLE else generate_username

    # Generate more than needed so we have spare "занят" candidates
    pool = gen_fn(length, max(count, count * 4))
    if len(pool) < count:
        pool = pool + gen_fn(length, count - len(pool))
    pool = pool[:count]

    n_check = max(1, round(len(pool) * 0.30))
    to_check = pool[:n_check]
    no_check = pool[n_check:]

    # Show progress while checking
    await editable_msg.edit_text(
        f"<b>Проверяю {n_check} из {count} юзернеймов...</b>",
        parse_mode="HTML",
    )

    free_names = []
    taken_names = list(no_check)

    for username in to_check:
        is_free = await check_username(bot, username)
        if is_free:
            free_names.append(username)
        else:
            taken_names.append(username)
        await _asyncio.sleep(0.35)

    # All names in one plain list — free ones first, then unchecked
    all_names = free_names + taken_names
    result_text = "\n".join(f'<a href="https://t.me/{u}">@{u}</a>' for u in all_names)
    b = InlineKeyboardBuilder()
    b.button(text="Ещё раз",       callback_data="generate")
    b.button(text="Купить Premium", callback_data="premium")
    b.button(text="Главное меню",   callback_data="main_menu")
    b.adjust(2, 1)

    await db.increment_generations(user_id, count)
    daily_used = await db.get_daily_generations(user_id)
    remaining = max(0, config.FREE_DAILY_LIMIT - daily_used)

    checked_note = f"Проверено через Telegram + Fragment: {n_check} шт."
    text = (
        f"<b>Юзернеймы</b> — {_style_label(style)}, длина {length}\n\n"
        f"{result_text}\n\n"
        f"{checked_note}\n"
        f"Остальные не проверялись.\n"
        f"Осталось сегодня: {remaining}/{config.FREE_DAILY_LIMIT}\n\n"
        f"<b>Premium</b> — все юзернеймы проверяются."
    )
    await editable_msg.edit_text(text, parse_mode="HTML", reply_markup=b.as_markup())


async def _generate_premium(
    bot: Bot, db: Database, user_id: int,
    length: int, count: int, style: str, editable_msg,
):
    """Premium: check each candidate against Telegram API + Fragment."""
    await editable_msg.edit_text(
        f"<b>Ищу свободные юзернеймы...</b>\n\n"
        f"Стиль: {_style_label(style)}  |  Длина: {length}  |  Нужно: {count}\n"
        f"Это займёт немного времени.",
        parse_mode="HTML",
    )

    last_edit = [0.0]

    async def progress_cb(found: int, target: int):
        now = time.time()
        if now - last_edit[0] < 2.0:
            return
        last_edit[0] = now
        try:
            await editable_msg.edit_text(
                f"<b>Ищу свободные юзернеймы...</b>\n\n"
                f"Стиль: {_style_label(style)}  |  Длина: {length}\n"
                f"Найдено: {found} / {target}",
                parse_mode="HTML",
            )
        except Exception:
            pass

    gen_fn = generate_readable_username if style == STYLE_READABLE else generate_username

    found = await find_free_usernames(
        bot=bot,
        length=length,
        target_count=count,
        generate_fn=gen_fn,
        progress_callback=progress_cb,
        delay=0.35,
    )

    b = InlineKeyboardBuilder()
    b.button(text="Ещё раз",     callback_data="generate")
    b.button(text="История",     callback_data="history")
    b.button(text="Главное меню", callback_data="main_menu")
    b.adjust(2, 1)

    if not found:
        await editable_msg.edit_text(
            "<b>Не удалось найти свободные юзернеймы</b>\n\n"
            "Попробуй другую длину или стиль — чем длиннее, тем выше шанс.",
            parse_mode="HTML",
            reply_markup=b.as_markup(),
        )
        return

    # Save to history
    await db.add_to_history(user_id, found, length, style)
    await db.increment_generations(user_id, len(found))

    lines = "\n".join(f'<a href="https://t.me/{u}">@{u}</a>' for u in found)
    await editable_msg.edit_text(
        f"<b>Свободные юзернеймы</b> — {_style_label(style)}, длина {length}\n\n"
        f"<code>{lines}</code>\n\n"
        f"Проверено: Telegram API + Fragment. Найдено: {len(found)} из {count}.",
        parse_mode="HTML",
        reply_markup=b.as_markup(),
    )
