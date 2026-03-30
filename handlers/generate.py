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
from utils.generator import gen_one, gen_batch
from utils.checker import find_free_usernames, check_username

logger = logging.getLogger(__name__)
router = Router()

# ─── Constants ───────────────────────────────────────────────────────────────

STYLE_RANDOM   = "random"
STYLE_READABLE = "readable"

FILTER_STANDARD = "standard"
FILTER_NO_DIGITS = "no_digits"
FILTER_LETTERS  = "letters_only"

_STYLE_LABELS = {
    STYLE_RANDOM:   "Случайные",
    STYLE_READABLE: "Созвучные",
}
_FILTER_LABELS = {
    FILTER_STANDARD:  "Стандарт",
    FILTER_NO_DIGITS: "Без цифр",
    FILTER_LETTERS:   "Обычные",
}


def _slabel(style: str) -> str:
    return _STYLE_LABELS.get(style, style)

def _flabel(f: str) -> str:
    return _FILTER_LABELS.get(f, f)


# ─── FSM ─────────────────────────────────────────────────────────────────────

class GenerateStates(StatesGroup):
    choosing_style  = State()
    choosing_filter = State()
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


def filter_kb() -> object:
    b = InlineKeyboardBuilder()
    b.button(text="Стандарт",   callback_data=f"gf_{FILTER_STANDARD}")
    b.button(text="Без цифр",   callback_data=f"gf_{FILTER_NO_DIGITS}")
    b.button(text="Обычные",    callback_data=f"gf_{FILTER_LETTERS}")
    b.button(text="Назад",      callback_data="gen_back_style")
    b.adjust(3, 1)
    return b.as_markup()


def length_kb() -> object:
    b = InlineKeyboardBuilder()
    for length in [4, 5, 6, 8, 10, 12]:
        b.button(text=str(length), callback_data=f"gl_{length}")
    b.button(text="Своя длина", callback_data="gl_custom")
    b.button(text="Назад",      callback_data="gen_back_filter")
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


def _header(style: str, filter_: str, length: int | None = None) -> str:
    parts = [_slabel(style), _flabel(filter_)]
    if length:
        parts.append(f"длина {length}")
    return " · ".join(parts)


# ─── Step 1: Style ───────────────────────────────────────────────────────────

@router.callback_query(F.data == "generate")
async def start_generate(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(GenerateStates.choosing_style)
    await state.update_data(msg_id=callback.message.message_id)
    await callback.message.edit_text(
        "<b>Шаг 1 / 4 — Стиль</b>\n\n"
        "<b>Случайные</b> — рандомные комбинации символов.\n"
        "<b>Созвучные</b> — читаемые, брендовые: durove, nova, nftlab...",
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
    await state.set_state(GenerateStates.choosing_filter)
    await callback.message.edit_text(
        f"<b>Шаг 2 / 4 — Символы</b>\n\nСтиль: <b>{_slabel(style)}</b>\n\n"
        "<b>Стандарт</b> — буквы, цифры, подчёркивание.\n"
        "<b>Без цифр</b> — только буквы и подчёркивание.\n"
        "<b>Обычные</b> — только буквы, ничего лишнего.",
        parse_mode="HTML",
        reply_markup=filter_kb(),
    )


@router.callback_query(F.data == "gen_back_style")
async def back_to_style(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GenerateStates.choosing_style)
    await callback.message.edit_text(
        "<b>Шаг 1 / 4 — Стиль</b>\n\n"
        "<b>Случайные</b> — рандомные комбинации символов.\n"
        "<b>Созвучные</b> — читаемые, брендовые: durove, nova, nftlab...",
        parse_mode="HTML",
        reply_markup=style_kb(),
    )


# ─── Step 2: Filter ──────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("gf_"), GenerateStates.choosing_filter)
async def pick_filter(callback: CallbackQuery, state: FSMContext):
    filter_ = callback.data[3:]
    if filter_ not in (FILTER_STANDARD, FILTER_NO_DIGITS, FILTER_LETTERS):
        await callback.answer("Неизвестный фильтр")
        return
    await state.update_data(filter=filter_)
    await state.set_state(GenerateStates.choosing_length)
    data = await state.get_data()
    style = data.get("style", STYLE_RANDOM)
    await callback.message.edit_text(
        f"<b>Шаг 3 / 4 — Длина</b>\n\n{_slabel(style)} · {_flabel(filter_)}\n\n"
        "Telegram принимает от 5 до 32 символов.\n"
        "Чем длиннее — тем больше шанс найти свободный.",
        parse_mode="HTML",
        reply_markup=length_kb(),
    )


@router.callback_query(F.data == "gen_back_filter")
async def back_to_filter(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    style = data.get("style", STYLE_RANDOM)
    await state.set_state(GenerateStates.choosing_filter)
    await callback.message.edit_text(
        f"<b>Шаг 2 / 4 — Символы</b>\n\nСтиль: <b>{_slabel(style)}</b>\n\n"
        "<b>Стандарт</b> — буквы, цифры, подчёркивание.\n"
        "<b>Без цифр</b> — только буквы и подчёркивание.\n"
        "<b>Обычные</b> — только буквы, ничего лишнего.",
        parse_mode="HTML",
        reply_markup=filter_kb(),
    )


# ─── Step 3: Length ──────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("gl_"), GenerateStates.choosing_length)
async def pick_length(callback: CallbackQuery, state: FSMContext):
    db: Database = callback.bot.db
    val = callback.data[3:]
    data = await state.get_data()
    style   = data.get("style",  STYLE_RANDOM)
    filter_ = data.get("filter", FILTER_STANDARD)

    if val == "custom":
        await callback.message.edit_text(
            "Введи длину (2–32):",
            reply_markup=back_kb("gen_back_filter"),
        )
        return

    length = int(val)
    await state.update_data(length=length)
    is_prem = await db.is_premium(callback.from_user.id)
    await state.set_state(GenerateStates.choosing_count)
    await callback.message.edit_text(
        f"<b>Шаг 4 / 4 — Количество</b>\n\n{_header(style, filter_, length)}",
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
    style   = data.get("style",  STYLE_RANDOM)
    filter_ = data.get("filter", FILTER_STANDARD)
    is_prem = await db.is_premium(message.from_user.id)
    await state.update_data(length=length)
    await state.set_state(GenerateStates.choosing_count)

    text = f"<b>Шаг 4 / 4 — Количество</b>\n\n{_header(style, filter_, length)}"
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
    style   = data.get("style",  STYLE_RANDOM)
    filter_ = data.get("filter", FILTER_STANDARD)
    await state.set_state(GenerateStates.choosing_length)
    await callback.message.edit_text(
        f"<b>Шаг 3 / 4 — Длина</b>\n\n{_slabel(style)} · {_flabel(filter_)}",
        parse_mode="HTML",
        reply_markup=length_kb(),
    )


# ─── Step 4: Count ───────────────────────────────────────────────────────────

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
    data  = await state.get_data()
    length  = data.get("length", 6)
    style   = data.get("style",  STYLE_RANDOM)
    filter_ = data.get("filter", FILTER_STANDARD)
    await state.clear()
    await _run_generation(callback.bot, db, callback.from_user.id, length, count, style, filter_, callback.message)


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

    data    = await state.get_data()
    length  = data.get("length", 6)
    style   = data.get("style",  STYLE_RANDOM)
    filter_ = data.get("filter", FILTER_STANDARD)
    msg_id  = data.get("msg_id")
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
            await _run_generation(message.bot, db, message.from_user.id, length, count, style, filter_, FakeMsg())
            return
        except Exception:
            pass

    sent = await message.answer("Обрабатываю...")
    await _run_generation(message.bot, db, message.from_user.id, length, count, style, filter_, sent)


# ─── Core logic ──────────────────────────────────────────────────────────────

async def _run_generation(
    bot: Bot, db: Database, user_id: int,
    length: int, count: int, style: str, filter_: str, editable_msg,
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
        await _generate_premium(bot, db, user_id, length, count, style, filter_, editable_msg)
    else:
        await _generate_free(bot, db, user_id, length, count, style, filter_, editable_msg)


async def _generate_free(
    bot: Bot, db: Database, user_id: int,
    length: int, count: int, style: str, filter_: str, editable_msg,
):
    """Free: generate batch, check 30% via TG API + Fragment, free names go first."""
    pool = gen_batch(style, length, count, filter_)

    n_check  = max(1, round(len(pool) * 0.30))
    to_check = pool[:n_check]
    no_check = pool[n_check:]

    await editable_msg.edit_text(
        f"<b>Проверяю {n_check} из {count} юзернеймов...</b>",
        parse_mode="HTML",
    )

    free_names  = []
    other_names = list(no_check)

    for username in to_check:
        if await check_username(bot, username):
            free_names.append(username)
        else:
            other_names.append(username)
        await asyncio.sleep(0.35)

    all_names   = free_names + other_names
    result_text = "\n".join(f'<a href="https://t.me/{u}">@{u}</a>' for u in all_names)

    b = InlineKeyboardBuilder()
    b.button(text="Ещё раз",       callback_data="generate")
    b.button(text="Купить Premium", callback_data="premium")
    b.button(text="Главное меню",   callback_data="main_menu")
    b.adjust(2, 1)

    await db.increment_generations(user_id, count)
    daily_used = await db.get_daily_generations(user_id)
    remaining  = max(0, config.FREE_DAILY_LIMIT - daily_used)

    text = (
        f"<b>Юзернеймы</b> — {_header(style, filter_, length)}\n\n"
        f"{result_text}\n\n"
        f"Проверено через Telegram + Fragment: {n_check} шт. Остальные не проверялись.\n"
        f"Осталось сегодня: {remaining}/{config.FREE_DAILY_LIMIT}\n\n"
        f"<b>Premium</b> — все юзернеймы проверяются."
    )
    await editable_msg.edit_text(text, parse_mode="HTML", reply_markup=b.as_markup())


async def _generate_premium(
    bot: Bot, db: Database, user_id: int,
    length: int, count: int, style: str, filter_: str, editable_msg,
):
    """Premium: find free usernames via full TG API + Fragment check."""
    await editable_msg.edit_text(
        f"<b>Ищу свободные юзернеймы...</b>\n\n"
        f"{_header(style, filter_, length)}  |  Нужно: {count}\n"
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
                f"{_header(style, filter_, length)}\n"
                f"Найдено: {found} / {target}",
                parse_mode="HTML",
            )
        except Exception:
            pass

    found = await find_free_usernames(
        bot=bot,
        length=length,
        target_count=count,
        generate_fn=lambda l: gen_one(style, l, filter_),
        progress_callback=progress_cb,
        delay=0.35,
    )

    b = InlineKeyboardBuilder()
    b.button(text="Ещё раз",      callback_data="generate")
    b.button(text="История",      callback_data="history")
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

    style_key = f"{style}_{filter_}"
    await db.add_to_history(user_id, found, length, style_key)
    await db.increment_generations(user_id, len(found))

    lines = "\n".join(f'<a href="https://t.me/{u}">@{u}</a>' for u in found)
    await editable_msg.edit_text(
        f"<b>Свободные юзернеймы</b> — {_header(style, filter_, length)}\n\n"
        f"{lines}\n\n"
        f"Проверено: Telegram API + Fragment. Найдено: {len(found)} из {count}.",
        parse_mode="HTML",
        reply_markup=b.as_markup(),
    )
