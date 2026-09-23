import os
import re
import asyncio
import contextlib
import html
import random
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest

from src import database as db
from src.bot import keyboards as kb
from src.bot import auth_flow
from src.bot.translit import t
from src.config import ADMIN_ID, ADMIN_CHANNEL_ID, PAYMENT_CARD_NUMBER, PAYMENT_CARD_HOLDER
from src.logger import setup_logger

logger = setup_logger("handlers")
router = Router()

# ==================== FSM STATES ====================
class AuthStates(StatesGroup):
    waiting_for_phone = State()
    waiting_for_code = State()
    waiting_for_2fa = State()

class PaymentStates(StatesGroup):
    waiting_for_cheque = State()

class PromoStates(StatesGroup):
    waiting_for_promocode = State()

class BotStates(StatesGroup):
    waiting_for_source_chat = State()
    waiting_for_custom_timing = State()
    waiting_for_custom_jitter = State()

class AdminStates(StatesGroup):
    waiting_for_broadcast = State()
    waiting_for_group_target = State()
    waiting_for_group_broadcast = State()

# Pricing definition (months -> (amount_uzs, display_title, bonus_days))
PRICING_PLANS = {
    1: (25000, "1 Oy", 30),
    3: (65000, "3 Oy", 90),
    6: (120000, "6 Oy", 180),
    12: (225000, "12 Oy + 1 Oy Bepul 🔥", 390)
}

def calculate_effective_plan_prices(campaign: Optional[Dict[str, Any]] = None, promo: Optional[Dict[str, Any]] = None) -> Dict[int, Dict[str, Any]]:
    """
    Calculates final prices, original prices, badges, and detailed calculation breakdowns
    for each plan (1, 3, 6, 12).
    """
    results = {}
    camp_discounts = campaign.get("plan_discounts", {}) if campaign else {}
    camp_title = campaign.get("title", "Aksiya") if campaign else ""
    
    promo_type = promo.get("discount_type") if promo else None
    promo_val = float(promo.get("discount_value", 0)) if promo else 0
    promo_code = promo.get("code") if promo else None
    promo_plans = promo.get("applicable_plans", "ALL") if promo else "ALL"
    promo_plan_list = [p.strip() for p in promo_plans.split(",")] if promo_plans != "ALL" else ["1", "3", "6", "12"]
    
    for months, (base_price, title, bonus_days) in PRICING_PLANS.items():
        price = base_price
        tags = []
        
        # 1. Campaign discount (e.g. 10% on 3m)
        m_str = str(months)
        camp_pct = int(camp_discounts.get(m_str, 0))
        camp_discount_uzs = 0
        if camp_pct > 0:
            camp_discount_uzs = int(base_price * (camp_pct / 100.0))
            price = max(1000, price - camp_discount_uzs)
            tags.append(f"-{camp_pct}% aksiya")
            
        # 2. Promocode discount (if applicable to this plan)
        promo_discount_uzs = 0
        promo_applied_this_plan = False
        if promo and m_str in promo_plan_list:
            promo_applied_this_plan = True
            if promo_type == "PERCENT":
                promo_discount_uzs = int(price * (promo_val / 100.0))
                price = max(1000, price - promo_discount_uzs)
                tags.append(f"-{int(promo_val)}% promo")
            elif promo_type == "FIXED":
                promo_discount_uzs = min(price - 1000, int(promo_val))
                price = max(1000, price - promo_discount_uzs)
                tags.append(f"-{int(promo_val):,} so'm promo")
                
        price = int(round(price / 100.0) * 100)
        tag_str = ", ".join(tags)
        total_savings = base_price - price
        
        # Step-by-step formula calculation string
        calc_formula = f"{base_price:,}"
        if camp_pct > 0:
            calc_formula += f" - {camp_discount_uzs:,} ({camp_title or 'Aksiya'}: {camp_pct}%)"
        if promo_applied_this_plan:
            p_desc = f"{int(promo_val)}%" if promo_type == "PERCENT" else f"{int(promo_val):,} so'm"
            calc_formula += f" - {promo_discount_uzs:,} ({promo_code}: {p_desc})"
        calc_formula += f" = {price:,} so'm"
        
        discount_details = {
            "base_price": base_price,
            "final_price": price,
            "total_savings": total_savings,
            "campaign_title": camp_title if camp_pct > 0 else None,
            "campaign_percent": camp_pct if camp_pct > 0 else None,
            "campaign_discount_uzs": camp_discount_uzs if camp_pct > 0 else 0,
            "promocode": promo_code if promo_applied_this_plan else None,
            "promo_type": promo_type if promo_applied_this_plan else None,
            "promo_value": promo_val if promo_applied_this_plan else 0,
            "promo_discount_uzs": promo_discount_uzs if promo_applied_this_plan else 0,
            "calculation": calc_formula
        }
        
        results[months] = {
            "title": title,
            "base_price": base_price,
            "price": price,
            "tag": tag_str,
            "is_discounted": price < base_price,
            "bonus_days": bonus_days,
            "discount_details": discount_details
        }
        
    return results

# ==================== HELPER FUNCTIONS ====================
async def safe_answer(call: CallbackQuery, text: str = None, show_alert: bool = False):
    """Safely answer callback queries ignoring timeout/invalid query errors."""
    with contextlib.suppress(TelegramBadRequest):
        await call.answer(text=text, show_alert=show_alert)

def get_time_greeting(script: str = "lat") -> str:
    """Returns dynamic time-of-day greeting for Tashkent timezone (UTC+5)."""
    tashkent_now = datetime.utcnow() + timedelta(hours=5)
    hour = tashkent_now.hour

    if 5 <= hour < 12:
        options = ["Xayrli tong!", "Tongingiz xayrli bo'lsin!"]
    elif 12 <= hour < 18:
        options = ["Xayrli kun!", "Kuningiz unumli o'tsin!", "Kuningiz xayrli bo'lsin!"]
    elif 18 <= hour < 22:
        options = ["Xayrli oqshom!", "Oqshomingiz xayrli bo'lsin!"]
    else:
        options = ["Xayrli tun!", "Tuningiz osuda o'tsin!"]

    return t(random.choice(options), script)

def check_subscription(expiry_str: Optional[str], script: str = "lat") -> tuple[str, bool]:
    if not expiry_str:
        return t("⚠️ Obuna mavjud emas", script), False
    try:
        expiry = datetime.strptime(expiry_str, '%Y-%m-%d %H:%M:%S')
        now = datetime.utcnow()
        if expiry > now:
            diff = expiry - now
            hours = diff.seconds // 3600
            if diff.days > 0:
                res = f"⭐️ {diff.days} kun {hours} soat qoldi"
            else:
                res = f"⭐️ {hours} soat qoldi"
            return t(res, script), True
        else:
            return t("🔴 Muddati tugagan", script), False
    except Exception:
        return t("⚠️ Noma'lum holat", script), False

async def render_dashboard(message_or_call, user_id: int, state: FSMContext = None):
    if state:
        await state.clear()
        
    user = await db.get_user(user_id)
    if not user:
        full_name = getattr(message_or_call.from_user, 'full_name', 'Foydalanuvchi')
        username = getattr(message_or_call.from_user, 'username', None)
        user, _ = await db.get_or_create_user(user_id, full_name, username)
        
    user_script = await db.get_user_script(user_id)
    is_auth = auth_flow.is_user_authenticated(user_id)
    sub_badge, is_sub_active = check_subscription(user.get('subscription_expiry'), script=user_script)
    
    greeting = get_time_greeting(user_script)
    full_name = user.get('full_name') or "Foydalanuvchi"
    
    if is_auth:
        phone = user.get('phone_number') or 'Telegram'
        auth_status = f"✅ {t('Ulangan', user_script)} (<code>{html.escape(phone)}</code>)"
    else:
        auth_status = f"❌ {t('Ulanmagan', user_script)}"
        
    user_label = t("Foydalanuvchi", user_script)
    sub_label = t("Obuna holati", user_script)
    acc_label = t("Akkaunt holati", user_script)

    text = (
        f"<b>{html.escape(greeting)}</b>\n\n"
        f"👤 <b>{html.escape(user_label)}:</b> {html.escape(full_name)} (ID: <code>{user_id}</code>)\n"
        f"💳 <b>{html.escape(sub_label)}:</b> {sub_badge}\n"
        f"📱 <b>{html.escape(acc_label)}:</b> {auth_status}"
    )
    
    if not is_auth:
        tips_title = t("💡 Boshlash uchun:", user_script)
        step1 = t("1. Quyidagi «📱 Akkauntni ulash» tugmasini bosing.", user_script)
        step2 = t("2. Telefon raqamingiz va Telegram kodini kiriting.", user_script)
        step3 = t("3. Buyurtmalar yoki E'lon tarqatish xizmatidan foydalaning!", user_script)
        text += f"\n\n{tips_title}\n{step1}\n{step2}\n{step3}"
        
    markup = kb.main_dashboard_kb(is_authenticated=is_auth, script=user_script)
    if user_id == ADMIN_ID:
        markup.inline_keyboard.insert(0, [
            InlineKeyboardButton(text=t("👑 SuperAdmin Panelga qaytish", user_script), callback_data="admin_panel")
        ])
    
    if isinstance(message_or_call, Message):
        await message_or_call.answer(text, reply_markup=markup, parse_mode="HTML")
    else:
        with contextlib.suppress(TelegramBadRequest):
            await message_or_call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")

async def render_sender_menu(message_or_call, user_id: int):
    user = await db.get_user(user_id)
    if not user:
        full_name = getattr(message_or_call.from_user, 'full_name', 'Foydalanuvchi')
        username = getattr(message_or_call.from_user, 'username', None)
        user, _ = await db.get_or_create_user(user_id, full_name, username)

    user_script = await db.get_user_script(user_id)
    settings = await db.get_user_settings(user_id)
    is_auth = auth_flow.is_user_authenticated(user_id)
    sub_badge, is_sub_active = check_subscription(user.get('subscription_expiry'), script=user_script)

    is_running = settings.get('is_running', False)
    source_chat_id = settings.get('source_chat_id')
    source_chat_title = settings.get('source_chat_title') or t("O'rnatilmagan", user_script)
    drop_author = settings.get('drop_author', False)

    cycle_min = settings.get('cycle_min', 60)
    cycle_max = settings.get('cycle_max', 90)
    jitter_min = settings.get('jitter_min', 1.5)
    jitter_max = settings.get('jitter_max', 2.0)

    groups = await db.get_user_groups(user_id)
    active_groups = len([g for g in groups if g.get('is_active')])
    total_groups = len(groups)

    forward_mode_text = t("Toza post (Muallifsiz)", user_script) if drop_author else t("Asl nusxa (Forwarded)", user_script)

    est_seconds = active_groups * ((float(jitter_min) + float(jitter_max)) / 2)
    est_minutes = est_seconds / 60

    if not is_sub_active:
        status_icon = t("🔴 Obuna muddati tugagan", user_script)
    elif is_running:
        status_icon = t("🟢 FAOL (Ishlayapti)", user_script)
    else:
        status_icon = t("🔴 TO'XTATILGAN (Pauza)", user_script)

    source_display = f"📢 <b>{html.escape(source_chat_title)}</b>" if source_chat_id else f"⚠️ <b>{t('O\'rnatilmagan', user_script)}</b>"

    header_title = t("📢 E'lon tarqatish sozlamalari", user_script)
    status_lbl = t("Holat:", user_script)
    source_lbl = t("Manba guruh:", user_script)
    forward_lbl = t("Forward rejimi:", user_script)
    groups_lbl = t("Guruhlar:", user_script)
    cycle_lbl = t("Doira oralig'i:", user_script)
    jitter_lbl = t("Yuborish tezligi:", user_script)
    ta_faol = t("ta Faol", user_script)
    ta_jami = t("ta Jami", user_script)
    daqiqada = t("daqiqada", user_script)
    ta_guruh = t("ta guruh", user_script)

    text = (
        f"<b>{header_title}</b>\n\n"
        f"<b>{status_lbl}</b> {status_icon}\n"
        f"📥 <b>{source_lbl}</b> {source_display}\n"
        f"🔄 <b>{forward_lbl}</b> {forward_mode_text}\n"
        f"👥 <b>{groups_lbl}</b> {active_groups} {ta_faol} / {total_groups} {ta_jami}\n"
        f"⏱ <b>{cycle_lbl}</b> {cycle_min}s - {cycle_max}s\n"
        f"⚡️ <b>{jitter_lbl}</b> {jitter_min}s - {jitter_max}s (~{est_minutes:.1f} {daqiqada} {active_groups} {ta_guruh})\n"
    )

    markup = kb.sender_menu_kb(
        is_authenticated=is_auth,
        is_running=is_running,
        drop_author=drop_author,
        script=user_script
    )

    if isinstance(message_or_call, Message):
        await message_or_call.answer(text, reply_markup=markup, parse_mode="HTML")
    else:
        with contextlib.suppress(TelegramBadRequest):
            await message_or_call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")

async def render_admin_dashboard(message_or_call, state: FSMContext = None):
    if state:
        await state.clear()
        
    user_id = message_or_call.from_user.id
    full_name = getattr(message_or_call.from_user, 'full_name', 'SuperAdmin')

    all_users = await db.get_all_users()
    total_users = len(all_users)
    now = datetime.utcnow()
    active_vips = 0
    for u in all_users:
        exp = u.get("subscription_expiry")
        if exp:
            try:
                if datetime.strptime(exp, '%Y-%m-%d %H:%M:%S') > now:
                    active_vips += 1
            except Exception:
                pass

    earnings = await db.get_earnings_stats()
    total_rev = earnings.get("total_revenue", 0)
    pending_cheques = await db.get_pending_payment_requests()
    pending_count = len(pending_cheques)

    h_stats = await db.get_harvester_stats()
    total_groups = h_stats.get("total_groups", 0)
    active_groups = h_stats.get("active_groups", 0)
    today_orders = h_stats.get("today_orders", 0)

    from src.harvester.service import default_harvester_service
    hb_status = default_harvester_service.get_status()
    is_online = hb_status["is_connected"]
    u_info = hb_status.get("user_info", {})
    
    if is_online:
        userbot_badge = f"🟢 **FAOL** (`{u_info.get('username') or u_info.get('phone') or 'Ulangan'}`)"
    else:
        userbot_badge = "🔴 **ULANMAGAN** (Faol emas)"

    text = (
        "👑 **SuperAdmin Boshqaruv Paneli**\n"
        f"Assalomu alaykum, **{full_name}**!\n\n"
        "📊 **Tizim Umumiy Ko'rsatkichlari:**\n"
        f"• 👥 Foydalanuvchilar: **{total_users} ta** ({active_vips} ta faol VIP)\n"
        f"• 💰 Jami tushum: **{total_rev:,} so'm**\n"
        f"• ⏳ Kutilayotgan cheklar: **{pending_count} ta**\n\n"
        "📡 **Harvester Radar Tizimi:**\n"
        f"• Userbot holati: {userbot_badge}\n"
        f"• Monitoring guruhlari: **{active_groups} ta faol** / {total_groups} ta jami\n"
        f"• Bugungi toza buyurtmalar: **{today_orders} ta**\n\n"
        "Kerakli bo'limni tanlang:"
    )

    markup = kb.admin_main_dashboard_kb(userbot_online=is_online, pending_cheques=pending_count)

    if isinstance(message_or_call, Message):
        await message_or_call.answer(text, reply_markup=markup, parse_mode="Markdown")
    else:
        with contextlib.suppress(TelegramBadRequest):
            await message_or_call.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")

# ==================== START & MENU HANDLERS ====================
@router.message(CommandStart())
@router.message(Command("menu"))
@router.message(Command("admin"))
async def start_cmd(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id == ADMIN_ID and message.text and "/admin" in message.text:
        await render_admin_dashboard(message, state)
        return

    user, is_new = await db.get_or_create_user(
        user_id=user_id,
        full_name=message.from_user.full_name or "Foydalanuvchi",
        username=message.from_user.username
    )
    
    user_script = await db.get_user_script(user_id)
    is_auth = auth_flow.is_user_authenticated(user_id)
    reply_markup = kb.main_reply_kb(user_script) if is_auth else kb.unauth_reply_kb(user_script)

    if is_new:
        welcome_text = (
            f"👋 <b>{t('Assalomu alaykum', user_script)}, {html.escape(message.from_user.full_name)}!</b>\n\n"
            f"🎉 {t('Sizga 3 kunlik BEPUL VIP sinov muddati taqdim etildi!', user_script)}\n"
            f"{t('Endi buyurtmalarni kuzatishingiz va guruhlarga avtomatik e\'lon tarqatishingiz mumkin.', user_script)}"
        )
        await message.answer(welcome_text, reply_markup=reply_markup, parse_mode="HTML")
    else:
        await message.answer(f"🚕 <b>{t('Taksi Xabarchi', user_script)}</b>", reply_markup=reply_markup, parse_mode="HTML")
        
    await render_dashboard(message, user_id, state)

@router.callback_query(F.data == "admin_panel")
async def admin_panel_call(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        await safe_answer(call, "Ruxsat yo'q!", show_alert=True)
        return
    await render_admin_dashboard(call, state)
    await safe_answer(call)

@router.callback_query(F.data == "admin_driver_view")
async def admin_driver_view_call(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    await render_dashboard(call, call.from_user.id, state)
    await safe_answer(call)

@router.callback_query(F.data == "back_dashboard")
async def back_dashboard_call(call: CallbackQuery, state: FSMContext):
    if call.from_user.id == ADMIN_ID:
        await render_admin_dashboard(call, state)
    else:
        await render_dashboard(call, call.from_user.id, state)
    await safe_answer(call)

@router.callback_query(F.data == "sender_menu")
async def sender_menu_call(call: CallbackQuery):
    await render_sender_menu(call, call.from_user.id)
    await safe_answer(call)

@router.callback_query(F.data == "toggle_script")
async def toggle_script_call(call: CallbackQuery):
    user_id = call.from_user.id
    current_script = await db.get_user_script(user_id)
    new_script = "cyr" if current_script == "lat" else "lat"
    await db.set_user_script(user_id, new_script)
    
    is_auth = auth_flow.is_user_authenticated(user_id)
    reply_markup = kb.main_reply_kb(new_script) if is_auth else kb.unauth_reply_kb(new_script)
    
    alert_txt = "Алифбо: Кирилл танланди 🇺🇿" if new_script == "cyr" else "Alifbo: Lotin tanlandi 🇺🇿"
    await safe_answer(call, alert_txt)
    await render_dashboard(call, user_id)
    with contextlib.suppress(Exception):
        await call.bot.send_message(
            chat_id=user_id,
            text=f"🌐 {alert_txt}",
            reply_markup=reply_markup
        )

@router.callback_query(F.data == "help_info")
async def help_info_call(call: CallbackQuery):
    user_id = call.from_user.id
    user_script = await db.get_user_script(user_id)
    text = (
        f"📖 <b>{t('Taksi Xabarchi Bot Qo\'llanmasi', user_script)}</b>\n\n"
        f"🎯 <b>1. {t('Buyurtmalar radari:', user_script)}</b>\n"
        f"{t('Haydovchilar uchun guruhlardagi toza yo\'lovchi va pochta xabarlarini avtomatik ajratib, tezkor bildirishnoma yuboradi. «Buyurtmalar» bo\'limida yo\'nalish va tumanlarni sozlashingiz mumkin.', user_script)}\n\n"
        f"📢 <b>2. {t('E\'lon tarqatish:', user_script)}</b>\n"
        f"{t('Shaxsiy akkauntingizni ulab, 50+ guruhlarga xabarlaringizni avtomatik va muntazam interval bilan tarqatasiz.', user_script)}\n\n"
        f"💳 <b>3. {t('Obuna tizimi:', user_script)}</b>\n"
        f"{t('Xizmatlardan to\'liq foydalanish uchun obunani o\'z vaqtida faollashtiring yoki uzaytiring.', user_script)}"
    )
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(text, reply_markup=kb.back_kb(user_script), parse_mode="HTML")
    await safe_answer(call)

@router.message(F.text.in_({"📖 Foydalanish qo'llanmasi", "📖 Фойдаланиш қўлланмаси"}))
async def guide_reply_handler(message: Message):
    user_id = message.from_user.id
    user_script = await db.get_user_script(user_id)
    guide_text = (
        f"📖 <b>{t('Taksi Xabarchi Bot Qo\'llanmasi', user_script)}</b>\n\n"
        f"🎯 <b>1. {t('Buyurtmalar radari:', user_script)}</b>\n"
        f"{t('Haydovchilar uchun guruhlardagi toza yo\'lovchi va pochta xabarlarini avtomatik ajratib, tezkor bildirishnoma yuboradi. «Buyurtmalar» bo\'limida yo\'nalish va tumanlarni sozlashingiz mumkin.', user_script)}\n\n"
        f"📢 <b>2. {t('E\'lon tarqatish:', user_script)}</b>\n"
        f"{t('Shaxsiy akkauntingizni ulab, 50+ guruhlarga xabarlaringizni avtomatik va muntazam interval bilan tarqatasiz.', user_script)}\n\n"
        f"💳 <b>3. {t('Obuna tizimi:', user_script)}</b>\n"
        f"{t('Xizmatlardan to\'liq foydalanish uchun obunani o\'z vaqtida faollashtiring yoki uzaytiring.', user_script)}"
    )
    await message.answer(guide_text, parse_mode="HTML")

@router.message(F.text.in_({"✍️ Adminga yozish", "✍️ Админга ёзиш"}))
async def admin_support_reply_handler(message: Message):
    user_id = message.from_user.id
    user_script = await db.get_user_script(user_id)
    support_text = (
        f"✍️ <b>{t('Qo\'llab-quvvatlash xizmati', user_script)}</b>\n\n"
        f"{t('Savol, taklif yoki to\'lovlar bo\'yicha murojaat qilish uchun adminga yozishingiz mumkin:', user_script)}\n\n"
        f"👤 <b>{t('Admin:', user_script)}</b> @sulaymonshoh\n"
        f"💬 <b>{t('Aloqa:', user_script)}</b> <a href=\"tg://user?id={ADMIN_ID}\">{t('Admin bilan bog\'lanish', user_script)}</a>"
    )
    await message.answer(support_text, parse_mode="HTML")

@router.message(F.text.in_({"❌ Bekor qilish", "❌ Бекор қилиш"}))
async def cancel_reply_handler(message: Message, state: FSMContext):
    user_id = message.from_user.id
    user_script = await db.get_user_script(user_id)
    await auth_flow.cancel_auth_session(user_id)
    await state.clear()
    is_auth = auth_flow.is_user_authenticated(user_id)
    reply_markup = kb.main_reply_kb(user_script) if is_auth else kb.unauth_reply_kb(user_script)
    await message.answer(t("Amal bekor qilindi.", user_script), reply_markup=reply_markup)
    await render_dashboard(message, user_id, state)

# ==================== IN-CHAT AUTHENTICATION FLOW ====================
@router.callback_query(F.data == "start_auth")
async def start_auth_call(call: CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    user_script = await db.get_user_script(user_id)
    if auth_flow.is_user_authenticated(user_id):
        await safe_answer(call, t("Sizning akkauntingiz allaqachon ulangan!", user_script), show_alert=True)
        await render_dashboard(call, user_id, state)
        return
        
    text = (
        f"📱 <b>{t('Telegram Akkauntni Ulash', user_script)}</b>\n\n"
        f"{t('Guruhlarga e\'lon tarqatish uchun Telegram akkauntingizni ulash lozim.', user_script)}\n\n"
        f"👇 {t('Pastdagi «📱 Telefon raqamni yuborish» tugmasini bosing yoki telefon raqamingizni xalqaro formatda yozib yuboring (Masalan: +998901234567):', user_script)}"
    )
    await state.set_state(AuthStates.waiting_for_phone)
    await call.message.answer(text, reply_markup=kb.phone_request_kb(user_script), parse_mode="HTML")
    await safe_answer(call)

@router.message(AuthStates.waiting_for_phone, F.contact)
@router.message(AuthStates.waiting_for_phone, F.text)
async def process_phone_input(message: Message, state: FSMContext):
    user_id = message.from_user.id
    user_script = await db.get_user_script(user_id)
    
    if message.text in ("❌ Bekor qilish", "❌ Бекор қилиш"):
        await state.clear()
        reply_markup = kb.unauth_reply_kb(user_script)
        await message.answer(t("Ulanish bekor qilindi.", user_script), reply_markup=reply_markup)
        await render_dashboard(message, user_id, state)
        return
        
    phone = message.contact.phone_number if message.contact else message.text.strip()
    clean_phone = re.sub(r'[^\d+]', '', phone)
    if not clean_phone.startswith('+'):
        clean_phone = f"+{clean_phone}"
        
    if len(clean_phone) < 9:
        await message.answer(t("⚠️ Telefon raqami noto'g'ri kiritildi. Iltimos, qaytadan yuboring (Masalan: `+998901234567`).", user_script), parse_mode="Markdown")
        return
        
    status_msg = await message.answer(t("⏳ Telegram serveriga ulanmoqda va tasdiqlash kodi so'ralmoqda...", user_script))
    
    res = await auth_flow.start_phone_login(user_id, clean_phone)
    with contextlib.suppress(Exception):
        await status_msg.delete()

    if not res.get("success"):
        await message.answer(
            f"❌ **Xatolik yuz berdi:**\n{res.get('error')}\n\nIltimos, raqamni tekshirib qaytadan urinib ko'ring:",
            reply_markup=kb.cancel_auth_kb(),
            parse_mode="Markdown"
        )
        return
        
    await state.set_state(AuthStates.waiting_for_code)
    code_prompt = (
        f"📩 <b>{t('Tasdiqlash kodi yuborildi!', user_script)}</b>\n\n"
        f"{t('Telefon raqamingiz', user_script)} (<code>{clean_phone}</code>) {t('ga Telegram ilovasi orqali 5 xonali tasdiqlash kodi yuborildi.', user_script)}\n\n"
        f"👉 <b>{t('Kodni probellar bilan ajratib yozib yuboring:', user_script)}</b>\n"
        f"{t('Masalan:', user_script)} <code>1 2 3 4 5</code>"
    )
    await message.answer(code_prompt, reply_markup=kb.cancel_auth_kb(), parse_mode="HTML")

@router.message(AuthStates.waiting_for_code, F.text)
async def process_code_input(message: Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id
    raw_code = message.text.strip()
    
    status_msg = await message.answer("⏳ Kod tekshirilmoqda...")
    res = await auth_flow.submit_auth_code(user_id, raw_code)
    
    if not res.get("success"):
        await status_msg.edit_text(
            f"❌ **Xatolik:** {res.get('error')}\n\nIltimos, kodni probellar bilan qayta kiriting (Masalan: `1 2 3 4 5`):",
            reply_markup=kb.cancel_auth_kb(),
            parse_mode="Markdown"
        )
        return
        
    if res.get("needs_2fa"):
        await state.set_state(AuthStates.waiting_for_2fa)
        await status_msg.edit_text(
            "🔐 **2-bosqichli xavfsizlik paroli (2FA) talab qilinadi!**\n\n"
            "Akkauntingizda ikki bosqichli autentifikatsiya paroli yoqilgan.\n"
            "Iltimos, parolingizni yozib yuboring:",
            reply_markup=kb.cancel_auth_kb(),
            parse_mode="Markdown"
        )
        return
        
    # Successful login without 2FA
    await state.clear()
    
    # Notify worker manager to start worker if enabled in settings
    settings = await db.get_user_settings(user_id)
    if settings.get("is_running", False):
        worker_mgr = getattr(bot, 'worker_manager', None)
        if worker_mgr:
            await worker_mgr.start_user_worker(user_id)
        
    user_script = await db.get_user_script(user_id)
    await status_msg.edit_text(f"🎉 <b>{t('Tabriklaymiz! Telegram akkauntingiz muvaffaqiyatli ulandi!', user_script)}</b>", parse_mode="HTML")
    with contextlib.suppress(Exception):
        await message.answer(f"✅ {t('Akkaunt ulandi.', user_script)}", reply_markup=kb.main_reply_kb(user_script))
    await render_dashboard(message, user_id, state)

@router.message(AuthStates.waiting_for_2fa, F.text)
async def process_2fa_input(message: Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id
    password = message.text.strip()
    
    status_msg = await message.answer("⏳ 2FA parol tekshirilmoqda...")
    res = await auth_flow.submit_2fa_password(user_id, password)
    
    if not res.get("success"):
        await status_msg.edit_text(
            f"❌ **Xatolik:** {res.get('error')}\n\nIltimos, parolni qaytadan kiriting:",
            reply_markup=kb.cancel_auth_kb(),
            parse_mode="Markdown"
        )
        return
        
    await state.clear()
    settings = await db.get_user_settings(user_id)
    if settings.get("is_running", False):
        worker_mgr = getattr(bot, 'worker_manager', None)
        if worker_mgr:
            await worker_mgr.start_user_worker(user_id)
        
    user_script = await db.get_user_script(user_id)
    await status_msg.edit_text(f"🎉 <b>{t('Tabriklaymiz! Akkauntingiz muvaffaqiyatli ulandi!', user_script)}</b>", parse_mode="HTML")
    with contextlib.suppress(Exception):
        await message.answer(f"✅ {t('Akkaunt ulandi.', user_script)}", reply_markup=kb.main_reply_kb(user_script))
    await render_dashboard(message, user_id, state)

@router.callback_query(F.data == "cancel_auth")
async def cancel_auth_call(call: CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    user_script = await db.get_user_script(user_id)
    await auth_flow.cancel_auth_session(user_id)
    await state.clear()
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(t("Akkaunt ulash bekor qilindi.", user_script))
    await render_dashboard(call, user_id, state)
    await safe_answer(call)

# ==================== LOGOUT FLOW ====================
@router.callback_query(F.data == "logout_confirm")
async def logout_confirm_call(call: CallbackQuery):
    user_id = call.from_user.id
    user_script = await db.get_user_script(user_id)
    text = (
        f"⚠️ <b>{t('Haqiqatdan ham akkauntni uzmoqchimisiz?', user_script)}</b>\n\n"
        f"{t('Akkaunt uzilgach, barcha avtomatik e\'lon tarqatish to\'xtatiladi va tizimdagi sessiyangiz o\'chiriladi.', user_script)}"
    )
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(text, reply_markup=kb.logout_confirm_kb(), parse_mode="HTML")
    await safe_answer(call)

@router.callback_query(F.data == "logout_confirmed")
async def logout_confirmed_call(call: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id
    
    worker_mgr = getattr(bot, 'worker_manager', None)
    if worker_mgr:
        await worker_mgr.stop_user_worker(user_id)
        
    session_file = f"{auth_flow.get_user_session_path(user_id)}.session"
    if os.path.exists(session_file):
        with contextlib.suppress(Exception):
            os.remove(session_file)
            
    await db.set_user_setting(user_id, "is_running", 0)
    await db.update_user_phone(user_id, "")
    
    user_script = await db.get_user_script(user_id)
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(f"🔌 <b>{t('Akkauntingiz tizimdan muvaffaqiyatli uzildi.', user_script)}</b>", parse_mode="HTML")
    with contextlib.suppress(Exception):
        await call.bot.send_message(
            chat_id=user_id,
            text=f"🔌 {t('Akkaunt uzildi.', user_script)}",
            reply_markup=kb.unauth_reply_kb(user_script)
        )
        
    await render_dashboard(call, user_id, state)
    await safe_answer(call)

# ==================== PRICING & PAYMENT APPROVAL ====================
@router.callback_query(F.data == "show_plans")
async def show_plans_call(call: CallbackQuery, state: Optional[FSMContext] = None):
    user_id = call.from_user.id
    campaign = await db.get_active_campaign_discount()
    applied_promo = None
    if state:
        state_data = await state.get_data()
        applied_promo = state_data.get("applied_promo")
        
    plan_prices = calculate_effective_plan_prices(campaign, applied_promo)
    
    banner = ""
    if campaign:
        rem_d = campaign.get("remaining_days", 0)
        rem_h = campaign.get("remaining_hours", 0)
        time_text = f"{rem_d} kun, {rem_h} soat" if rem_d > 0 else f"{rem_h} soat"
        title_esc = html.escape(str(campaign.get('title', 'Aksiya')))
        banner += f"🔥 <b>MAXSUS AKSIYA: {title_esc}</b>\n⏳ Tugashiga: <b>{time_text} qoldi!</b>\n\n"
        
    if applied_promo:
        code_esc = html.escape(str(applied_promo.get('code', '')))
        banner += f"🎟 <b>Faol Promokod:</b> <code>{code_esc}</code> qo'llandi!\n\n"
        
    text = (
        "💎 <b>Obuna Tariflari va To'lov</b>\n\n"
        f"{banner}"
        "📦 <b>Mavjud tariflar:</b>\n"
    )
    for m in [1, 3, 6, 12]:
        p = plan_prices[m]
        p_title = html.escape(str(p['title']))
        base_formatted = f"<s>({p['base_price']:,} so'm)</s> " if p['is_discounted'] else ""
        tag_formatted = f" <i>({html.escape(str(p['tag']))})</i>" if p['tag'] else ""
        text += f"• <b>{p_title}:</b> {p['price']:,} so'm {base_formatted}{tag_formatted}\n"
        
    card_number_esc = html.escape(str(PAYMENT_CARD_NUMBER))
    card_holder_esc = html.escape(str(PAYMENT_CARD_HOLDER))
    text += (
        "\n💳 <b>To'lov uchun karta:</b>\n"
        f"💳 <code>{card_number_esc}</code>\n"
        f"👤 {card_holder_esc}\n\n"
        "👇 O'zingizga ma'qul tarifni tanlang yoki promokod kiriting:"
    )
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(text, reply_markup=kb.pricing_plans_kb(plan_prices), parse_mode="HTML")
    await safe_answer(call)

@router.callback_query(F.data.startswith("buy_plan_"))
async def select_plan_call(call: CallbackQuery, state: FSMContext):
    months = int(call.data.split("_")[2])
    campaign = await db.get_active_campaign_discount()
    state_data = await state.get_data()
    applied_promo = state_data.get("applied_promo")
    
    plan_prices = calculate_effective_plan_prices(campaign, applied_promo)
    plan_info = plan_prices.get(months, {"price": 25000, "base_price": 25000, "title": f"{months} Oy", "tag": "", "discount_details": {}})
    amount_uzs = plan_info["price"]
    base_amount_uzs = plan_info["base_price"]
    discount_details = plan_info.get("discount_details", {})
    title = plan_info["title"]
    
    await state.set_state(PaymentStates.waiting_for_cheque)
    await state.update_data(
        plan_months=months,
        amount_uzs=amount_uzs,
        base_amount_uzs=base_amount_uzs,
        discount_details=discount_details,
        promocode=discount_details.get("promocode")
    )
    
    discount_note = ""
    if discount_details.get("campaign_percent") or discount_details.get("promocode"):
        discount_note = f"\n🏷 **Chegirmalar:** {plan_info['tag']}\n💡 **Hisob-kitob:** `{discount_details.get('calculation')}`"
        
    text = (
        f"🧾 **Tarif tanlandi: {title}**{discount_note}\n\n"
        f"💰 **To'lov summasi:** `{amount_uzs:,}` so'm\n\n"
        f"💳 **To'lov kartasi:**\n"
        f"💳 `{PAYMENT_CARD_NUMBER}`\n"
        f"👤 **Egasi:** {PAYMENT_CARD_HOLDER}\n\n"
        "👉 Iltimos, ko'rsatilgan summani kartaga o'tkazib, **to'lov chekining rasmini (skrinshot)** ushbu botga yuboring!"
    )
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(text, reply_markup=kb.cancel_payment_kb(), parse_mode="Markdown")
    await safe_answer(call)

@router.message(PaymentStates.waiting_for_cheque, F.photo)
async def process_cheque_photo(message: Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id
    data = await state.get_data()
    plan_months = data.get("plan_months", 1)
    amount_uzs = data.get("amount_uzs", 25000)
    base_amount_uzs = data.get("base_amount_uzs", amount_uzs)
    discount_details = data.get("discount_details") or {}
    promocode = data.get("promocode")
    applied_promo = data.get("applied_promo")
    
    # Get highest resolution photo
    photo_file_id = message.photo[-1].file_id
    
    # Store payment request in DB with discount details and promocode!
    request_id = await db.create_payment_request(
        user_id=user_id,
        plan_months=plan_months,
        amount_uzs=amount_uzs,
        receipt_file_id=photo_file_id,
        base_amount_uzs=base_amount_uzs,
        discount_details=discount_details,
        promocode=promocode
    )
    
    # Record promo usage if a discount promo was used
    if applied_promo and applied_promo.get("id"):
        await db.record_promocode_usage(applied_promo["id"], user_id, plan_months)
    
    await state.clear()
    
    confirm_text = (
        "✅ **To'lov chekingiz qabul qilindi!**\n\n"
        "Chek adminga yuborildi. Administrator tekshirib tasdiqlashi bilan obunangiz darhol faollashtiriladi va sizga xabar yuboriladi."
    )
    await message.answer(confirm_text, reply_markup=kb.back_kb(), parse_mode="Markdown")
    
    # Forward to SuperAdmin Channel / DM with 1-Tap Approval Buttons
    user = await db.get_user(user_id)
    full_name = user.get('full_name', message.from_user.full_name)
    username = user.get('username') or 'Mavjud emas'
    
    has_discounts = discount_details.get("campaign_percent") or discount_details.get("promocode")
    discount_block = ""
    if has_discounts:
        discount_block = "\n🏷 **Chegirma va Hisob-kitob:**\n"
        discount_block += f"• **Asl narx:** {base_amount_uzs:,} so'm\n"
        if discount_details.get("campaign_percent"):
            discount_block += f"• **Aksiya:** {discount_details['campaign_title']} (-{discount_details['campaign_percent']}% ➡️ -{discount_details['campaign_discount_uzs']:,} so'm)\n"
        if discount_details.get("promocode"):
            p_val_str = f"-{int(discount_details['promo_value'])}%" if discount_details.get('promo_type') == 'PERCENT' else f"-{int(discount_details['promo_value']):,} so'm"
            discount_block += f"• **Promokod:** `{discount_details['promocode']}` ({p_val_str} ➡️ -{discount_details['promo_discount_uzs']:,} so'm)\n"
        if discount_details.get("calculation"):
            discount_block += f"• **Formula:** `{discount_details['calculation']}`\n"
        if discount_details.get("total_savings"):
            discount_block += f"💡 **Jami tejaldi:** `{discount_details['total_savings']:,} so'm`\n"

    admin_caption = (
        f"🧾 **Yangi To'lov Cheki (ID: #{request_id})**\n\n"
        f"👤 **Mijoz:** {full_name}\n"
        f"🆔 **User ID:** `{user_id}`\n"
        f"🔗 **Username:** @{username}\n"
        f"📦 **Tanlangan tarif:** {plan_months} Oy\n"
        f"💰 **To'lov summasi:** {amount_uzs:,} so'm\n"
        f"{discount_block}\n"
        f"🕒 **Vaqt:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
    )
    
    approval_markup = kb.admin_payment_approval_kb(request_id, user_id, plan_months)
    try:
        await bot.send_photo(
            chat_id=ADMIN_CHANNEL_ID,
            photo=photo_file_id,
            caption=admin_caption,
            reply_markup=approval_markup,
            parse_mode="Markdown"
        )
        logger.info(f"Payment request #{request_id} sent to admin channel {ADMIN_CHANNEL_ID}")
    except Exception as e:
        logger.error(f"Failed to forward payment request to admin channel: {e}")

# ==================== 1-TAP ADMIN APPROVAL CALLBACKS ====================
@router.callback_query(F.data.startswith("pay_app_"))
async def admin_approve_payment_call(call: CallbackQuery, bot: Bot):
    parts = call.data.split("_")
    request_id = int(parts[2])
    user_id = int(parts[3])
    plan_months = int(parts[4])
    
    plan_info = PRICING_PLANS.get(plan_months, (25000, "1 Oy", 30))
    days_to_add = plan_info[2]
    
    # Update payment status
    await db.update_payment_request_status(request_id, "APPROVED")
    
    # Extend subscription
    new_expiry = await db.update_user_subscription(user_id, days_to_add)
    
    # Update admin message
    admin_name = call.from_user.username or call.from_user.full_name
    new_caption = (
        f"{call.message.caption}\n\n"
        f"✅ **TASDIQLANDI** (Admin: @{admin_name})\n"
        f"📅 Yangi muddat: `{new_expiry}`"
    )
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_caption(caption=new_caption, reply_markup=None, parse_mode="Markdown")
        
    # Send celebration DM to User!
    user_msg = (
        "🎉 **Tabriklaymiz! To'lovingiz muvaffaqiyatli tasdiqlandi!**\n\n"
        f"📦 **Faollashtirilgan tarif:** {plan_info[1]}\n"
        f"📅 **Yangi amal qilish muddati:** `{new_expiry}` gacha.\n\n"
        "E'lon tarqatish xizmatidan unumli foydalanishingizni tilaymiz!"
    )
    try:
        await bot.send_message(chat_id=user_id, text=user_msg, reply_markup=kb.back_kb(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Failed to send confirmation DM to user {user_id}: {e}")
        
    await safe_answer(call, "To'lov tasdiqlandi va obuna uzaytirildi!", show_alert=True)

@router.callback_query(F.data.startswith("pay_rej_"))
async def admin_reject_payment_call(call: CallbackQuery, bot: Bot):
    parts = call.data.split("_")
    request_id = int(parts[2])
    user_id = int(parts[3])
    
    await db.update_payment_request_status(request_id, "REJECTED")
    
    admin_name = call.from_user.username or call.from_user.full_name
    new_caption = (
        f"{call.message.caption}\n\n"
        f"❌ **RAD ETILDI** (Admin: @{admin_name})"
    )
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_caption(caption=new_caption, reply_markup=None, parse_mode="Markdown")
        
    user_msg = (
        "❌ **Afsuski, yuborilgan to'lov cheki tasdiqlanmadi.**\n\n"
        "Iltimos, to'lov to'g'ri o'tkazilganini tekshirib, qaytadan chek yuboring yoki administrator bilan bog'laning."
    )
    try:
        await bot.send_message(chat_id=user_id, text=user_msg, reply_markup=kb.back_kb(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Failed to send rejection DM to user {user_id}: {e}")
        
    await safe_answer(call, "To'lov rad etildi.", show_alert=True)

# ==================== STATE TOGGLE & FORWARD MODE ====================
@router.callback_query(F.data == "toggle_state")
async def toggle_state_call(call: CallbackQuery, bot: Bot):
    user_id = call.from_user.id
    user = await db.get_user(user_id)
    user_script = await db.get_user_script(user_id)
    _, is_sub_active = check_subscription(user.get('subscription_expiry') if user else None, script=user_script)
    
    if not is_sub_active:
        await safe_answer(call, t("Obuna muddatingiz tugagan! Iltimos, obunani uzaytiring.", user_script), show_alert=True)
        return
        
    if not auth_flow.is_user_authenticated(user_id):
        await safe_answer(call, t("Avval Telegram akkauntingizni ulang!", user_script), show_alert=True)
        return
        
    settings = await db.get_user_settings(user_id)
    is_running = settings.get('is_running', False)
    source_chat_id = settings.get('source_chat_id')
    
    if not is_running and not source_chat_id:
        await safe_answer(call, t("Avval 'Manba guruhni sozlash' orqali xabar olinadigan guruhni ulang!", user_script), show_alert=True)
        return
        
    new_state = 0 if is_running else 1
    await db.set_user_setting(user_id, "is_running", new_state)
    
    worker_mgr = getattr(bot, 'worker_manager', None)
    if worker_mgr:
        if new_state:
            await worker_mgr.start_user_worker(user_id)
        else:
            await worker_mgr.stop_user_worker(user_id)
            
    await render_sender_menu(call, user_id)
    await safe_answer(call, t("Holat o'zgartirildi!", user_script))

@router.callback_query(F.data == "toggle_drop_author")
async def toggle_drop_author_call(call: CallbackQuery):
    user_id = call.from_user.id
    user_script = await db.get_user_script(user_id)
    settings = await db.get_user_settings(user_id)
    drop_author = settings.get('drop_author', False)
    await db.set_user_setting(user_id, "drop_author", 0 if drop_author else 1)
    await render_sender_menu(call, user_id)
    await safe_answer(call, t("Forward rejimi o'zgartirildi!", user_script))

# ==================== SOURCE CHAT SETUP ====================
@router.message(Command("source"))
async def source_cmd(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id
    source_chat_id = None
    source_chat_title = None
    
    parts = message.text.strip().split(maxsplit=1)
    
    if message.reply_to_message and message.reply_to_message.forward_from_chat:
        source_chat_id = message.reply_to_message.forward_from_chat.id
        source_chat_title = message.reply_to_message.forward_from_chat.title or f"Chat {source_chat_id}"
    elif len(parts) > 1:
        target_input = parts[1].strip()
        worker_mgr = getattr(bot, 'worker_manager', None)
        async with auth_flow.user_client_scope(user_id, worker_mgr) as client:
            if client:
                try:
                    if target_input.startswith("-100"):
                        target_input = int(target_input)
                    entity = await client.get_entity(target_input)
                    source_chat_id = entity.id
                    source_chat_title = getattr(entity, 'title', f"Chat {entity.id}")
                    if not str(source_chat_id).startswith("-100"):
                        from telethon.tl.types import Channel
                        if isinstance(entity, Channel):
                            source_chat_id = int(f"-100{entity.id}")
                except Exception as e:
                    logger.error(f"Error resolving source chat via command: {e}")
                    await message.answer(f"⚠️ Manba guruhni aniqlab bo'lmadi: {e}", parse_mode="Markdown")
                    return
            else:
                await message.answer("⚠️ Avval Telegram akkauntingizni ulang.", reply_markup=kb.back_kb())
                return
    else:
        await message.answer(
            "ℹ️ **Manba guruhni o'rnatish:**\n\n"
            "Manba guruhdagi birorta xabarni ushbu botga **Forward (Uzatish)** qiling yoki unga `/source` deb javob qaytaring.",
            parse_mode="Markdown"
        )
        return
        
    if source_chat_id:
        await db.set_user_setting(user_id, "source_chat_id", source_chat_id)
        await db.set_user_setting(user_id, "source_chat_title", source_chat_title)
        await message.answer(
            f"✅ **Manba guruh muvaffaqiyatli o'rnatildi!**\n\n"
            f"📢 **Nomi:** {source_chat_title}\n"
            f"🆔 **ID:** `{source_chat_id}`\n\n"
            f"Bot har bir aylanmada ushbu guruhdagi eng oxirgi xabarni olib tarqatadi.",
            parse_mode="Markdown"
        )
        await render_dashboard(message, user_id, state)

@router.callback_query(F.data == "set_source_chat")
async def set_source_chat_call(call: CallbackQuery, state: FSMContext):
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(
            "📥 **Manba guruhni sozlash**\n\n"
            "Xabarlar qaysi guruh yoki kanaldan olinib tarqatilishi kerak?\n\n"
            "👉 O'sha guruh/kanaldagi **biron bir xabarni to'g'ridan-to'g'ri ushbu botga Forward (Uzatish)** qilib yuboring,\n"
            "yoki buyruq orqali yuboring: `/source @guruh_nomi`\n\n"
            "*(Bot har doim o'sha guruhdagi eng oxirgi yuborilgan yangi xabarni oladi)*",
            reply_markup=kb.back_kb(),
            parse_mode="Markdown"
        )
    await state.set_state(BotStates.waiting_for_source_chat)
    await safe_answer(call)

@router.message(BotStates.waiting_for_source_chat)
async def process_source_chat_input(message: Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id
    source_chat_id = None
    source_chat_title = None
    
    if message.forward_from_chat:
        source_chat_id = message.forward_from_chat.id
        source_chat_title = message.forward_from_chat.title or f"Chat {source_chat_id}"
    elif message.text and (message.text.startswith("@") or "t.me/" in message.text or message.text.startswith("-100")):
        worker_mgr = getattr(bot, 'worker_manager', None)
        async with auth_flow.user_client_scope(user_id, worker_mgr) as client:
            if client:
                try:
                    entity_input = message.text.strip()
                    if entity_input.startswith("-100"):
                        entity_input = int(entity_input)
                    entity = await client.get_entity(entity_input)
                    source_chat_id = entity.id
                    source_chat_title = getattr(entity, 'title', f"Chat {entity.id}")
                    if not str(source_chat_id).startswith("-100"):
                        from telethon.tl.types import Channel
                        if isinstance(entity, Channel):
                            source_chat_id = int(f"-100{entity.id}")
                except Exception as e:
                    logger.error(f"Error resolving source chat: {e}")
                    await message.answer("⚠️ Guruhni havola orqali topib bo'lmadi. Iltimos, xabarni Forward qilib yuboring!", reply_markup=kb.back_kb())
                    return
            else:
                await message.answer("⚠️ Avval Telegram akkauntingizni ulang.", reply_markup=kb.back_kb())
                return
                
    if source_chat_id:
        await db.set_user_setting(user_id, "source_chat_id", source_chat_id)
        await db.set_user_setting(user_id, "source_chat_title", source_chat_title)
        await message.answer(
            f"✅ **Manba guruh muvaffaqiyatli ulandi!**\n\n"
            f"📢 **Nomi:** {source_chat_title}\n"
            f"🆔 **ID:** `{source_chat_id}`",
            parse_mode="Markdown"
        )
        await render_dashboard(message, user_id, state)
    else:
        await message.answer("⚠️ Iltimos, manba guruhingizdan biron bir xabarni botga Forward qilib yuboring!", reply_markup=kb.back_kb())

# ==================== GROUP MANAGEMENT & DIALOG SYNC ====================
@router.callback_query(F.data == "manage_groups")
async def manage_groups_call(call: CallbackQuery, bot: Bot):
    user_id = call.from_user.id
    worker_mgr = getattr(bot, 'worker_manager', None)
    async with auth_flow.user_client_scope(user_id, worker_mgr) as client:
        if client and client.is_connected():
            try:
                from telethon.tl.types import Channel, Chat
                dialogs = await client.get_dialogs()
                settings = await db.get_user_settings(user_id)
                source_chat_id = settings.get("source_chat_id")
                
                for d in dialogs:
                    if (d.is_group or d.is_channel) and d.id != source_chat_id:
                        is_valid = False
                        if getattr(d.entity, 'megagroup', False) or isinstance(d.entity, Chat):
                            is_valid = True
                        if is_valid:
                            username = getattr(d.entity, 'username', None)
                            await db.add_or_update_user_group(
                                user_id=user_id,
                                chat_id=d.id,
                                title=d.name,
                                username=username,
                                is_active=True
                            )
            except Exception as e:
                logger.error(f"Error syncing dialogs for user {user_id}: {e}")
            
    groups = await db.get_user_groups(user_id)
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(
            f"👥 **Guruhlarni Boshqarish**\n"
            f"Jami {len(groups)} ta guruh mavjud.\n"
            "Xabar tarqatiladigan guruhlarni belgilang (✅ - faol, ⬜️ - o'chirilgan):",
            reply_markup=kb.paginated_groups_kb(groups, 0),
            parse_mode="Markdown"
        )
    await safe_answer(call)

@router.callback_query(F.data == "noop")
async def noop_call(call: CallbackQuery):
    await safe_answer(call)

@router.callback_query(F.data.startswith("bulk_groups_on_"))
async def bulk_groups_on_call(call: CallbackQuery):
    user_id = call.from_user.id
    page = int(call.data.split("_")[3])
    await db.set_all_user_groups_active(user_id, True)
    groups = await db.get_user_groups(user_id)
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_reply_markup(reply_markup=kb.paginated_groups_kb(groups, page))
    await safe_answer(call, "Barcha guruhlar faollashtirildi!")

@router.callback_query(F.data.startswith("bulk_groups_off_"))
async def bulk_groups_off_call(call: CallbackQuery):
    user_id = call.from_user.id
    page = int(call.data.split("_")[3])
    await db.set_all_user_groups_active(user_id, False)
    groups = await db.get_user_groups(user_id)
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_reply_markup(reply_markup=kb.paginated_groups_kb(groups, page))
    await safe_answer(call, "Barcha guruhlar o'chirildi!")

@router.callback_query(F.data.startswith("page_groups_"))
async def page_groups_call(call: CallbackQuery):
    user_id = call.from_user.id
    page = int(call.data.split("_")[2])
    groups = await db.get_user_groups(user_id)
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_reply_markup(reply_markup=kb.paginated_groups_kb(groups, page))
    await safe_answer(call)

@router.callback_query(F.data.startswith("toggle_group_"))
async def toggle_group_call(call: CallbackQuery):
    user_id = call.from_user.id
    parts = call.data.split("_")
    chat_id = int(parts[2])
    page = int(parts[3])
    
    groups = await db.get_user_groups(user_id)
    target = next((g for g in groups if g['chat_id'] == chat_id), None)
    if target:
        new_status = not target['is_active']
        await db.update_user_group_status(user_id, chat_id, target.get('status', 'Healthy'), is_active=new_status)
        
    groups = await db.get_user_groups(user_id)
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_reply_markup(reply_markup=kb.paginated_groups_kb(groups, page))
    await safe_answer(call)

# ==================== QUICK GROUP ADD (FORWARD & LINK) ====================
@router.message(F.forward_from_chat, StateFilter(None))
async def forward_group_inspector(message: Message):
    user_id = message.from_user.id
    chat = message.forward_from_chat
    if chat.type in ["group", "supergroup"]:
        title = chat.title or f"Guruh {chat.id}"
        username = chat.username
        await db.add_or_update_user_group(user_id=user_id, chat_id=chat.id, title=title, username=username, is_active=True)
        
        user_link = f"@{username}" if username else f"`{chat.id}`"
        text = (
            f"✅ **Guruh muvaffaqiyatli qo'shildi va faollashtirildi!**\n\n"
            f"👥 **Nomi:** **{title}**\n"
            f"🆔 **ID:** `{chat.id}`\n"
            f"🔗 **Havola:** {user_link}\n\n"
            f"Ushbu guruh e'lon tarqatish ro'yxatingizga kiritildi."
        )
        await message.answer(text, parse_mode="Markdown")
    else:
        await message.answer("⚠️ Uzatilgan xabar guruh yoki superguruhdan emas.")

@router.message(F.text & (F.text.startswith("@") | F.text.contains("t.me/")), StateFilter(None))
async def link_group_inspector(message: Message, bot: Bot):
    user_id = message.from_user.id
        
    worker_mgr = getattr(bot, 'worker_manager', None)
    async with auth_flow.user_client_scope(user_id, worker_mgr) as client:
        if not client:
            await message.answer("⚠️ Avval Telegram akkauntingizni ulang.")
            return
            
        link_or_user = message.text.strip()
        try:
            from telethon.tl.types import Channel, Chat
            entity = await client.get_entity(link_or_user)
            is_group = False
            if getattr(entity, 'megagroup', False) or isinstance(entity, Chat) or (isinstance(entity, Channel) and not entity.broadcast):
                is_group = True
                
            if is_group:
                title = getattr(entity, 'title', f"Guruh {entity.id}")
                username = getattr(entity, 'username', None)
                chat_id = entity.id
                if not str(chat_id).startswith("-100") and isinstance(entity, Channel):
                    chat_id = int(f"-100{entity.id}")
                    
                await db.add_or_update_user_group(user_id=user_id, chat_id=chat_id, title=title, username=username, is_active=True)
                user_link = f"@{username}" if username else f"`{chat_id}`"
                await message.answer(
                    f"✅ **Guruh muvaffaqiyatli qo'shildi!**\n\n"
                    f"👥 **Nomi:** **{title}**\n"
                    f"🆔 **ID:** `{chat_id}`\n"
                    f"🔗 **Havola:** {user_link}",
                    parse_mode="Markdown"
                )
            else:
                await message.answer("⚠️ Kiritilgan havola guruhga tegishli emas.")
        except Exception as e:
            logger.error(f"Error adding group from link for user {user_id}: {e}")
            await message.answer("⚠️ Guruhni havola orqali topib bo'lmadi. Guruhdagi birorta xabarni botga Forward qiling!")

# ==================== TIMING & JITTER CONFIG ====================
@router.callback_query(F.data == "adjust_timing")
async def adjust_timing_call(call: CallbackQuery):
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(
            "⏱ **Doira oralig'ini sozlash (Round Cooldown)**\n\n"
            "Barcha guruhlarga xabar yuborib bo'lingach, keyingi aylanmagacha kutish vaqti:",
            reply_markup=kb.timing_kb(),
            parse_mode="Markdown"
        )
    await safe_answer(call)

@router.callback_query(F.data.startswith("time_preset_"))
async def time_preset_call(call: CallbackQuery):
    user_id = call.from_user.id
    preset = call.data.split("_")[2]
    if preset == "1min":
        c_min, c_max = 60, 90
        label = "1 daqiqa (60-90s)"
    elif preset == "fast":
        c_min, c_max = 180, 300
        label = "Tez (3-5 daqiqa)"
    elif preset == "med":
        c_min, c_max = 300, 600
        label = "O'rtacha (5-10 daqiqa)"
    elif preset == "relax":
        c_min, c_max = 600, 900
        label = "Sekin (10-15 daqiqa)"
        
    await db.set_user_setting(user_id, "cycle_min", c_min)
    await db.set_user_setting(user_id, "cycle_max", c_max)
    await render_dashboard(call, user_id)
    await safe_answer(call, f"Doira vaqti sozlandi: {label}")

@router.callback_query(F.data == "adjust_jitter")
async def adjust_jitter_call(call: CallbackQuery):
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(
            "⚡️ **Yuborish tezligini sozlash (Send Jitter)**\n\n"
            "Bitta guruhga yuborilgach, keyingi guruhga yuborishgacha bo'lgan oraliq kutish vaqti:",
            reply_markup=kb.jitter_kb(),
            parse_mode="Markdown"
        )
    await safe_answer(call)

@router.callback_query(F.data.startswith("jitter_preset_"))
async def jitter_preset_call(call: CallbackQuery):
    user_id = call.from_user.id
    preset = call.data.split("_")[2]
    if preset == "fast":
        j_min, j_max = 1.5, 2.0
        label = "⚡️ Tezkor (1.5s - 2.0s)"
    elif preset == "med":
        j_min, j_max = 2.0, 4.0
        label = "⚖️ O'rtacha (2.0s - 4.0s)"
    elif preset == "safe":
        j_min, j_max = 6.0, 12.0
        label = "🛡 Xavfsiz (6.0s - 12.0s)"
        
    await db.set_user_setting(user_id, "jitter_min", j_min)
    await db.set_user_setting(user_id, "jitter_max", j_max)
    await render_dashboard(call, user_id)
    await safe_answer(call, f"Yuborish tezligi: {label}")

@router.callback_query(F.data == "time_custom")
async def time_custom_call(call: CallbackQuery, state: FSMContext):
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(
            "✍️ **O'zingiz doira vaqtini kiriting**\n\n"
            "Doiralar orasidagi minimal va maksimal kutish vaqtini (soniyalarda) probel bilan yuboring.\n"
            "Masalan: `60 90` yoki `180 300`",
            reply_markup=kb.back_kb(),
            parse_mode="Markdown"
        )
    await state.set_state(BotStates.waiting_for_custom_timing)
    await safe_answer(call)

@router.message(BotStates.waiting_for_custom_timing)
async def process_custom_timing(message: Message, state: FSMContext):
    user_id = message.from_user.id
    try:
        parts = message.text.strip().split()
        if len(parts) != 2:
            raise ValueError()
        c_min, c_max = int(parts[0]), int(parts[1])
        if c_min < 0 or c_max < c_min:
            raise ValueError()
            
        await db.set_user_setting(user_id, "cycle_min", c_min)
        await db.set_user_setting(user_id, "cycle_max", c_max)
        await render_dashboard(message, user_id, state)
    except ValueError:
        await message.answer(
            "⚠️ Noto'g'ri format. Iltimos, ikkita musbat son kiriting, masalan: `60 90` yoki `180 300`.",
            reply_markup=kb.back_kb()
        )

@router.callback_query(F.data == "jitter_custom")
async def jitter_custom_call(call: CallbackQuery, state: FSMContext):
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(
            "✍️ **O'zingiz yuborish tezligini kiriting**\n\n"
            "Har bir guruh orasidagi minimal va maksimal vaqtni (soniyalarda) probel bilan kiriting.\n"
            "Masalan: `1.5 2.0` yoki `2 4`",
            reply_markup=kb.back_kb(),
            parse_mode="Markdown"
        )
    await state.set_state(BotStates.waiting_for_custom_jitter)
    await safe_answer(call)

@router.message(BotStates.waiting_for_custom_jitter)
async def process_custom_jitter(message: Message, state: FSMContext):
    user_id = message.from_user.id
    try:
        parts = message.text.strip().split()
        if len(parts) != 2:
            raise ValueError()
        j_min, j_max = float(parts[0]), float(parts[1])
        if j_min < 0.5 or j_max < j_min:
            raise ValueError()
            
        await db.set_user_setting(user_id, "jitter_min", j_min)
        await db.set_user_setting(user_id, "jitter_max", j_max)
        await render_dashboard(message, user_id, state)
    except ValueError:
        await message.answer(
            "⚠️ Noto'g'ri format. Iltimos, kamida 0.5 bo'lgan ikkita son kiriting, masalan: `1.5 2.0`.",
            reply_markup=kb.back_kb()
        )

# ==================== /REMOVE OR /DELETE TARGET GROUP ====================
@router.message(Command("remove"))
@router.message(Command("delete"))
async def remove_group_cmd(message: Message, bot: Bot):
    user_id = message.from_user.id
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "ℹ️ **Guruhni ro'yxatdan o'chirish:**\n\n"
            "Misol:\n"
            "`/remove @guruh_nomi`\n"
            "`/remove https://t.me/guruh`\n"
            "`/remove -1001234567890`",
            parse_mode="Markdown"
        )
        return
        
    query = parts[1].strip()
    target_chat_id = None
    target_title = None
    
    groups = await db.get_user_groups(user_id)
    for g in groups:
        clean_username = (g.get('username') or '').lstrip('@').lower()
        query_username = query.lstrip('@').replace('https://t.me/', '').replace('http://t.me/', '').lower()
        if (clean_username and clean_username == query_username) or str(g['chat_id']) == query:
            target_chat_id = g['chat_id']
            target_title = g.get('title', 'Guruh')
            break
            
    if not target_chat_id:
        worker_mgr = getattr(bot, 'worker_manager', None)
        async with auth_flow.user_client_scope(user_id, worker_mgr) as client:
            if client:
                try:
                    entity = await client.get_entity(query)
                    entity_id = entity.id
                    if not str(entity_id).startswith("-100"):
                        from telethon.tl.types import Channel
                        if isinstance(entity, Channel):
                            entity_id = int(f"-100{entity.id}")
                    for g in groups:
                        if g['chat_id'] == entity_id:
                            target_chat_id = g['chat_id']
                            target_title = g.get('title', 'Guruh')
                            break
                except Exception:
                    pass
                
    if not target_chat_id:
        await message.answer(f"⚠️ `{query}` nomli guruh ro'yxatingizda topilmadi.", parse_mode="Markdown")
        return
        
    text = (
        f"❓ **Guruhni ro'yxatdan o'chirishni tasdiqlaysizmi?**\n\n"
        f"👥 **Guruh:** {target_title}\n"
        f"🆔 **ID:** `{target_chat_id}`"
    )
    await message.answer(text, reply_markup=kb.delete_confirm_kb(target_chat_id), parse_mode="Markdown")

@router.callback_query(F.data.startswith("confirm_delete_"))
async def confirm_delete_call(call: CallbackQuery):
    user_id = call.from_user.id
    chat_id = int(call.data.split("_")[2])
    await db.delete_user_group(user_id, chat_id)
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text("✅ Guruh ro'yxatingizdan muvaffaqiyatli o'chirildi!")
    await safe_answer(call, "Guruh o'chirildi!", show_alert=True)

# ==================== MANUAL TEST TRIGGER ====================
@router.callback_query(F.data == "trigger_test")
async def trigger_test_call(call: CallbackQuery, bot: Bot):
    user_id = call.from_user.id
    worker_mgr = getattr(bot, 'worker_manager', None)
    if worker_mgr:
        success = await worker_mgr.trigger_test_round(user_id)
        if success:
            await safe_answer(call, "🧪 Sinov yuborish boshlandi!", show_alert=True)
            return
    await safe_answer(call, "Akkaunt yoki manba guruh ulanmagan.", show_alert=True)

# ==================== SUPERADMIN COMMANDS (/admin) ====================
@router.message(Command("admin"))
async def admin_panel_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
        
    users = await db.get_all_users()
    pending = await db.get_pending_payment_requests()
    
    text = (
        "👑 **SuperAdmin Boshqaruv Paneli**\n\n"
        f"👥 **Jami foydalanuvchilar:** {len(users)} ta\n"
        f"🧾 **Kutilayotgan to'lov cheklari:** {len(pending)} ta\n"
    )
    await message.answer(text, reply_markup=kb.superadmin_kb(), parse_mode="Markdown")

@router.callback_query(F.data == "admin_stats")
async def admin_stats_call(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    users = await db.get_all_users()
    pending = await db.get_pending_payment_requests()
    
    active_subs = 0
    now = datetime.utcnow()
    for u in users:
        exp = u.get('subscription_expiry')
        if exp:
            try:
                if datetime.strptime(exp, '%Y-%m-%d %H:%M:%S') > now:
                    active_subs += 1
            except Exception:
                pass
                
    text = (
        "📊 **Platforma Statistikasi:**\n\n"
        f"👥 **Jami ro'yxatdan o'tganlar:** {len(users)} ta\n"
        f"⭐️ **Faol VIP/Sinov obunachilar:** {active_subs} ta\n"
        f"🧾 **Ko'rib chiqilayotgan to'lovlar:** {len(pending)} ta\n"
    )
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(text, reply_markup=kb.superadmin_kb(), parse_mode="Markdown")
    await safe_answer(call)

@router.callback_query(F.data == "admin_pending_cheques")
async def admin_pending_cheques_call(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    pending = await db.get_pending_payment_requests()
    if not pending:
        with contextlib.suppress(TelegramBadRequest):
            await call.message.edit_text("✅ Kutilayotgan to'lov cheklari yo'q.", reply_markup=kb.superadmin_kb())
        await safe_answer(call)
        return
        
    text = f"🧾 **Kutilayotgan to'lov cheklari: {len(pending)} ta**\n\n"
    for p in pending[:5]:
        text += f"• Chek #{p['id']}: User `{p['user_id']}` — {p['plan_months']} oy ({p['amount_uzs']:,} so'm)\n"
    text += "\nTo'lovlarni tasdiqlash uchun admin kanaliga qarang yoki veb-paneldan foydalaning."
    
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(text, reply_markup=kb.superadmin_kb(), parse_mode="Markdown")
    await safe_answer(call)

@router.callback_query(F.data.in_(["admin_broadcast", "admin_broadcast_msg"]))
async def admin_broadcast_menu_call(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await safe_answer(call, "Ruxsat yo'q!", show_alert=True)
        return

    from src.harvester.service import default_harvester_service
    is_online = default_harvester_service.is_connected()
    if not is_online:
        await safe_answer(
            call,
            "⚠️ DIQQAT: Userbot ulanmagan!\n\n"
            "Xabarnoma yuborish xizmatidan foydalanish uchun Userbot sessiyasi faol holatda bo'lishi lozim.",
            show_alert=True
        )
        return

    text = (
        "📢 **Ommaviy Xabarnoma Yuborish**\n\n"
        "Qaysi yo'nalishda e'lon yubormoqchisiz?\n"
        "• **Bot foydalanuvchilariga**: Botdan ro'yxatdan o'tgan barcha haydovchilarga xabar.\n"
        "• **Guruhlarga**: Harvester monitoring superguruhlariga Userbot orqali e'lon tarqatish.\n\n"
        "📡 Userbot holati: 🟢 **FAOL**"
    )
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(text, reply_markup=kb.admin_broadcast_kb(userbot_online=True), parse_mode="Markdown")
    await safe_answer(call)

@router.message(Command("broadcast"))
async def admin_broadcast_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    from src.harvester.service import default_harvester_service
    is_online = default_harvester_service.is_connected()
    if not is_online:
        await message.answer(
            "⚠️ **DIQQAT: Userbot ulanmagan!**\n\n"
            "Xabarnoma yuborish xizmatidan foydalanish uchun Userbot sessiyasi faol holatda bo'lishi lozim.",
            reply_markup=kb.admin_return_kb(),
            parse_mode="Markdown"
        )
        return

    text = (
        "📢 **Ommaviy Xabarnoma Yuborish**\n\n"
        "Qaysi yo'nalishda e'lon yubormoqchisiz?\n"
        "• **Bot foydalanuvchilariga**: Botdan ro'yxatdan o'tgan barcha haydovchilarga xabar.\n"
        "• **Guruhlarga**: Harvester monitoring superguruhlariga Userbot orqali e'lon tarqatish.\n\n"
        "📡 Userbot holati: 🟢 **FAOL**"
    )
    await message.answer(text, reply_markup=kb.admin_broadcast_kb(userbot_online=True), parse_mode="Markdown")

@router.callback_query(F.data == "admin_broadcast_users")
async def admin_broadcast_users_call(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    text = (
        "👥 **Bot Foydalanuvchilariga Xabar Yuborish**\n\n"
        "Barcha ro'yxatdan o'tgan foydalanuvchilarga yuboriladigan xabar matnini kiriting:\n"
        "(Bekor qilish uchun: /cancel)"
    )
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(text, reply_markup=kb.admin_return_kb(), parse_mode="Markdown")
    await state.set_state(AdminStates.waiting_for_broadcast)
    await safe_answer(call)

@router.message(AdminStates.waiting_for_broadcast)
async def process_admin_broadcast(message: Message, state: FSMContext, bot: Bot):
    if message.from_user.id != ADMIN_ID:
        return
    if message.text == "/cancel":
        await state.clear()
        await message.answer("Xabar tarqatish bekor qilindi.", reply_markup=kb.admin_return_kb())
        return
        
    text = message.text
    users = await db.get_all_users()
    await state.clear()
    status_msg = await message.answer(f"⏳ {len(users)} ta foydalanuvchiga xabar yuborilmoqda...")
    
    sent = 0
    for u in users:
        try:
            await bot.send_message(chat_id=u['user_id'], text=text, parse_mode="Markdown")
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass
            
    await status_msg.edit_text(
        f"✅ **Xabar muvaffaqiyatli tarqatildi!**\n\n"
        f"Yetkazildi: **{sent}/{len(users)} ta** foydalanuvchi.",
        reply_markup=kb.admin_return_kb(),
        parse_mode="Markdown"
    )

@router.callback_query(F.data == "admin_broadcast_groups")
async def admin_broadcast_groups_call(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    from src.harvester.service import default_harvester_service
    if not default_harvester_service.is_connected():
        await safe_answer(
            call,
            "⚠️ DIQQAT: Userbot ulanmagan!\n\n"
            "Guruhlarga e'lon tarqatish uchun Userbot ulangan bo'lishi kerak.",
            show_alert=True
        )
        return
    groups = await db.get_harvester_groups(active_only=True)
    if not groups:
        await safe_answer(call, "⚠️ Faol monitoring guruhlari mavjud emas.", show_alert=True)
        return

    text = (
        f"📡 **Harvester Guruhlarga E'lon Tarqatish**\n\n"
        f"Xabar {len(groups)} ta monitoring superguruhiga Userbot orqali yuboriladi.\n\n"
        "Yuboriladigan e'lon matnini kiriting:\n"
        "(Bekor qilish uchun: /cancel)"
    )
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(text, reply_markup=kb.admin_return_kb(), parse_mode="Markdown")
    await state.set_state(AdminStates.waiting_for_group_broadcast)
    await safe_answer(call)

@router.message(AdminStates.waiting_for_group_broadcast)
async def process_admin_group_broadcast(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    if message.text == "/cancel":
        await state.clear()
        await message.answer("Guruhlarga e'lon tarqatish bekor qilindi.", reply_markup=kb.admin_return_kb())
        return

    text = message.text
    await state.clear()
    status_msg = await message.answer("⏳ Guruhlarga e'lon Userbot orqali tarqatilmoqda...")
    from src.harvester.service import default_harvester_service
    res = await default_harvester_service.broadcast_to_groups(text)
    if res.get("success"):
        await status_msg.edit_text(
            f"✅ **Guruhlarga e'lon muvaffaqiyatli tarqatildi!**\n\n"
            f"• Yetkazildi: **{res.get('sent', 0)} ta guruh**\n"
            f"• Xatolik: {res.get('failed', 0)} ta",
            reply_markup=kb.admin_return_kb(),
            parse_mode="Markdown"
        )
    else:
        await status_msg.edit_text(
            f"❌ **Xatolik:** {res.get('error', 'E\'lon tarqatib bo\'lmadi')}",
            reply_markup=kb.admin_return_kb(),
            parse_mode="Markdown"
        )

@router.callback_query(F.data == "dismiss")
async def dismiss_call(call: CallbackQuery):
    with contextlib.suppress(TelegramBadRequest):
        await call.message.delete()
    await safe_answer(call)

@router.callback_query(F.data == "admin_finance")
async def admin_finance_call(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    stats = await db.get_earnings_stats()
    pending = await db.get_pending_payment_requests()
    
    text = (
        "💰 **Taksi Xabarchi — Moliyaviy Hisobot**\n\n"
        f"💵 **Jami tushum:** `{stats['total_revenue']:,} so'm`\n"
        f"📅 **Shu oy:** `{stats['this_month']:,} so'm`\n"
        f"⏮ **O'tgan oy:** `{stats['last_month']:,} so'm`\n"
        f"🧾 **Tasdiqlangan to'lovlar:** `{stats['approved_count']} ta`\n"
        f"⏳ **Kutilayotgan cheklar:** `{len(pending)} ta`\n\n"
        "📊 **Oylik taqsimot:**\n"
    )
    if stats['monthly_breakdown']:
        for m in stats['monthly_breakdown'][:6]:
            text += f"• `{m['month']}`: {m['total_amount']:,} so'm ({m['count']} ta chek)\n"
    else:
        text += "• Hozircha tasdiqlangan to'lovlar mavjud emas.\n"
        
    text += "\n🌐 Batafsil ma'lumot va cheklar tarixi veb-panelda: `/finance` sahifasida."
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(text, reply_markup=kb.admin_return_kb(), parse_mode="Markdown")
    await safe_answer(call)

@router.callback_query(F.data == "admin_users")
async def admin_users_call(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    users = await db.get_all_users()
    pending = await db.get_pending_payment_requests()
    
    active_vips = 0
    trial_users = 0
    now = datetime.utcnow()
    for u in users:
        exp = u.get('subscription_expiry')
        if exp:
            try:
                if datetime.strptime(exp, '%Y-%m-%d %H:%M:%S') > now:
                    active_vips += 1
            except Exception:
                pass
        if u.get('is_trial'):
            trial_users += 1

    text = (
        "👥 **Foydalanuvchilar Statistikasi**\n\n"
        f"• 👥 **Jami ro'yxatdan o'tganlar:** `{len(users)} ta`\n"
        f"• ⭐️ **Faol VIP obunachilar:** `{active_vips} ta`\n"
        f"• 🎁 **Sinov muddatidagilar:** `{trial_users} ta`\n"
        f"• 🧾 **Kutilayotgan to'lov cheklari:** `{len(pending)} ta`\n\n"
        "🌐 Foydalanuvchilarni to'liq boshqarish va cheklarni tasdiqlash veb-panelda mavjud."
    )
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(text, reply_markup=kb.admin_return_kb(), parse_mode="Markdown")
    await safe_answer(call)

@router.message(Command("finance"))
@router.message(Command("earnings"))
async def admin_finance_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    stats = await db.get_earnings_stats()
    pending = await db.get_pending_payment_requests()
    
    text = (
        "💰 **Taksi Xabarchi — Moliyaviy Hisobot**\n\n"
        f"💵 **Jami tushum:** `{stats['total_revenue']:,} so'm`\n"
        f"📅 **Shu oy:** `{stats['this_month']:,} so'm`\n"
        f"⏮ **O'tgan oy:** `{stats['last_month']:,} so'm`\n"
        f"🧾 **Tasdiqlangan to'lovlar:** `{stats['approved_count']} ta`\n"
        f"⏳ **Kutilayotgan cheklar:** `{len(pending)} ta`\n\n"
        "📊 **Oylik taqsimot:**\n"
    )
    if stats['monthly_breakdown']:
        for m in stats['monthly_breakdown'][:6]:
            text += f"• `{m['month']}`: {m['total_amount']:,} so'm ({m['count']} ta chek)\n"
    else:
        text += "• Hozircha tasdiqlangan to'lovlar mavjud emas.\n"
        
    text += "\n🌐 Batafsil ma'lumot va cheklar tarixi veb-panelda: `/finance` sahifasida."
    await message.answer(text, reply_markup=kb.admin_return_kb(), parse_mode="Markdown")

# ==================== PROMOCODES & DISCOUNT CAMPAIGNS ====================
@router.callback_query(F.data == "enter_promocode")
async def enter_promocode_call(call: CallbackQuery, state: FSMContext):
    await state.set_state(PromoStates.waiting_for_promocode)
    text = (
        "🎟 **Promokod kiritish**\n\n"
        "Agar sizda chegirma yoki bepul VIP kunlar beruvchi promokod bo'lsa, "
        "iltimos, uni quyida yozib yuboring (masalan: `BAHOR2026`):"
    )
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(text, reply_markup=kb.cancel_promo_kb(), parse_mode="Markdown")
    await safe_answer(call)

@router.message(PromoStates.waiting_for_promocode, F.text)
async def process_promocode_input(message: Message, state: FSMContext):
    user_id = message.from_user.id
    code = message.text.strip()
    success, msg, promo = await db.redeem_promocode(user_id, code)
    if not success:
        await message.answer(f"{msg}\n\nIltimos, qaytadan kiriting yoki bekor qiling:", reply_markup=kb.cancel_promo_kb())
        return
        
    if promo and promo.get("discount_type") == "DAYS":
        await state.clear()
        await message.answer(msg, reply_markup=kb.back_kb(), parse_mode="Markdown")
        return
        
    # PERCENT or FIXED discount applied to cart
    await state.update_data(applied_promo=promo)
    campaign = await db.get_active_campaign_discount()
    plan_prices = calculate_effective_plan_prices(campaign, promo)
    
    text = (
        f"{msg}\n\n"
        "👇 Chegirma muvaffaqiyatli hisoblandi! O'zingizga ma'qul tarifni tanlang:"
    )
    await message.answer(text, reply_markup=kb.pricing_plans_kb(plan_prices), parse_mode="Markdown")

@router.message(Command("promocode"))
@router.message(Command("promo"))
async def promo_command(message: Message, state: FSMContext):
    parts = message.text.strip().split()
    user_id = message.from_user.id
    if len(parts) > 1:
        code = parts[1]
        success, msg, promo = await db.redeem_promocode(user_id, code)
        if not success:
            await message.answer(msg)
            return
        if promo and promo.get("discount_type") == "DAYS":
            await message.answer(msg, reply_markup=kb.back_kb(), parse_mode="Markdown")
            return
        await state.update_data(applied_promo=promo)
        campaign = await db.get_active_campaign_discount()
        plan_prices = calculate_effective_plan_prices(campaign, promo)
        await message.answer(f"{msg}\n\n👇 Tariflar:", reply_markup=kb.pricing_plans_kb(plan_prices), parse_mode="Markdown")
    else:
        await state.set_state(PromoStates.waiting_for_promocode)
        await message.answer(
            "🎟 **Promokod kiritish**\n\nIltimos, promokodingizni yozib yuboring:",
            reply_markup=kb.cancel_promo_kb(),
            parse_mode="Markdown"
        )

# ==================== SUPERADMIN DISCOUNT & PROMO COMMANDS ====================
@router.message(Command("discounts"))
@router.message(Command("promos"))
async def admin_discounts_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    campaign = await db.get_active_campaign_discount()
    promos = await db.get_promocodes()
    
    text = "🏷 **Chegirmalar va Promokodlar Boshqaruvi**\n\n"
    if campaign:
        text += (
            f"🔥 **Faol Aksiya:** `{campaign['title']}`\n"
            f"⏳ Tugashiga: `{campaign.get('remaining_days', 0)} kun, {campaign.get('remaining_hours', 0)} soat`\n"
            f"📊 Tariflar chegirmasi: `{campaign.get('plan_discounts')}`\n"
            "To'xtatish uchun: `/stopdiscount`\n\n"
        )
    else:
        text += "⚪️ **Hozirda faol aksiya yo'q.**\nBoshlash: `/setdiscount <KUN> <1m%> <3m%> <6m%> <12m%> [NOMI]`\n\n"
        
    text += f"🎟 **Promokodlar ({len(promos)} ta):**\n"
    for p in promos[:5]:
        val_str = f"+{int(p['discount_value'])} kun" if p['discount_type'] == 'DAYS' else f"-{int(p['discount_value'])}%"
        text += f"• `{p['code']}`: {val_str} ({p['used_count']}/{p['max_uses']} ta) — {p['status_badge']}\n"
        
    text += "\n🌐 Veb-paneldan boshqarish: `/discounts` sahifasida."
    await message.answer(text, reply_markup=kb.admin_return_kb(), parse_mode="Markdown")

@router.message(Command("setdiscount"))
async def admin_setdiscount_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.strip().split()
    if len(parts) < 3:
        await message.answer(
            "⚠️ **Noto'g'ri format!**\n\n"
            "Formatlar:\n"
            "1. Yagona: `/setdiscount <KUN> <FOIZ%> [NOMI]`\n"
            "Masalan: `/setdiscount 3 20 Bahorgi aksiya`\n\n"
            "2. Har bir tarifga: `/setdiscount <KUN> <1m%> <3m%> <6m%> <12m%> [NOMI]`\n"
            "Masalan: `/setdiscount 3 0 12 15 20 Katta chegirma`",
            reply_markup=kb.admin_return_kb(),
            parse_mode="Markdown"
        )
        return
        
    try:
        duration_days = int(parts[1])
        if len(parts) >= 6 and parts[2].isdigit() and parts[3].isdigit():
            p1 = int(parts[2])
            p3 = int(parts[3])
            p6 = int(parts[4])
            p12 = int(parts[5])
            title = " ".join(parts[6:]) if len(parts) > 6 else "Maxsus Aksiya"
            plan_discounts = {"1": p1, "3": p3, "6": p6, "12": p12}
        else:
            flat_pct = int(parts[2].replace("%", ""))
            title = " ".join(parts[3:]) if len(parts) > 3 else "Maxsus Chegirma"
            plan_discounts = {"1": flat_pct, "3": flat_pct, "6": flat_pct, "12": flat_pct}
            
        camp_id = await db.set_campaign_discount(title, plan_discounts, duration_days)
        await message.answer(
            f"✅ **Aksiya muvaffaqiyatli ishga tushirildi!** (ID: #{camp_id})\n\n"
            f"🏷 Nomi: **{title}**\n"
            f"⏳ Muddat: **{duration_days} kun**\n"
            f"📊 Chegirmalar: `{plan_discounts}`",
            reply_markup=kb.admin_return_kb(),
            parse_mode="Markdown"
        )
    except Exception as e:
        await message.answer(f"❌ Xatolik: {e}", reply_markup=kb.admin_return_kb())

@router.message(Command("stopdiscount"))
async def admin_stopdiscount_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await db.stop_campaign_discount()
    await message.answer("🛑 **Faol aksiya to'xtatildi.** Barcha tariflar standart holatga qaytarildi.", reply_markup=kb.admin_return_kb())

@router.message(Command("newpromo"))
async def admin_newpromo_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.strip().split()
    if len(parts) < 6:
        await message.answer(
            "⚠️ **Format:** `/newpromo <KOD> <TURI: days|percent|fixed> <QIYMATI> <MUDDAT_KUN> <LIMIT> [TARIFLAR]`\n\n"
            "Misollar:\n"
            "• `/newpromo BAHOR days 7 14 50` (+7 kun bepul VIP, 14 kun, 50 marta)\n"
            "• `/newpromo TAXI20 percent 20 7 100 6,12` (20% chegirma, faqat 6 va 12 oylik tariflarga)",
            reply_markup=kb.admin_return_kb(),
            parse_mode="Markdown"
        )
        return
        
    try:
        code = parts[1].upper()
        d_type = parts[2].upper()
        d_val = float(parts[3])
        dur_days = int(parts[4])
        max_uses = int(parts[5])
        plans = parts[6] if len(parts) > 6 else "ALL"
        
        promo_id = await db.create_promocode(
            code=code,
            discount_type=d_type,
            discount_value=d_val,
            duration_days=dur_days,
            max_uses=max_uses,
            applicable_plans=plans
        )
        await message.answer(
            f"✅ **Promokod yaratildi!** (ID: #{promo_id})\n\n"
            f"🎟 Kod: `{code}`\n"
            f"🎁 Tur: **{d_type}** ({d_val})\n"
            f"⏳ Muddat: **{dur_days} kun**\n"
            f"👥 Limit: **{max_uses} ta**\n"
            f"📦 Tariflar: `{plans}`",
            reply_markup=kb.admin_return_kb(),
            parse_mode="Markdown"
        )
    except Exception as e:
        await message.answer(f"❌ Xatolik: {e}", reply_markup=kb.admin_return_kb())

# ==================== SUPERADMIN PLANS & PRICING MANAGEMENT ====================
async def render_admin_plans(message_or_call):
    camp = await db.get_active_campaign_discount()
    promos = await db.get_promocodes()
    active_promos = [p for p in promos if p.get("status_badge") == "🟢 FAOL"]

    text = (
        "💳 **Tariflar va To'lov Sozlamalari**\n\n"
        "📦 **Standart Tarif Rejalari:**\n"
        "• 1 oylik obuna: **25,000 so'm** (30 kun)\n"
        "• 3 oylik obuna: **65,000 so'm** (90 kun) — *Tejamkor*\n"
        "• 6 oylik obuna: **120,000 so'm** (180 kun) — *Optima*\n"
        "• 12 oylik obuna: **225,000 so'm** (390 kun) — *+1 oy bepul 🔥*\n\n"
    )
    if camp:
        d = camp.get("plan_discounts", {})
        rem_days = camp.get("remaining_days", 0)
        rem_hours = camp.get("remaining_hours", 0)
        text += (
            f"🔥 **Faol Aksiya:** `{camp.get('title', 'Aksiya')}`\n"
            f"• Chegirmalar: 1m: **{d.get('1', 0)}%** | 3m: **{d.get('3', 0)}%** | 6m: **{d.get('6', 0)}%** | 12m: **{d.get('12', 0)}%**\n"
            f"• Qolgan vaqt: `{rem_days} kun, {rem_hours} soat`\n\n"
        )
    else:
        text += "⚪️ **Faol Aksiya:** Hozirda umumiy aksiya yo'q.\n\n"

    text += (
        f"🎟 **Promokodlar:** Jami {len(promos)} ta ({len(active_promos)} ta faol)\n\n"
        "⚡️ **Boshqaruv buyruqlari:**\n"
        "• `/setdiscount <kun> <% yoki 1m 3m 6m 12m> [nomi]` — Chegirma aksiyasini yoqish\n"
        "• `/stopdiscount` — Faol aksiyani to'xtatish\n"
        "• `/newpromo` — Yangi promo-kod yaratish\n"
        "• `/discounts` — Barcha chegirma va promolarni ko'rish"
    )

    markup = kb.admin_plans_kb(has_active_discount=bool(camp))
    if isinstance(message_or_call, Message):
        await message_or_call.answer(text, reply_markup=markup, parse_mode="Markdown")
    else:
        with contextlib.suppress(TelegramBadRequest):
            await message_or_call.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")

@router.callback_query(F.data == "admin_plans")
async def admin_plans_call(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    await render_admin_plans(call)
    await safe_answer(call)

@router.message(Command("plans"))
async def admin_plans_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await render_admin_plans(message)

@router.callback_query(F.data == "admin_promos")
async def admin_promos_call(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    await render_admin_plans(call)
    await safe_answer(call)

@router.callback_query(F.data == "admin_stop_discount")
async def admin_stop_discount_call(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    await db.stop_campaign_discount()
    await safe_answer(call, "🛑 Aksiya to'xtatildi!", show_alert=True)
    await render_admin_plans(call)

@router.callback_query(F.data == "admin_set_discount_info")
async def admin_set_discount_info_call(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    text = (
        "🏷 **Yangi Chegirma Aksiyasi Belgilash**\n\n"
        "Aksiya boshlash uchun quyidagi buyruq formatlaridan birini yozib yuboring:\n\n"
        "1. **Barcha tariflarga bir xil chegirma:**\n"
        "`/setdiscount <KUN> <FOIZ%> [NOMI]`\n"
        "Masalan: `/setdiscount 3 20 Bahorgi aksiya`\n\n"
        "2. **Har bir tarifga alohida chegirma:**\n"
        "`/setdiscount <KUN> <1m%> <3m%> <6m%> <12m%> [NOMI]`\n"
        "Masalan: `/setdiscount 3 0 10 15 20 Katta aksiya`"
    )
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(text, reply_markup=kb.admin_return_kb(), parse_mode="Markdown")
    await safe_answer(call)

@router.callback_query(F.data == "admin_new_promo_info")
async def admin_new_promo_info_call(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    text = (
        "🎟 **Yangi Promokod Yaratish**\n\n"
        "Yangi promo-kod yaratish uchun quyidagi buyruqdan foydalaning:\n"
        "`/newpromo <KOD> <days|percent> <QIYMAT> <KUN> <LIMIT> [TARIFLAR]`\n\n"
        "**Misollar:**\n"
        "• `/newpromo BAHOR days 7 14 50` (+7 kun bepul VIP, 14 kunlik amal qilish, 50 marta)\n"
        "• `/newpromo TAXI20 percent 20 7 100 6,12` (20% chegirma, faqat 6 va 12 oylik tariflarga)"
    )
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(text, reply_markup=kb.admin_return_kb(), parse_mode="Markdown")
    await safe_answer(call)

# ==================== V3 DRIVER RADAR HANDLERS (STAGE 3) ====================

async def render_radar_menu(message_or_call, user_id: int):
    user = await db.get_user(user_id)
    user_script = await db.get_user_script(user_id)
    sub_badge, is_vip = check_subscription(user.get("subscription_expiry") if user else None, script=user_script)
    prefs = await db.get_driver_radar_preferences(user_id)

    is_active = bool(prefs.get("is_radar_active", True))
    direction = prefs.get("direction", "both")
    allow_passenger = bool(prefs.get("allow_passenger", True))
    allow_cargo = bool(prefs.get("allow_cargo", True))
    sound_alerts = bool(prefs.get("sound_alerts", True))
    selected_districts = prefs.get("selected_districts", [])
    if not isinstance(selected_districts, list):
        selected_districts = []

    dir_names = {
        "both": "Toshkent ⇄ Andijon (Ikkala tomon)",
        "toshkent_to_andijon": "Toshkent ➡️ Andijon",
        "andijon_to_toshkent": "Andijon ➡️ Toshkent"
    }
    dir_str = t(dir_names.get(direction, "Toshkent ⇄ Andijon"), user_script)

    types_list = []
    if allow_passenger:
        types_list.append(t("Yo'lovchi (✅)", user_script))
    if allow_cargo:
        types_list.append(t("Pochta/Yuk (✅)", user_script))
    if not types_list:
        types_list.append(t("Tanlanmagan (❌)", user_script))
    types_str = " | ".join(types_list)

    district_dict = dict(kb.ANDIJON_RADAR_DISTRICTS)
    district_names = [t(district_dict.get(d, d), user_script) for d in selected_districts]
    if district_names:
        dist_str = ", ".join(district_names[:6])
        if len(district_names) > 6:
            dist_str += f" {t('va yana', user_script)} {len(district_names) - 6} {t('ta', user_script)}"
    else:
        dist_str = t("Barcha tumanlar (Filtrsiz)", user_script)

    status_badge = t("🟢 YONIQ (Aktiv)", user_script) if is_active else t("🔴 TO'XTATILGAN (Pauza)", user_script)
    sound_badge = t("🔔 Ovozli", user_script) if sound_alerts else t("🔕 Tovushsiz", user_script)

    header = t("🎯 BUYURTMALAR", user_script)
    subhead = t("Guruhlardagi saralangan toza mijoz va pochta buyurtmalarini soniyada tutib beradi.", user_script)
    sub_lbl = t("Obuna holati:", user_script)
    radar_lbl = t("Radar:", user_script)
    dir_lbl = t("Yo'nalish:", user_script)
    order_type_lbl = t("Buyurtma turi:", user_script)
    notif_lbl = t("Bildirishnoma:", user_script)
    dist_lbl = t(f"Tanlangan tumanlar ({len(selected_districts)} ta):", user_script)
    tip = t("Avtomatlashtirilgan tranzit yo'lak algoritmi siz tanlagan tumanlar va ularga tutash qo'shni tumanlardagi buyurtmalarni sizga yetkazadi!", user_script)

    text = (
        f"🎯 <b>{header}</b>\n"
        f"<i>{subhead}</i>\n\n"
        f"⭐️ <b>{sub_lbl}</b> {sub_badge}\n"
        f"📡 <b>{radar_lbl}</b> {status_badge}\n"
        f"🔀 <b>{dir_lbl}</b> {dir_str}\n"
        f"📦 <b>{order_type_lbl}</b> {types_str}\n"
        f"🔔 <b>{notif_lbl}</b> {sound_badge}\n\n"
        f"📍 <b>{dist_lbl}</b>\n"
        f"• <i>{dist_str}</i>\n\n"
        f"💡 <i>{tip}</i>"
    )

    markup = kb.radar_menu_kb(prefs, is_vip, script=user_script)

    if isinstance(message_or_call, Message):
        await message_or_call.answer(text, reply_markup=markup, parse_mode="HTML")
    else:
        with contextlib.suppress(TelegramBadRequest):
            await message_or_call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")

async def render_radar_districts(call: CallbackQuery, user_id: int):
    user_script = await db.get_user_script(user_id)
    prefs = await db.get_driver_radar_preferences(user_id)
    districts = prefs.get("selected_districts", [])
    if not isinstance(districts, list):
        districts = []

    header = t("📍 RADAR TUMANLAR FILTRI", user_script)
    desc1 = t("Qaysi tumanlardan yo'lovchi yoki pochta olmoqchi bo'lsangiz, ularni belgilang.", user_script)
    desc2 = t("Tizim tanlangan tumanlar va ularning tranzit yo'lagidagi buyurtmalarni filtrlash uchun xizmat qiladi.", user_script)
    sel_info = t(f"Hozirda tanlangan: {len(districts)} ta tuman", user_script)

    text = (
        f"<b>{header}</b>\n\n"
        f"{desc1}\n"
        f"<i>{desc2}</i>\n\n"
        f"<b>{sel_info}</b>"
    )
    markup = kb.radar_districts_kb(districts, script=user_script)
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")

@router.message(Command("radar"))
async def radar_command(message: Message, state: FSMContext):
    if state:
        await state.clear()
    await render_radar_menu(message, message.from_user.id)

@router.callback_query(F.data == "radar_menu")
async def radar_menu_call(call: CallbackQuery):
    await render_radar_menu(call, call.from_user.id)
    await safe_answer(call)

@router.callback_query(F.data == "radar_toggle_state")
async def radar_toggle_state_call(call: CallbackQuery):
    user_id = call.from_user.id
    user_script = await db.get_user_script(user_id)
    prefs = await db.get_driver_radar_preferences(user_id)
    new_state = 0 if prefs.get("is_radar_active", 1) else 1
    await db.update_driver_radar_preferences(user_id, is_radar_active=new_state)
    await render_radar_menu(call, user_id)
    status_msg = t("🟢 Radar faollashtirildi!", user_script) if new_state else t("🔴 Radar to'xtatildi (pauza)!", user_script)
    await safe_answer(call, status_msg)

@router.callback_query(F.data == "radar_toggle_dir")
async def radar_toggle_dir_call(call: CallbackQuery):
    user_id = call.from_user.id
    prefs = await db.get_driver_radar_preferences(user_id)
    current_dir = prefs.get("direction", "both")
    cycle = {
        "both": "toshkent_to_andijon",
        "toshkent_to_andijon": "andijon_to_toshkent",
        "andijon_to_toshkent": "both"
    }
    next_dir = cycle.get(current_dir, "both")
    await db.update_driver_radar_preferences(user_id, direction=next_dir)
    await render_radar_menu(call, user_id)
    await safe_answer(call)

@router.callback_query(F.data == "radar_toggle_passenger")
async def radar_toggle_passenger_call(call: CallbackQuery):
    user_id = call.from_user.id
    prefs = await db.get_driver_radar_preferences(user_id)
    new_val = 0 if prefs.get("allow_passenger", 1) else 1
    await db.update_driver_radar_preferences(user_id, allow_passenger=new_val)
    await render_radar_menu(call, user_id)
    await safe_answer(call)

@router.callback_query(F.data == "radar_toggle_cargo")
async def radar_toggle_cargo_call(call: CallbackQuery):
    user_id = call.from_user.id
    prefs = await db.get_driver_radar_preferences(user_id)
    new_val = 0 if prefs.get("allow_cargo", 1) else 1
    await db.update_driver_radar_preferences(user_id, allow_cargo=new_val)
    await render_radar_menu(call, user_id)
    await safe_answer(call)

@router.callback_query(F.data == "radar_toggle_sound")
async def radar_toggle_sound_call(call: CallbackQuery):
    user_id = call.from_user.id
    user_script = await db.get_user_script(user_id)
    prefs = await db.get_driver_radar_preferences(user_id)
    new_val = 0 if prefs.get("sound_alerts", 1) else 1
    await db.update_driver_radar_preferences(user_id, sound_alerts=new_val)
    await render_radar_menu(call, user_id)
    msg = t("🔔 Ovozli bildirishnomalar yoqildi", user_script) if new_val else t("🔕 Bildirishnomalar tovushsiz rejimga o'tkazildi", user_script)
    await safe_answer(call, msg)

@router.callback_query(F.data == "radar_districts")
async def radar_districts_call(call: CallbackQuery):
    await render_radar_districts(call, call.from_user.id)
    await safe_answer(call)

@router.callback_query(F.data.startswith("radar_district_"))
async def radar_toggle_district_call(call: CallbackQuery):
    user_id = call.from_user.id
    d_id = call.data.replace("radar_district_", "")
    await db.toggle_driver_district(user_id, d_id)
    await render_radar_districts(call, user_id)
    await safe_answer(call)

@router.callback_query(F.data == "radar_districts_all")
async def radar_districts_all_call(call: CallbackQuery):
    user_id = call.from_user.id
    user_script = await db.get_user_script(user_id)
    all_districts = [d[0] for d in kb.ANDIJON_RADAR_DISTRICTS]
    await db.update_driver_radar_preferences(user_id, selected_districts=all_districts)
    await render_radar_districts(call, user_id)
    await safe_answer(call, t("✅ Barcha tumanlar tanlandi", user_script))

@router.callback_query(F.data == "radar_districts_clear")
async def radar_districts_clear_call(call: CallbackQuery):
    user_id = call.from_user.id
    user_script = await db.get_user_script(user_id)
    await db.update_driver_radar_preferences(user_id, selected_districts=[])
    await render_radar_districts(call, user_id)
    await safe_answer(call, t("⬜️ Tumanlar filtri tozalandi", user_script))

# ==================== V3 ORDER CLAIM HANDLER (STAGE 4) ====================

@router.callback_query(F.data.startswith("claim_order_"))
async def claim_order_call(call: CallbackQuery):
    user_id = call.from_user.id
    order_id = call.data.replace("claim_order_", "")
    user = await db.get_user(user_id)
    _, is_vip = check_subscription(user.get("subscription_expiry") if user else None)
    if not is_vip:
        await safe_answer(call, "⚠️ Buyurtmani qabul qilish uchun VIP obuna kerak!", show_alert=True)
        return

    await safe_answer(call, "✅ Buyurtma qabul qilindi! Mijoz bilan zudlik bilan bog'laning.", show_alert=True)
    with contextlib.suppress(TelegramBadRequest):
        current_text = call.message.html_text or call.message.text or ""
        claimed_banner = "\n\n<b>✅ SIZ BU BUYURTMANI QABUL QILDINGIZ!</b>\n<i>Mijoz bilan bog'laning.</i>"
        if "SIZ BU BUYURTMANI QABUL QILDINGIZ" not in current_text:
            new_text = current_text + claimed_banner
            new_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Qabul qilingan", callback_data="noop")]
            ])
            await call.message.edit_text(new_text, reply_markup=new_kb, parse_mode="HTML")


# ==================== SUPERADMIN HARVESTER & PANEL HANDLERS ====================

async def render_admin_harvester_hub(message_or_call):
    from src.harvester.service import default_harvester_service
    if not default_harvester_service.is_connected() and default_harvester_service.is_session_available():
        await default_harvester_service.start()

    hb_status = default_harvester_service.get_status()
    is_online = hb_status["is_connected"]
    u_info = hb_status.get("user_info", {})
    
    h_stats = await db.get_harvester_stats()
    total_groups = h_stats.get("total_groups", 0)
    active_groups = h_stats.get("active_groups", 0)
    total_orders = h_stats.get("total_orders", 0)
    today_orders = h_stats.get("today_orders", 0)
    passenger_orders = h_stats.get("passenger_orders", 0)
    cargo_orders = h_stats.get("cargo_orders", 0)

    if is_online:
        u_name = html.escape(str(u_info.get("username") or u_info.get("phone") or "Ulangan"))
        status_line = f"🟢 <b>FAOL</b> (<code>{u_name}</code>, ID: <code>{u_info.get('id')}</code>)"
    else:
        status_line = "🔴 <b>ULANMAGAN</b>\n<i>(Userbot sessiyasi ulanmagan)</i>"

    text = (
        "📡 <b>Harvester Radar — Boshqaruv Markazi</b>\n\n"
        f"🤖 <b>Userbot Tinglovchi Holati:</b>\n{status_line}\n\n"
        "📊 <b>Monitoring Ko'rsatkichlari:</b>\n"
        f"• 👥 Faol guruhlar: <b>{active_groups} ta</b> / {total_groups} ta jami\n"
        f"• ⚡️ Bugungi buyurtmalar: <b>{today_orders} ta</b>\n"
        f"• 📦 Jami buyurtmalar: <b>{total_orders} ta</b> ({passenger_orders} odam / {cargo_orders} pochta)\n"
        f"• ⚡️ NLP tahlil tezligi: <b>&lt; 0.05 ms</b> (sub-millisekund)\n\n"
        "Quyidagi amallardan birini tanlang:"
    )

    markup = kb.admin_harvester_hub_kb(userbot_online=is_online)

    if isinstance(message_or_call, Message):
        await message_or_call.answer(text, reply_markup=markup, parse_mode="HTML")
    else:
        with contextlib.suppress(TelegramBadRequest):
            await message_or_call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")

@router.callback_query(F.data == "admin_harvester")
async def admin_harvester_call(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await safe_answer(call, "Ruxsat yo'q!", show_alert=True)
        return
    await render_admin_harvester_hub(call)
    await safe_answer(call)

@router.message(Command("harvester"))
@router.message(Command("radar_admin"))
async def admin_harvester_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await render_admin_harvester_hub(message)

@router.callback_query(F.data == "admin_reload_groups")
async def admin_reload_groups_call(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    from src.harvester.service import default_harvester_service
    await default_harvester_service.reload_groups()
    await safe_answer(call, "🔄 Guruhlar ro'yxati va ko'rsatkichlar yangilandi!", show_alert=False)
    await render_admin_harvester_hub(call)

@router.callback_query(F.data == "admin_groups_list")
async def admin_groups_list_call(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    await safe_answer(call)
    groups = await db.get_harvester_groups(active_only=False)
    if not groups:
        text = (
            "📋 <b>Monitoring Guruhlari Ro'yxati</b>\n\n"
            "Hozircha birorta ham monitoring guruhi qo'shilmagan.\n"
            "«➕ Guruh qo'shish» tugmasi orqali yangi superguruh qo'shing."
        )
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Guruh qo'shish", callback_data="admin_add_group")],
            [
                InlineKeyboardButton(text="🔄 Yangilash", callback_data="admin_groups_list"),
                InlineKeyboardButton(text="« Harvester panel", callback_data="admin_harvester")
            ]
        ])
        with contextlib.suppress(TelegramBadRequest):
            await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
        return

    text = f"📋 <b>Monitoring Guruhlari ({len(groups)} ta):</b>\n\nQuyida Harvester tinglayotgan guruhlar keltirilgan. Guruhni vaqtincha to'xtatish (Pauza) yoki o'chirish mumkin:"
    markup = kb.admin_groups_list_kb(groups, page=0)
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")

@router.callback_query(F.data == "noop")
async def noop_call(call: CallbackQuery):
    await safe_answer(call)

@router.callback_query(F.data.startswith("group_info_"))
async def group_info_call(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    gid = int(call.data.replace("group_info_", ""))
    groups = await db.get_harvester_groups(active_only=False)
    g = next((x for x in groups if x["group_id"] == gid), None)
    if not g:
        await safe_answer(call, "Guruh topilmadi!", show_alert=True)
        return

    tag = g.get("region_tag", "andijon")
    from src.harvester.geo_tagger import parse_tag_string, format_tag_display
    reg, dist = parse_tag_string(tag)
    tag_display = format_tag_display(reg, dist)

    is_act = bool(g.get("is_active", True))
    status_str = "🟢 Faol (Tinglanmoqda)" if is_act else "⏸ To'xtatilgan (Pauza)"
    toggle_action = "0" if is_act else "1"
    toggle_label = "⏸ Pauza qilish" if is_act else "🟢 Faollashtirish"

    text = (
        f"📌 <b>Guruh Ma'lumotlari</b>\n\n"
        f"<b>Nomi:</b> {html.escape(g.get('title') or str(gid))}\n"
        f"<b>ID:</b> <code>{gid}</code>\n"
        f"<b>Username:</b> {g.get('username') or 'Mavjud emas'}\n"
        f"<b>📍 Hudud tegi:</b> <b>{tag_display}</b>\n"
        f"<b>Holati:</b> {status_str}\n"
        f"<b>Jami ushlangan:</b> {g.get('total_harvested', 0)} ta e'lon\n\n"
        "<i>E'lonlarda shahar ko'rsatilmaganda ushbu hudud tegi asos qilib olinadi.</i>"
    )

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✏️ Hudud tegi: {tag_display} (O'zgartirish)", callback_data=f"change_group_tag_{gid}")],
        [
            InlineKeyboardButton(text=toggle_label, callback_data=f"group_toggle_{gid}_{toggle_action}"),
            InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"group_del_{gid}")
        ],
        [InlineKeyboardButton(text="« Guruhlar ro'yxatiga qaytish", callback_data="admin_groups_list")]
    ])
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    await safe_answer(call)

@router.callback_query(F.data.startswith("change_group_tag_"))
async def admin_change_group_tag_call(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    gid = int(call.data.replace("change_group_tag_", ""))
    g = await db.get_harvester_group(gid)
    if not g:
        await safe_answer(call, "Guruh topilmadi!", show_alert=True)
        return
    current_tag = g.get("region_tag", "andijon")
    from src.harvester.geo_tagger import parse_tag_string, format_tag_display
    reg, dist = parse_tag_string(current_tag)
    tag_display = format_tag_display(reg, dist)

    markup = kb.admin_group_tag_picker_kb(gid, current_tag=current_tag)
    text = (
        f"📍 <b>Guruh hudud tegini tanlang:</b>\n\n"
        f"📌 <b>Guruh:</b> {html.escape(g.get('title') or str(gid))}\n"
        f"🔹 <b>Hozirgi teg:</b> <b>{tag_display}</b> (<code>{current_tag}</code>)\n\n"
        "<i>Ushbu guruhdagi e'lonlarda qaysi shahar/tuman aytilmagan bo'lsa, tanlangan hudud avtomatik qo'llaniladi.</i>"
    )
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    await safe_answer(call)

@router.callback_query(F.data.startswith("set_group_tag_"))
async def admin_set_group_tag_call(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    data_str = call.data.replace("set_group_tag_", "")
    parts = data_str.split("_", 1)
    if len(parts) < 2:
        return
    gid = int(parts[0])
    new_tag = parts[1]

    await db.update_harvester_group_tag(gid, new_tag)
    from src.harvester.service import default_harvester_service
    await default_harvester_service.reload_groups()

    from src.harvester.geo_tagger import parse_tag_string, format_tag_display
    reg, dist = parse_tag_string(new_tag)
    tag_display = format_tag_display(reg, dist)

    await safe_answer(call, f"Hudud tegi o'rnatildi: {tag_display}!", show_alert=True)

    groups = await db.get_harvester_groups(active_only=False)
    g = next((x for x in groups if x["group_id"] == gid), None)
    if g:
        is_act = bool(g.get("is_active", True))
        status_str = "🟢 Faol (Tinglanmoqda)" if is_act else "⏸ To'xtatilgan (Pauza)"
        toggle_action = "0" if is_act else "1"
        toggle_label = "⏸ Pauza qilish" if is_act else "🟢 Faollashtirish"
        text = (
            f"📌 <b>Guruh Ma'lumotlari</b>\n\n"
            f"<b>Nomi:</b> {html.escape(g.get('title') or str(gid))}\n"
            f"<b>ID:</b> <code>{gid}</code>\n"
            f"<b>Username:</b> {g.get('username') or 'Mavjud emas'}\n"
            f"<b>📍 Hudud tegi:</b> <b>{tag_display}</b>\n"
            f"<b>Holati:</b> {status_str}\n"
            f"<b>Jami ushlangan:</b> {g.get('total_harvested', 0)} ta e'lon\n\n"
            "<i>E'lonlarda shahar ko'rsatilmaganda ushbu hudud tegi asos qilib olinadi.</i>"
        )
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"✏️ Hudud tegi: {tag_display} (O'zgartirish)", callback_data=f"change_group_tag_{gid}")],
            [
                InlineKeyboardButton(text=toggle_label, callback_data=f"group_toggle_{gid}_{toggle_action}"),
                InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"group_del_{gid}")
            ],
            [InlineKeyboardButton(text="« Guruhlar ro'yxatiga qaytish", callback_data="admin_groups_list")]
        ])
        with contextlib.suppress(TelegramBadRequest):
            await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")

@router.message(Command("groups"))
@router.message(Command("harvester_groups"))
async def admin_groups_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    groups = await db.get_harvester_groups(active_only=False)
    if not groups:
        await message.answer(
            "📋 <b>Monitoring Guruhlari:</b>\n"
            "Hozircha birorta ham monitoring guruhi yo'q.\n"
            "Qo'shish: <code>/add_group @username</code>",
            reply_markup=kb.admin_return_kb(),
            parse_mode="HTML"
        )
        return
    text = f"📋 <b>Monitoring Guruhlari ({len(groups)} ta):</b>\nBoshqarish uchun tugmalardan foydalaning:"
    markup = kb.admin_groups_list_kb(groups, page=0)
    await message.answer(text, reply_markup=markup, parse_mode="HTML")

@router.callback_query(F.data.startswith("admin_groups_p_"))
async def admin_groups_page_call(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    await safe_answer(call)
    page = int(call.data.replace("admin_groups_p_", ""))
    groups = await db.get_harvester_groups(active_only=False)
    text = f"📋 <b>Monitoring Guruhlari ({len(groups)} ta):</b>"
    markup = kb.admin_groups_list_kb(groups, page=page)
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")

@router.callback_query(F.data.startswith("group_toggle_"))
async def group_toggle_call(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    parts = call.data.split("_")
    gid = int(parts[2])
    new_state = bool(int(parts[3]))
    await db.toggle_harvester_group(gid, new_state)
    from src.harvester.service import default_harvester_service
    await default_harvester_service.reload_groups()
    
    state_msg = "yoqildi" if new_state else "to'xtatildi"
    await safe_answer(call, f"Guruh holati {state_msg}!")
    
    groups = await db.get_harvester_groups(active_only=False)
    markup = kb.admin_groups_list_kb(groups, page=0)
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_reply_markup(reply_markup=markup)

@router.callback_query(F.data.startswith("group_del_"))
async def group_del_call(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    gid = int(call.data.replace("group_del_", ""))
    await db.delete_harvester_group(gid)
    from src.harvester.service import default_harvester_service
    await default_harvester_service.reload_groups()
    await safe_answer(call, "Guruh o'chirildi!", show_alert=True)
    
    groups = await db.get_harvester_groups(active_only=False)
    if groups:
        markup = kb.admin_groups_list_kb(groups, page=0)
        with contextlib.suppress(TelegramBadRequest):
            await call.message.edit_reply_markup(reply_markup=markup)
    else:
        await render_admin_harvester_hub(call)

@router.callback_query(F.data == "admin_add_group")
async def admin_add_group_call(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    await safe_answer(call)
    await state.set_state(AdminStates.waiting_for_group_target)
    text = (
        "➕ <b>Monitoring Guruhini Qo'shish</b>\n\n"
        "Guruh username, havola yoki ID sini yuboring:\n"
        "• <i>Misol:</i> <code>@vodiy_pitak_taxi</code>\n"
        "• <i>Havola:</i> <code>https://t.me/vodiy_pitak_taxi</code> yoki <code>https://t.me/+AbCdEf...</code>\n"
        "• <i>ID:</i> <code>-1001234567890</code>\n"
        "• Yoki guruhdan biror xabarni ushbu botga uzating (forward qiling).\n\n"
        "❌ Bekor qilish uchun: /cancel"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin_harvester")]
    ])
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")

@router.message(AdminStates.waiting_for_group_target)
async def admin_group_target_received(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    target_text = ""
    group_title = None
    if message.forward_from_chat:
        target_text = str(message.forward_from_chat.id)
        group_title = message.forward_from_chat.title
    elif message.text:
        target_text = message.text.strip()
    elif message.caption:
        target_text = message.caption.strip()

    if not target_text or target_text == "/cancel":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=kb.admin_return_kb())
        await render_admin_harvester_hub(message)
        return

    wait_msg = await message.answer(f"⏳ <code>{html.escape(target_text)}</code> tekshirilmoqda va Telegramdan ma'lumotlar olinmoqda...", parse_mode="HTML")
    from src.harvester.service import default_harvester_service
    res = await default_harvester_service.resolve_and_join_group(target_text, fallback_title=group_title)

    await state.clear()
    with contextlib.suppress(Exception):
        await wait_msg.delete()

    is_online = default_harvester_service.is_connected()
    if res.get("success"):
        gid = res.get("group_id")
        tag = res.get("region_tag", "andijon")
        from src.harvester.geo_tagger import parse_tag_string, format_tag_display
        reg, dist = parse_tag_string(tag)
        tag_display = format_tag_display(reg, dist)

        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"✏️ Hudud tegi: {tag_display} (O'zgartirish)", callback_data=f"change_group_tag_{gid}")],
            [InlineKeyboardButton(text="📋 Guruhlar ro'yxati", callback_data="admin_groups_list")],
            [InlineKeyboardButton(text="« Harvester panel", callback_data="admin_harvester")]
        ])
        await message.answer(
            f"✅ <b>Guruh monitoringga muvaffaqiyatli qo'shildi!</b>\n\n"
            f"📌 <b>Nomi:</b> {html.escape(str(res.get('title')))}\n"
            f"🆔 <b>ID:</b> <code>{gid}</code>\n"
            f"🔗 <b>Username:</b> {res.get('username') or 'Mavjud emas'}\n"
            f"📍 <b>Hudud tegi:</b> <b>{tag_display}</b>\n\n"
            "📡 Ushbu guruhdagi barcha yangi e'lonlar real vaqtda tahlil qilinadi!",
            reply_markup=markup,
            parse_mode="HTML"
        )
    else:
        err_msg = res.get("error") or "Guruhni qo'shib bo'lmadi"
        await message.answer(
            f"❌ <b>Xatolik:</b> {html.escape(str(err_msg))}\n\n"
            "Iltimos, guruh username yoki havolasi to'g'riligini tekshiring.",
            reply_markup=kb.admin_harvester_hub_kb(userbot_online=is_online),
            parse_mode="HTML"
        )

@router.message(Command("add_group"))
async def admin_add_group_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.strip().split()
    if len(parts) < 2:
        await message.answer(
            "⚠️ <b>Format:</b> <code>/add_group &lt;@username | havola | ID&gt;</code>\n"
            "Misol: <code>/add_group @vodiy_pitak_taxi</code>",
            reply_markup=kb.admin_return_kb(),
            parse_mode="HTML"
        )
        return
    target = parts[1]
    wait_msg = await message.answer(f"⏳ <code>{html.escape(target)}</code> tekshirilmoqda...", parse_mode="HTML")
    from src.harvester.service import default_harvester_service
    res = await default_harvester_service.resolve_and_join_group(target)
    with contextlib.suppress(Exception):
        await wait_msg.delete()

    if res.get("success"):
        gid = res.get("group_id")
        tag = res.get("region_tag", "andijon")
        from src.harvester.geo_tagger import parse_tag_string, format_tag_display
        reg, dist = parse_tag_string(tag)
        tag_display = format_tag_display(reg, dist)
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"✏️ Hudud tegi: {tag_display} (O'zgartirish)", callback_data=f"change_group_tag_{gid}")],
            [InlineKeyboardButton(text="📋 Guruhlar ro'yxati", callback_data="admin_groups_list")],
            [InlineKeyboardButton(text="« Harvester panel", callback_data="admin_harvester")]
        ])
        await message.answer(
            f"✅ <b>Guruh qo'shildi:</b> <b>{html.escape(str(res.get('title')))}</b> (ID: <code>{gid}</code>)\n"
            f"📍 <b>Hudud tegi:</b> <b>{tag_display}</b>",
            reply_markup=markup,
            parse_mode="HTML"
        )
    else:
        await message.answer(f"❌ <b>Xatolik:</b> {html.escape(str(res.get('error')))}", reply_markup=kb.admin_return_kb(), parse_mode="HTML")

@router.message(Command("del_group"))
async def admin_del_group_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.strip().split()
    if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
        await message.answer("⚠️ <b>Format:</b> <code>/del_group &lt;guruh_id&gt;</code>", reply_markup=kb.admin_return_kb(), parse_mode="HTML")
        return
    gid = int(parts[1])
    await db.delete_harvester_group(gid)
    from src.harvester.service import default_harvester_service
    await default_harvester_service.reload_groups()
    await message.answer(f"✅ Guruh (ID: <code>{gid}</code>) monitoringdan o'chirildi.", reply_markup=kb.admin_harvester_hub_kb(userbot_online=default_harvester_service.is_connected()), parse_mode="HTML")

@router.callback_query(F.data == "admin_recent_orders")
async def admin_recent_orders_call(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    await safe_answer(call)
    orders = await db.get_recent_harvested_orders(limit=10)
    if not orders:
        text = (
            "📥 <b>Oxirgi Buyurtmalar Ro'yxati</b>\n\n"
            "Hozircha guruhlardan birorta ham buyurtma tutib olinmagan.\n"
            "Monitoring guruhlariga yangi e'lonlar tushishi bilan bu yerda real vaqtda ko'rinadi."
        )
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Yangilash", callback_data="admin_recent_orders")],
            [InlineKeyboardButton(text="« Harvester panel", callback_data="admin_harvester")]
        ])
        with contextlib.suppress(TelegramBadRequest):
            await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
        return

    text = "📥 <b>Oxirgi 10 ta Tutib Olingan Buyurtma:</b>\n\n"
    for o in orders:
        o_type = "👤 Yo'lovchi" if o.get("order_type") == "PASSENGER" else "📦 Pochta"
        phone = o.get("phone_number") or "Tel yo'q"
        orig = o.get("origin_district") or "?"
        dest = o.get("dest_district") or "?"
        text += (
            f"• <b>#{o['id']} ({o_type})</b> <code>{html.escape(orig)}</code> ➡️ <code>{html.escape(dest)}</code>\n"
            f"  📞 {html.escape(phone)} | 👥 {o.get('passenger_count', 1)} ta | ⏱ {o.get('created_at')}\n"
        )

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Yangilash", callback_data="admin_recent_orders")],
        [InlineKeyboardButton(text="« Harvester panel", callback_data="admin_harvester")]
    ])
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
