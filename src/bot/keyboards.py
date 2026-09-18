import math
from typing import List, Dict, Any, Optional
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove
)

# ==================== MAIN USER DASHBOARD ====================
def main_dashboard_kb(is_authenticated: bool, is_running: bool, drop_author: bool) -> InlineKeyboardMarkup:
    keyboard = []
    
    if not is_authenticated:
        keyboard.append([
            InlineKeyboardButton(text="📱 Telegram akkauntni ulash", callback_data="start_auth")
        ])
        keyboard.append([
            InlineKeyboardButton(text="💳 Tariflar va To'lov", callback_data="show_plans"),
            InlineKeyboardButton(text="ℹ️ Qo'llanma", callback_data="help_info")
        ])
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
        
    # Authenticated user dashboard
    state_btn = InlineKeyboardButton(
        text="⏸ To'xtatish (Pauza)" if is_running else "▶️ Boshlash (Aktiv)",
        callback_data="toggle_state"
    )
    forward_mode_btn = InlineKeyboardButton(
        text="🔄 Rejim: Toza post (Muallifsiz)" if drop_author else "🔄 Rejim: Asl nusxa (Forwarded)",
        callback_data="toggle_drop_author"
    )
    
    keyboard.append([state_btn])
    keyboard.append([InlineKeyboardButton(text="📥 Manba guruhni sozlash", callback_data="set_source_chat")])
    keyboard.append([
        InlineKeyboardButton(text="⏱ Doira vaqti", callback_data="adjust_timing"),
        InlineKeyboardButton(text="⚡️ Yuborish tezligi", callback_data="adjust_jitter")
    ])
    keyboard.append([InlineKeyboardButton(text="👥 Guruhlarni boshqarish", callback_data="manage_groups")])
    keyboard.append([forward_mode_btn])
    keyboard.append([InlineKeyboardButton(text="🧪 Sinov yuborish (Test)", callback_data="trigger_test")])
    keyboard.append([
        InlineKeyboardButton(text="💳 Obunani uzaytirish", callback_data="show_plans"),
        InlineKeyboardButton(text="🔌 Akkauntni uzish", callback_data="logout_confirm")
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# ==================== AUTH KEYBOARDS ====================
def phone_request_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Telefon raqamni yuborish", request_contact=True)],
            [KeyboardButton(text="❌ Bekor qilish")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )

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
def pricing_plans_kb(is_lifetime_discount: bool = True) -> InlineKeyboardMarkup:
    # 1m (25k), 3m (65k), 6m (120k), 12m (225k UZS)
    keyboard = [
        [InlineKeyboardButton(text="1️⃣ 1 Oy — 25,000 so'm (38% chegirma)", callback_data="buy_plan_1")],
        [InlineKeyboardButton(text="2️⃣ 3 Oy — 65,000 so'm (-10% qo'shimcha)", callback_data="buy_plan_3")],
        [InlineKeyboardButton(text="3️⃣ 6 Oy — 120,000 so'm (-20% qo'shimcha)", callback_data="buy_plan_6")],
        [InlineKeyboardButton(text="4️⃣ 12 Oy + 1 Oy Bepul — 225,000 so'm 🔥", callback_data="buy_plan_12")],
        [InlineKeyboardButton(text="« Asosiy menyu", callback_data="back_dashboard")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

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

def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« Asosiy menyu", callback_data="back_dashboard")]
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

