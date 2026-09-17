from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import List, Dict, Any
import math

def main_dashboard_kb(is_running: bool, auto_cleanup: bool) -> InlineKeyboardMarkup:
    state_btn = InlineKeyboardButton(
        text="⏸ To'xtatish (Pauza)" if is_running else "▶️ Boshlash (Aktiv)",
        callback_data="toggle_state"
    )
    cleanup_btn = InlineKeyboardButton(
        text="🧹 Avto-tozalash: YOQILGAN" if auto_cleanup else "🧹 Avto-tozalash: O'CHIRILGAN",
        callback_data="toggle_cleanup"
    )
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [state_btn],
        [
            InlineKeyboardButton(text="👁 Xabarni ko'rish", callback_data="preview_message"),
            InlineKeyboardButton(text="📝 Xabarni tahrirlash", callback_data="edit_message")
        ],
        [
            InlineKeyboardButton(text="⏱ Vaqt oralig'i", callback_data="adjust_timing"),
            InlineKeyboardButton(text="👥 Guruhlarni boshqarish", callback_data="manage_groups")
        ],
        [cleanup_btn],
        [InlineKeyboardButton(text="🧪 Sinov yuborish (Test)", callback_data="trigger_test")]
    ])

def timing_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡️ 1 daqiqa (60 - 90 soniya)", callback_data="time_preset_1min")],
        [InlineKeyboardButton(text="🚀 Tez (3 - 5 daqiqa)", callback_data="time_preset_fast")],
        [InlineKeyboardButton(text="⚖️ O'rtacha (5 - 10 daqiqa)", callback_data="time_preset_med")],
        [InlineKeyboardButton(text="☕️ Sekin (10 - 15 daqiqa)", callback_data="time_preset_relax")],
        [InlineKeyboardButton(text="✍️ O'zingiz kiritish", callback_data="time_custom")],
        [InlineKeyboardButton(text="« Asosiy menyu", callback_data="back_dashboard")]
    ])

def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« Asosiy menyu", callback_data="back_dashboard")]
    ])

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
        # Truncate title if too long
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
