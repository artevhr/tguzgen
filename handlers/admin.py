import logging
from datetime import datetime
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import config
from database import Database

logger = logging.getLogger(__name__)
router = Router()


# ─── Admin guard ────────────────────────────────────────────────────────────

def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


# ─── FSM ────────────────────────────────────────────────────────────────────

class AdminStates(StatesGroup):
    broadcast_waiting   = State()
    broadcast_confirm   = State()
    user_info_waiting   = State()
    grant_id_waiting    = State()
    grant_days_waiting  = State()
    revoke_id_waiting   = State()


# ─── Keyboards ──────────────────────────────────────────────────────────────

def admin_panel_kb() -> object:
    b = InlineKeyboardBuilder()
    b.button(text="📊 Статистика",         callback_data="adm_stats")
    b.button(text="👥 Все пользователи",   callback_data="adm_users")
    b.button(text="🔍 Инфо о юзере",       callback_data="adm_user_info")
    b.button(text="🔑 Выдать Premium",      callback_data="adm_grant")
    b.button(text="❌ Забрать Premium",     callback_data="adm_revoke")
    b.button(text="📢 Рассылка",            callback_data="adm_broadcast")
    b.button(text="◀️ Главное меню",        callback_data="main_menu")
    b.adjust(2, 2, 2, 1)
    return b.as_markup()


def back_admin_kb() -> object:
    b = InlineKeyboardBuilder()
    b.button(text="◀️ Панель админа", callback_data="admin_panel")
    return b.as_markup()


# ─── Panel entry ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_panel")
async def show_admin_panel(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    await state.clear()
    await callback.message.edit_text(
        "⚙️ <b>Панель администратора</b>\n\nВыбери действие:",
        parse_mode="HTML",
        reply_markup=admin_panel_kb(),
    )


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer(
        "⚙️ <b>Панель администратора</b>\n\nВыбери действие:",
        parse_mode="HTML",
        reply_markup=admin_panel_kb(),
    )


# ─── Stats ──────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "adm_stats")
async def show_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    db: Database = callback.bot.db
    s = await db.get_stats()
    await callback.message.edit_text(
        f"<b>Статистика</b>\n\n"
        f"Всего: <b>{s['total']}</b>\n"
        f"Premium: <b>{s['premium']}</b> (навсегда: <b>{s['lifetime']}</b>)\n"
        f"Активны сегодня: <b>{s['active_today']}</b>\n"
        f"Генераций сегодня: <b>{s['gens_today']}</b>",
        parse_mode="HTML",
        reply_markup=back_admin_kb(),
    )


# ─── All users list ─────────────────────────────────────────────────────────

@router.callback_query(F.data == "adm_users")
async def show_all_users(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    db: Database = callback.bot.db
    users = await db.get_all_users()
    lines = []
    for u in users[:50]:  # cap to avoid huge message
        prem = "⭐" if u.get("is_premium") else "🆓"
        uname = f"@{u['username']}" if u.get("username") else f"#{u['user_id']}"
        lines.append(f"{prem} {uname} | {u['user_id']} | gen:{u.get('total_generations', 0)}")
    text = "\n".join(lines) or "Нет пользователей"
    if len(users) > 50:
        text += f"\n\n…и ещё {len(users) - 50} юзеров"
    await callback.message.edit_text(
        f"👥 <b>Пользователи ({len(users)})</b>\n\n<code>{text}</code>",
        parse_mode="HTML",
        reply_markup=back_admin_kb(),
    )


# ─── User info ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "adm_user_info")
async def ask_user_info_id(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.user_info_waiting)
    await callback.message.edit_text(
        "🔍 Введи Telegram ID или @username пользователя:",
        reply_markup=back_admin_kb(),
    )


@router.message(AdminStates.user_info_waiting)
async def show_user_info(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    db: Database = message.bot.db
    text = message.text.strip().lstrip("@")
    user = None

    try:
        uid = int(text)
        user = await db.get_user(uid)
    except ValueError:
        # Try by username
        users = await db.get_all_users()
        for u in users:
            if u.get("username", "").lower() == text.lower():
                user = u
                break

    await state.clear()
    try:
        await message.delete()
    except Exception:
        pass

    if not user:
        await message.answer(
            "❌ Пользователь не найден", reply_markup=back_admin_kb()
        )
        return

    prem_until = user.get("premium_until") or "—"
    if prem_until and prem_until != "—":
        try:
            prem_until = datetime.fromisoformat(prem_until).strftime("%d.%m.%Y %H:%M")
        except Exception:
            pass

    referrer = await db.get_referrer_name(user.get("referrer_id"))

    await message.answer(
        f"👤 <b>Пользователь</b>\n\n"
        f"ID: <code>{user['user_id']}</code>\n"
        f"Юзернейм: @{user.get('username') or '—'}\n"
        f"Имя: {user.get('first_name') or '—'}\n"
        f"Premium: {'✅' if user.get('is_premium') else '❌'}\n"
        f"Premium до: {prem_until}\n"
        f"Генераций всего: {user.get('total_generations', 0)}\n"
        f"Рефералов: {user.get('referral_count', 0)}\n"
        f"Скидка: {user.get('referral_discount', 0)}⭐\n"
        f"Пригласил: {referrer}\n"
        f"Регистрация: {user.get('created_at', '—')[:10]}",
        parse_mode="HTML",
        reply_markup=back_admin_kb(),
    )


# ─── Grant Premium ──────────────────────────────────────────────────────────

@router.callback_query(F.data == "adm_grant")
async def ask_grant_id(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.grant_id_waiting)
    await callback.message.edit_text(
        "🔑 Введи Telegram ID пользователя, которому выдать Premium:",
        reply_markup=back_admin_kb(),
    )


@router.message(AdminStates.grant_id_waiting)
async def grant_ask_days(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        uid = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Введи числовой ID")
        return
    await state.update_data(target_id=uid)
    await state.set_state(AdminStates.grant_days_waiting)
    try:
        await message.delete()
    except Exception:
        pass
    await message.answer(
        f"📅 ID: <code>{uid}</code>\n\nНа сколько дней выдать Premium? (введи число, 0 = навсегда):",
        parse_mode="HTML",
        reply_markup=back_admin_kb(),
    )


@router.message(AdminStates.grant_days_waiting)
async def grant_premium(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    db: Database = message.bot.db
    try:
        days = int(message.text.strip())
        if days < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи неотрицательное число")
        return

    data = await state.get_data()
    target_id = data.get("target_id")
    await state.clear()
    try:
        await message.delete()
    except Exception:
        pass

    if days == 0:
        await db.update_user(target_id, is_premium=1, premium_until=None)
        period = "навсегда"
    else:
        await db.set_premium(target_id, days=days)
        period = f"{days} дней"

    await message.answer(
        f"✅ Premium выдан пользователю <code>{target_id}</code> на <b>{period}</b>.",
        parse_mode="HTML",
        reply_markup=back_admin_kb(),
    )
    try:
        await message.bot.send_message(
            target_id,
            f"🎉 Администратор активировал тебе <b>Premium</b> на <b>{period}</b>!\n"
            f"Пользуйся безлимитной генерацией свободных юзернеймов.",
            parse_mode="HTML",
        )
    except Exception:
        pass


# ─── Revoke Premium ─────────────────────────────────────────────────────────

@router.callback_query(F.data == "adm_revoke")
async def ask_revoke_id(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.revoke_id_waiting)
    await callback.message.edit_text(
        "❌ Введи Telegram ID пользователя, у которого забрать Premium:",
        reply_markup=back_admin_kb(),
    )


@router.message(AdminStates.revoke_id_waiting)
async def revoke_premium(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    db: Database = message.bot.db
    try:
        uid = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Введи числовой ID")
        return
    await state.clear()
    try:
        await message.delete()
    except Exception:
        pass
    await db.revoke_premium(uid)
    await message.answer(
        f"✅ Premium снят с пользователя <code>{uid}</code>.",
        parse_mode="HTML",
        reply_markup=back_admin_kb(),
    )
    try:
        await message.bot.send_message(
            uid,
            "ℹ️ Твой Premium был деактивирован администратором.",
        )
    except Exception:
        pass


# ─── Broadcast ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "adm_broadcast")
async def ask_broadcast_msg(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.broadcast_waiting)
    await callback.message.edit_text(
        "📢 <b>Рассылка</b>\n\nОтправь сообщение для рассылки.\n"
        "Поддерживаются текст, фото, видео.\n\n"
        "<i>Поддерживается HTML-разметка в тексте.</i>",
        parse_mode="HTML",
        reply_markup=back_admin_kb(),
    )


@router.message(AdminStates.broadcast_waiting)
async def confirm_broadcast(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    # Store message info for broadcast
    await state.update_data(
        bc_text=message.text or message.caption or "",
        bc_photo=message.photo[-1].file_id if message.photo else None,
        bc_video=message.video.file_id if message.video else None,
        bc_entities=message.entities,
        bc_caption_entities=message.caption_entities,
    )
    await state.set_state(AdminStates.broadcast_confirm)
    db: Database = message.bot.db
    user_count = len(await db.get_all_user_ids())

    b = InlineKeyboardBuilder()
    b.button(text=f"✅ Отправить ({user_count} юзеров)", callback_data="adm_bc_confirm")
    b.button(text="❌ Отмена", callback_data="admin_panel")
    b.adjust(1)

    await message.answer(
        f"📋 Превью рассылки выше.\n\nОтправить <b>{user_count}</b> пользователям?",
        parse_mode="HTML",
        reply_markup=b.as_markup(),
    )


@router.callback_query(F.data == "adm_bc_confirm", AdminStates.broadcast_confirm)
async def do_broadcast(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    db: Database = callback.bot.db
    data = await state.get_data()
    await state.clear()

    user_ids = await db.get_all_user_ids()
    bc_text  = data.get("bc_text", "")
    bc_photo = data.get("bc_photo")
    bc_video = data.get("bc_video")

    await callback.message.edit_text(f"⏳ Рассылка запущена… (0 / {len(user_ids)})")

    ok = 0
    fail = 0
    for i, uid in enumerate(user_ids):
        try:
            if bc_photo:
                await callback.bot.send_photo(uid, bc_photo, caption=bc_text, parse_mode="HTML")
            elif bc_video:
                await callback.bot.send_video(uid, bc_video, caption=bc_text, parse_mode="HTML")
            else:
                await callback.bot.send_message(uid, bc_text, parse_mode="HTML")
            ok += 1
        except Exception:
            fail += 1

        if (i + 1) % 20 == 0:
            try:
                await callback.message.edit_text(
                    f"⏳ Рассылка… {i + 1} / {len(user_ids)} (✅{ok} ❌{fail})"
                )
            except Exception:
                pass

    await callback.message.edit_text(
        f"✅ <b>Рассылка завершена</b>\n\n"
        f"Отправлено: <b>{ok}</b>\nОшибок: <b>{fail}</b>",
        parse_mode="HTML",
        reply_markup=back_admin_kb(),
    )
