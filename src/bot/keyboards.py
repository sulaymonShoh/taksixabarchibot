from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import List, Dict, Any
import math

def main_dashboard_kb(is_running: bool, auto_cleanup: bool) -> InlineKeyboardMarkup:
    state_btn = InlineKeyboardButton(
        text="⏸ Pause Broadcast" if is_running else "▶️ Resume Broadcast",
        callback_data="toggle_state"
    )
    cleanup_btn = InlineKeyboardButton(
        text="🧹 Auto-Delete: ON" if auto_cleanup else "🧹 Auto-Delete: OFF",
        callback_data="toggle_cleanup"
    )
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [state_btn],
        [InlineKeyboardButton(text="📝 Edit Message", callback_data="edit_message")],
        [InlineKeyboardButton(text="⏱ Adjust Timing", callback_data="adjust_timing")],
        [InlineKeyboardButton(text="👥 Manage Groups", callback_data="manage_groups")],
        [cleanup_btn],
        [InlineKeyboardButton(text="🧪 Trigger Test Round", callback_data="trigger_test")]
    ])

def timing_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Fast (3-5m)", callback_data="time_preset_fast")],
        [InlineKeyboardButton(text="Medium (5-10m)", callback_data="time_preset_med")],
        [InlineKeyboardButton(text="Relaxed (10-15m)", callback_data="time_preset_relax")],
        [InlineKeyboardButton(text="Custom Range", callback_data="time_custom")],
        [InlineKeyboardButton(text="« Back to Dashboard", callback_data="back_dashboard")]
    ])

def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« Back to Dashboard", callback_data="back_dashboard")]
    ])

def paginated_groups_kb(groups: List[Dict[str, Any]], page: int, per_page: int = 6) -> InlineKeyboardMarkup:
    total_pages = max(1, math.ceil(len(groups) / per_page))
    start_idx = page * per_page
    end_idx = start_idx + per_page
    
    current_groups = groups[start_idx:end_idx]
    
    keyboard = []
    for g in current_groups:
        status_icon = "✅" if g.get('is_active') else "⬜️"
        title = g.get('title', 'Unknown')
        # Truncate title if too long
        if len(title) > 25:
            title = title[:22] + "..."
            
        keyboard.append([
            InlineKeyboardButton(
                text=f"{status_icon} {title}",
                callback_data=f"toggle_group_{g['chat_id']}_{page}"
            )
        ])
        
    # Pagination controls
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="« Prev", callback_data=f"page_groups_{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="Next »", callback_data=f"page_groups_{page+1}"))
        
    if nav_buttons:
        keyboard.append(nav_buttons)
        
    keyboard.append([InlineKeyboardButton(text="« Back to Dashboard", callback_data="back_dashboard")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def forward_confirm_kb(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Add to Active List", callback_data=f"add_group_{chat_id}")],
        [InlineKeyboardButton(text="❌ Dismiss", callback_data="dismiss")]
    ])
