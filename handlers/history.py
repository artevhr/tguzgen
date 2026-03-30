from datetime import datetime
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import Database

router = Router()

_PAGE_SIZE = 15


def _style_label(style: str) -> str:
    return "созвучн." if style == "readable" else "случайн."


@router.callback_query(F.data == "history")
async def show_history(callback: CallbackQuery):
    await _render_history(callback, page=0)


@router.callback_query(F.data.startswith("history_page_"))
async def history_page(callback: CallbackQuery):
    page = int(callback.data.split("_")[-1])
    await _render_history(callback, page=page)


@router.callback_query(F.data == "history_clear_confirm")
async def history_clear_confirm(callback: CallbackQuery):
    b = InlineKeyboardBuilder()
    b.button(text="Да, удалить всё", callback_data="history_clear_do")
    b.button(text="Отмена",           callback_data="history")
    b.adjust(1)
    await callback.message.edit_text(
        "Удалить всю историю найденных юзернеймов?",
        reply_markup=b.as_markup(),
    )


@router.callback_query(F.data == "history_clear_do")
async def history_clear_do(callback: CallbackQuery):
    db: Database = callback.bot.db
    await db.clear_history(callback.from_user.id)
    b = InlineKeyboardBuilder()
    b.button(text="Назад", callback_data="profile")
    await callback.message.edit_text(
        "История очищена.",
        reply_markup=b.as_markup(),
    )


async def _render_history(callback: CallbackQuery, page: int):
    db: Database = callback.bot.db
    uid = callback.from_user.id
    all_items = await db.get_history(uid, limit=50)

    b = InlineKeyboardBuilder()

    if not all_items:
        b.button(text="Назад", callback_data="profile")
        await callback.message.edit_text(
            "<b>История генераций</b>\n\nПусто — здесь появятся свободные юзернеймы, "
            "найденные в Premium-режиме.",
            parse_mode="HTML",
            reply_markup=b.as_markup(),
        )
        return

    total_pages = max(1, (len(all_items) + _PAGE_SIZE - 1) // _PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    chunk = all_items[page * _PAGE_SIZE : (page + 1) * _PAGE_SIZE]

    lines = []
    for item in chunk:
        raw_date = item.get("found_at", "")
        try:
            dt = datetime.fromisoformat(raw_date).strftime("%d.%m %H:%M")
        except Exception:
            dt = "—"
        style_lbl = _style_label(item.get("style", "random"))
        lines.append(f"@{item['username']}  <i>{item['length']}симв, {style_lbl}, {dt}</i>")

    text = (
        f"<b>История</b> ({len(all_items)} юзернеймов, стр. {page+1}/{total_pages})\n\n"
        + "\n".join(lines)
    )

    # Pagination
    if total_pages > 1:
        if page > 0:
            b.button(text="← Пред.", callback_data=f"history_page_{page - 1}")
        if page < total_pages - 1:
            b.button(text="След. →", callback_data=f"history_page_{page + 1}")
        b.adjust(2)

    b.button(text="Очистить историю", callback_data="history_clear_confirm")
    b.button(text="Назад",             callback_data="profile")
    b.adjust(2) if total_pages > 1 else b.adjust(1)

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=b.as_markup(),
    )
