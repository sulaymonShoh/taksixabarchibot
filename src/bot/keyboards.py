import math
from typing import List, Dict, Any, Optional
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove
)

from src.bot.translit import t

# ==================== MAIN USER DASHBOARD ====================
def main_dashboard_kb(
    is_authenticated: bool,
    is_running: bool = False,
    drop_author: bool = False,
    script: str = "lat",
    can_claim_trial: bool = False
) -> InlineKeyboardMarkup:
    """
    Streamlined Main Dashboard Keyboard:
    - 🎁 24 soat bepul sinab ko'rish (if eligible)
    - 🎯 Buyurtmalar
    - 📢 E'lon tarqatish
    - 💳 Obunani boshqarish / 🔌 Akkauntni uzish
    - 🌐 Alifbo: Lotin / Кирилл
    """
    radar_title = t("🎯 Buyurtmalar", script)
    sender_title = t("📢 E'lon tarqatish", script)
    sub_title = t("💳 Obunani boshqarish", script)
    
    if is_authenticated:
        auth_btn = InlineKeyboardButton(text=t("🔌 Akkauntni uzish", script), callback_data="logout_confirm")
    else:
        auth_btn = InlineKeyboardButton(text=t("📱 Akkauntni ulash", script), callback_data="start_auth")

    lang_text = "🌐 Алифбо: Кирилл 🇺🇿" if script == "cyr" else "🌐 Alifbo: Lotin 🇺🇿"

    keyboard = []
    if can_claim_trial:
        keyboard.append([
            InlineKeyboardButton(text=t("🎁 24 soat bepul sinab ko'rish", script), callback_data="claim_trial")
        ])

    keyboard.extend([
        [InlineKeyboardButton(text=radar_title, callback_data="radar_menu")],
        [InlineKeyboardButton(text=sender_title, callback_data="sender_menu")],
        [
            InlineKeyboardButton(text=sub_title, callback_data="show_plans"),
            auth_btn
        ],
        [InlineKeyboardButton(text=lang_text, callback_data="toggle_script")]
    ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def sender_menu_kb(
    is_authenticated: bool,
    is_running: bool = False,
    drop_author: bool = False,
    script: str = "lat"
) -> InlineKeyboardMarkup:
    """Dedicated menu for automated broadcasting/message sender controls."""
    keyboard = []
    
    if not is_authenticated:
        keyboard.append([
            InlineKeyboardButton(text=t("📱 Telegram akkauntni ulash", script), callback_data="start_auth")
        ])
        keyboard.append([
            InlineKeyboardButton(text=t("« Asosiy menyu", script), callback_data="back_dashboard")
        ])
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
        
    state_btn = InlineKeyboardButton(
        text=t("⏸ To'xtatish (Pauza)", script) if is_running else t("▶️ Boshlash (Aktiv)", script),
        callback_data="toggle_state"
    )
    forward_mode_btn = InlineKeyboardButton(
        text=t("🔄 Rejim: Toza post (Muallifsiz)", script) if drop_author else t("🔄 Rejim: Asl nusxa (Forwarded)", script),
        callback_data="toggle_drop_author"
    )
    
    keyboard.append([state_btn])
    keyboard.append([InlineKeyboardButton(text=t("📥 Manba guruhni sozlash", script), callback_data="set_source_chat")])
    keyboard.append([
        InlineKeyboardButton(text=t("⏱ Doira vaqti", script), callback_data="adjust_timing"),
        InlineKeyboardButton(text=t("⚡️ Yuborish tezligi", script), callback_data="adjust_jitter")
    ])
    keyboard.append([InlineKeyboardButton(text=t("👥 Guruhlarni boshqarish", script), callback_data="manage_groups")])
    keyboard.append([forward_mode_btn])
    keyboard.append([InlineKeyboardButton(text=t("🧪 Sinov yuborish (Test)", script), callback_data="trigger_test")])
    keyboard.append([InlineKeyboardButton(text=t("« Asosiy menyu", script), callback_data="back_dashboard")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# ==================== PERSISTENT REPLY KEYBOARDS (INPUT ROW) ====================
def main_reply_kb(script: str = "lat") -> ReplyKeyboardMarkup:
    """Persistent reply keyboard for authenticated users: User manual & Admin support."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=t("📖 Foydalanish qo'llanmasi", script)),
                KeyboardButton(text=t("✍️ Adminga yozish", script))
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )

def unauth_reply_kb(script: str = "lat") -> ReplyKeyboardMarkup:
    """Persistent reply keyboard for unauthenticated / first-time users."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t("📱 Telefon raqamni yuborish", script), request_contact=True)],
            [KeyboardButton(text=t("❌ Bekor qilish", script))]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )

def phone_request_kb(script: str = "lat") -> ReplyKeyboardMarkup:
    """Alias for unauth_reply_kb for backward compatibility."""
    return unauth_reply_kb(script=script)

def cancel_auth_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_auth")]
    ])

def logout_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 Ha, akkauntni uzish", callback_data="logout_confirmed")],
        [InlineKeyboardButton(text="« Bekor qilish", callback_data="back_dashboard")]
    ])

# ==================== PRICING & SUBSCRIPTION ====================
def pricing_plans_kb(plan_details: Any = None, script: str = "lat", can_claim_trial: bool = False) -> InlineKeyboardMarkup:
    # Dynamic or default plans: 1m (25k), 3m (65k), 6m (120k), 12m (225k UZS)
    keyboard = []
    
    if can_claim_trial:
        keyboard.append([
            InlineKeyboardButton(text=t("🎁 24 soat bepul sinab ko'rish", script), callback_data="claim_trial")
        ])

    if isinstance(plan_details, dict):
        for months in [1, 3, 6, 12]:
            info = plan_details.get(months)
            if info:
                title = info.get("title", f"{months} Oy")
                price = info.get("price", 25000)
                tag = info.get("tag", "")
                tag_str = f" ({tag})" if tag else ""
                icon = {1: "1️⃣", 3: "2️⃣", 6: "3️⃣", 12: "4️⃣"}.get(months, "📦")
                btn_text = f"{icon} {title} — {price:,} so'm{tag_str}"
                keyboard.append([InlineKeyboardButton(text=btn_text, callback_data=f"buy_plan_{months}")])
    else:
        keyboard.extend([
            [InlineKeyboardButton(text="1️⃣ 1 Oy — 25,000 so'm (38% chegirma)", callback_data="buy_plan_1")],
            [InlineKeyboardButton(text="2️⃣ 3 Oy — 65,000 so'm (-10% qo'shimcha)", callback_data="buy_plan_3")],
            [InlineKeyboardButton(text="3️⃣ 6 Oy — 120,000 so'm (-20% qo'shimcha)", callback_data="buy_plan_6")],
            [InlineKeyboardButton(text="4️⃣ 12 Oy + 1 Oy Bepul — 225,000 so'm 🔥", callback_data="buy_plan_12")]
        ])
        
    keyboard.append([InlineKeyboardButton(text=t("🎟 Promokod kiritish", script), callback_data="enter_promocode")])
    keyboard.append([InlineKeyboardButton(text=t("« Asosiy menyu", script), callback_data="back_dashboard")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def cancel_promo_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« Bekor qilish va orqaga", callback_data="show_plans")]
    ])

def cancel_payment_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« Bekor qilish va qaytish", callback_data="show_plans")]
    ])

# ==================== 1-TAP ADMIN APPROVAL KEYBOARD ====================
def admin_payment_approval_kb(request_id: int, user_id: int, plan_months: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"✅ Tasdiqlash (+{plan_months} oy)", callback_data=f"pay_app_{request_id}_{user_id}_{plan_months}"),
            InlineKeyboardButton(text="❌ Rad etish", callback_data=f"pay_rej_{request_id}_{user_id}")
        ]
    ])

# ==================== TIMING & JITTER CONFIGURATION ====================
def timing_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡️ 1 daqiqa (60 - 90 soniya)", callback_data="time_preset_1min")],
        [InlineKeyboardButton(text="🚀 Tez (3 - 5 daqiqa)", callback_data="time_preset_fast")],
        [InlineKeyboardButton(text="⚖️ O'rtacha (5 - 10 daqiqa)", callback_data="time_preset_med")],
        [InlineKeyboardButton(text="☕️ Sekin (10 - 15 daqiqa)", callback_data="time_preset_relax")],
        [InlineKeyboardButton(text="✍️ O'zingiz kiritish", callback_data="time_custom")],
        [InlineKeyboardButton(text="« Asosiy menyu", callback_data="back_dashboard")]
    ])

def jitter_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡️ Tezkor (1.5s - 2.0s) [50 guruh ~1.5 daq]", callback_data="jitter_preset_fast")],
        [InlineKeyboardButton(text="⚖️ O'rtacha (2.0s - 4.0s)", callback_data="jitter_preset_med")],
        [InlineKeyboardButton(text="🛡 Xavfsiz (6.0s - 12.0s)", callback_data="jitter_preset_safe")],
        [InlineKeyboardButton(text="✍️ O'zingiz kiritish", callback_data="jitter_custom")],
        [InlineKeyboardButton(text="« Asosiy menyu", callback_data="back_dashboard")]
    ])

def back_kb(script: str = "lat") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t("« Asosiy menyu", script), callback_data="back_dashboard")]
    ])

# ==================== PAGINATED TARGET GROUPS ====================
def paginated_groups_kb(groups: List[Dict[str, Any]], page: int, per_page: int = 10) -> InlineKeyboardMarkup:
    total_pages = max(1, math.ceil(len(groups) / per_page))
    start_idx = page * per_page
    end_idx = start_idx + per_page
    
    current_groups = groups[start_idx:end_idx]
    keyboard = []
    
    # Bulk actions row
    keyboard.append([
        InlineKeyboardButton(text="✅ Barchasini yoqish", callback_data=f"bulk_groups_on_{page}"),
        InlineKeyboardButton(text="⬜️ Barchasini o'chirish", callback_data=f"bulk_groups_off_{page}")
    ])
    
    for g in current_groups:
        status_icon = "✅" if g.get('is_active') else "⬜️"
        title = g.get('title', 'Noma\'lum guruh')
        if len(title) > 28:
            title = title[:25] + "..."
            
        keyboard.append([
            InlineKeyboardButton(
                text=f"{status_icon} {title}",
                callback_data=f"toggle_group_{g['chat_id']}_{page}"
            )
        ])
        
    # Pagination controls
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="« Oldingi", callback_data=f"page_groups_{page-1}"))
    
    nav_buttons.append(InlineKeyboardButton(text=f"📄 {page+1}/{total_pages}", callback_data="noop"))

    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="Keyingi »", callback_data=f"page_groups_{page+1}"))
        
    keyboard.append(nav_buttons)
    keyboard.append([InlineKeyboardButton(text="« Asosiy menyu", callback_data="back_dashboard")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def forward_confirm_kb(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Guruhlar ro'yxatiga qo'shish", callback_data=f"add_group_{chat_id}")],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="dismiss")]
    ])

def delete_confirm_kb(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Ha, o'chirish", callback_data=f"confirm_delete_{chat_id}")],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="dismiss")]
    ])

# ==================== SUPERADMIN CONTROL PANEL ====================
def superadmin_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Umumiy Statistika", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🧾 Kutilayotgan Cheklar", callback_data="admin_pending_cheques")],
        [InlineKeyboardButton(text="📢 Ommaviy Xabar (Broadcast)", callback_data="admin_broadcast_msg")],
        [InlineKeyboardButton(text="« Asosiy menyu", callback_data="back_dashboard")]
    ])

# ==================== V3 DRIVER RADAR KEYBOARDS ====================
ANDIJON_RADAR_DISTRICTS = [
    ("asaka", "Asaka"),
    ("shahrixon", "Shahrixon"),
    ("boston", "Bo'ston (Bo'z)"),
    ("marhamat", "Marhamat"),
    ("andijon_shahar", "Andijon shahar"),
    ("oltinkol", "Oltinko'l"),
    ("xojaobod", "Xo'jaobod"),
    ("buloqboshi", "Buloqboshi"),
    ("qorgontepa", "Qo'rg'ontepa"),
    ("jalaquduq", "Jalaquduq"),
    ("paxtaobod", "Paxtaobod"),
    ("izboskan", "Izboskan"),
    ("baliqchi", "Baliqchi"),
    ("ulugnor", "Ulug'nor"),
    ("xonobod", "Xonobod"),
]

def radar_menu_kb(prefs: Dict[str, Any], is_vip: bool, script: str = "lat", can_claim_trial: bool = False) -> InlineKeyboardMarkup:
    is_active = bool(prefs.get("is_radar_active", True))
    direction = prefs.get("direction", "both")
    allow_passenger = bool(prefs.get("allow_passenger", True))
    allow_cargo = bool(prefs.get("allow_cargo", True))
    sound_alerts = bool(prefs.get("sound_alerts", True))
    selected_districts = prefs.get("selected_districts", [])
    district_count = len(selected_districts) if isinstance(selected_districts, list) else 0

    dir_labels = {
        "both": t("Toshkent ⇄ Andijon (Ikkala tomon)", script),
        "toshkent_to_andijon": t("Toshkent ➡️ Andijon", script),
        "andijon_to_toshkent": t("Andijon ➡️ Toshkent", script)
    }
    dir_text = dir_labels.get(direction, t("Toshkent ⇄ Andijon", script))

    status_text = t("🟢 Radar: YONIQ (Aktiv)", script) if is_active else t("🔴 Radar: O'CHIQ (Pauza)", script)
    sound_text = t("🔔 Bildirishnoma: Ovozli", script) if sound_alerts else t("🔕 Bildirishnoma: Tovushsiz", script)
    pass_icon = "✅" if allow_passenger else "⬜️"
    cargo_icon = "✅" if allow_cargo else "⬜️"

    keyboard = [
        [InlineKeyboardButton(text=status_text, callback_data="radar_toggle_state")],
        [InlineKeyboardButton(text=dir_text, callback_data="radar_toggle_dir")],
        [
            InlineKeyboardButton(text=f"{pass_icon} {t('Yo\'lovchilar', script)}", callback_data="radar_toggle_passenger"),
            InlineKeyboardButton(text=f"{cargo_icon} {t('Pochta / Yuk', script)}", callback_data="radar_toggle_cargo")
        ],
        [InlineKeyboardButton(text=t(f"📍 Tumanlar filtri ({district_count} ta tanlangan)", script), callback_data="radar_districts")],
        [InlineKeyboardButton(text=sound_text, callback_data="radar_toggle_sound")]
    ]

    if not is_vip:
        if can_claim_trial:
            keyboard.append([InlineKeyboardButton(text=t("🎁 24 soat bepul sinab ko'rish", script), callback_data="claim_trial")])
        keyboard.append([InlineKeyboardButton(text=t("⭐️ VIP Obunani faollashtirish", script), callback_data="show_plans")])

    keyboard.append([InlineKeyboardButton(text=t("« Asosiy menyu", script), callback_data="back_dashboard")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def radar_districts_kb(selected_districts: List[str], script: str = "lat") -> InlineKeyboardMarkup:
    selected_set = set(selected_districts or [])
    keyboard = []

    # 2 columns layout
    row = []
    for d_id, d_name in ANDIJON_RADAR_DISTRICTS:
        icon = "✅" if d_id in selected_set else "⬜️"
        row.append(InlineKeyboardButton(text=f"{icon} {t(d_name, script)}", callback_data=f"radar_district_{d_id}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    # Bulk actions row
    keyboard.append([
        InlineKeyboardButton(text=t("✅ Barchasini tanlash", script), callback_data="radar_districts_all"),
        InlineKeyboardButton(text=t("⬜️ Tozalash", script), callback_data="radar_districts_clear")
    ])
    keyboard.append([InlineKeyboardButton(text=t("« Radarga qaytish", script), callback_data="radar_menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# ==================== SUPERADMIN CONTROL PANEL KEYBOARDS ====================
def admin_main_dashboard_kb(userbot_online: bool = False, pending_cheques: int = 0) -> InlineKeyboardMarkup:
    """Main dashboard keyboard for SuperAdmin account."""
    hb_icon = "🟢" if userbot_online else "🔴"
    cheque_badge = f" ({pending_cheques} ta kutilmoqda)" if pending_cheques > 0 else ""
    
    keyboard = [
        [InlineKeyboardButton(text=f"📡 Harvester Radar ({hb_icon} Userbot)", callback_data="admin_harvester")],
        [
            InlineKeyboardButton(text="👥 Foydalanuvchilar", callback_data="admin_users"),
            InlineKeyboardButton(text=f"💰 Moliya & Cheklar{cheque_badge}", callback_data="admin_finance")
        ],
        [
            InlineKeyboardButton(text="💳 Tariflarni boshqarish", callback_data="admin_plans"),
            InlineKeyboardButton(text="🏷 Chegirma & Promolar", callback_data="admin_promos")
        ],
        [
            InlineKeyboardButton(text="📢 Xabarnoma yuborish", callback_data="admin_broadcast")
        ],
        [
            InlineKeyboardButton(text="🚗 Haydovchi rejimini ko'rish (Sinov)", callback_data="admin_driver_view")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def admin_harvester_hub_kb(userbot_online: bool = False) -> InlineKeyboardMarkup:
    """Control keyboard for Harvester Radar subsystem."""
    keyboard = [
        [
            InlineKeyboardButton(text="➕ Guruh qo'shish", callback_data="admin_add_group"),
            InlineKeyboardButton(text="📋 Guruhlar ro'yxati", callback_data="admin_groups_list")
        ],
        [
            InlineKeyboardButton(text="🔄 Guruhlarni qayta yuklash", callback_data="admin_reload_groups"),
            InlineKeyboardButton(text="📥 Oxirgi buyurtmalar", callback_data="admin_recent_orders")
        ],
        [InlineKeyboardButton(text="👑 Asosiy panelga qaytish", callback_data="admin_panel")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def admin_plans_kb(has_active_discount: bool = False) -> InlineKeyboardMarkup:
    """Keyboard for managing pricing plans and payment info."""
    buttons = [
        [
            InlineKeyboardButton(text="🏷 Chegirma aksiyasi (/setdiscount)", callback_data="admin_set_discount_info"),
            InlineKeyboardButton(text="🎟 Yangi promo (/newpromo)", callback_data="admin_new_promo_info")
        ]
    ]
    if has_active_discount:
        buttons.append([
            InlineKeyboardButton(text="🛑 Faol aksiyani to'xtatish", callback_data="admin_stop_discount")
        ])
    buttons.append([
        InlineKeyboardButton(text="👑 Asosiy panelga qaytish", callback_data="admin_panel")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_broadcast_kb(userbot_online: bool = False) -> InlineKeyboardMarkup:
    """Keyboard for broadcasting options."""
    hb_icon = "🟢" if userbot_online else "🔴"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Bot foydalanuvchilariga xabar", callback_data="admin_broadcast_users")],
        [InlineKeyboardButton(text=f"📡 Guruhlarga e'lon ({hb_icon} Userbot)", callback_data="admin_broadcast_groups")],
        [InlineKeyboardButton(text="👑 Asosiy panelga qaytish", callback_data="admin_panel")]
    ])

def admin_groups_list_kb(groups: List[Dict[str, Any]], page: int = 0, per_page: int = 5) -> InlineKeyboardMarkup:
    """Paginated inline keyboard displaying monitored groups with toggle/delete."""
    keyboard = []
    total_groups = len(groups)
    total_pages = max(1, math.ceil(total_groups / per_page))
    page = max(0, min(page, total_pages - 1))
    
    start_idx = page * per_page
    page_groups = groups[start_idx : start_idx + per_page]

    for g in page_groups:
        gid = g["group_id"]
        title = g.get("title") or str(gid)
        if len(title) > 20:
            title = title[:18] + ".."
        is_act = bool(g.get("is_active", True))
        status_icon = "🟢" if is_act else "⏸"
        toggle_action = "0" if is_act else "1"
        toggle_label = "Pauza" if is_act else "Yoqish"

        keyboard.append([
            InlineKeyboardButton(text=f"{status_icon} {title}", callback_data=f"group_info_{gid}"),
            InlineKeyboardButton(text=f"{toggle_label}", callback_data=f"group_toggle_{gid}_{toggle_action}"),
            InlineKeyboardButton(text="🗑", callback_data=f"group_del_{gid}")
        ])

    # Pagination navigation row
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ Oldingi", callback_data=f"admin_groups_p_{page-1}"))
    nav_row.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(text="Keyingi ➡️", callback_data=f"admin_groups_p_{page+1}"))
    
    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([
        InlineKeyboardButton(text="➕ Guruh qo'shish", callback_data="admin_add_group"),
        InlineKeyboardButton(text="« Harvester panel", callback_data="admin_harvester")
    ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def admin_return_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👑 Asosiy panelga qaytish", callback_data="admin_panel")]
    ])

def admin_group_tag_picker_kb(group_id: int, current_tag: Optional[str] = None) -> InlineKeyboardMarkup:
    """
    Inline keyboard for SuperAdmin to set or change a group's geographic context tag.
    Supports 1-tap district tags (Andijon districts) and other provinces.
    """
    tags = [
        ("📍 Andijon (Umumiy)", "andijon"),
        ("🔹 Asaka", "andijon:asaka"),
        ("🔹 Shahrixon", "andijon:shahrixon"),
        ("🔹 Bo'ston (Bo'z)", "andijon:boston"),
        ("🔹 Marhamat", "andijon:marhamat"),
        ("🔹 Andijon shahar", "andijon:andijon_shahar"),
        ("🔹 Oltinko'l", "andijon:oltinkol"),
        ("🔹 Qurg'ontepa", "andijon:qorgontepa"),
        ("🔹 Baliqchi", "andijon:baliqchi"),
        ("🔹 Paxtaobod", "andijon:paxtaobod"),
        ("🔹 Xo'jaobod", "andijon:xojaobod"),
        ("🔹 Buloqboshi", "andijon:buloqboshi"),
        ("🔹 Izboskan", "andijon:izboskan"),
        ("🔹 Jalolquduq", "andijon:jalolquduq"),
        ("🔹 Ulug'nor", "andijon:ulugnor"),
        ("🔹 Xonobod", "andijon:xonobod"),
        ("🌍 Farg'ona", "fargona"),
        ("🌍 Namangan", "namangan"),
        ("🌍 Toshkent", "toshkent"),
        ("🌍 Samarqand", "samarqand"),
        ("🌐 Barcha (ALL)", "ALL")
    ]
    
    keyboard = []
    row = []
    for label, tag_val in tags:
        display = f"✅ {label}" if current_tag == tag_val else label
        row.append(InlineKeyboardButton(text=display, callback_data=f"set_group_tag_{group_id}_{tag_val}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
        
    keyboard.append([
        InlineKeyboardButton(text="« Guruh ma'lumotlariga qaytish", callback_data=f"group_info_{group_id}")
    ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)




