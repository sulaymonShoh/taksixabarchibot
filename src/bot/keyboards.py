from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import List, Dict, Any
import math

def main_dashboard_kb(is_running: bool, drop_author: bool) -> InlineKeyboardMarkup:
    state_btn = InlineKeyboardButton(
        text="⏸ To'xtatish (Pauza)" if is_running else "▶️ Boshlash (Aktiv)",
        callback_data="toggle_state"
    )
    forward_mode_btn = InlineKeyboardButton(
        text="🔄 Rejim: Toza post (Muallifsiz)" if drop_author else "🔄 Rejim: Asl nusxa (Forwarded)",
        callback_data="toggle_drop_author"
    )
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [state_btn],
        [InlineKeyboardButton(text="📥 Manba guruhni sozlash", callback_data="set_source_chat")],
        [
            InlineKeyboardButton(text="⏱ Doira vaqti", callback_data="adjust_timing"),
            InlineKeyboardButton(text="⚡️ Yuborish tezligi", callback_data="adjust_jitter")
        ],
        [InlineKeyboardButton(text="👥 Guruhlarni boshqarish", callback_data="manage_groups")],
        [forward_mode_btn],
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
