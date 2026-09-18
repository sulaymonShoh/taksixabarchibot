import os
import contextlib
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest

from src import database as db
from src.bot import keyboards as kb
from src.logger import setup_logger

logger = setup_logger("handlers")
router = Router()

class BotStates(StatesGroup):
    waiting_for_source_chat = State()
    waiting_for_custom_timing = State()
    waiting_for_custom_jitter = State()

async def safe_answer(call: CallbackQuery, text: str = None, show_alert: bool = False):
    """Safely answer callback queries ignoring timeout/invalid query errors."""
    with contextlib.suppress(TelegramBadRequest):
        await call.answer(text=text, show_alert=show_alert)

async def render_dashboard(message_or_call, state: FSMContext = None):
    if state:
        await state.clear()
        
    is_running = await db.get_setting("is_running", False)
    source_chat_id = await db.get_setting("source_chat_id", None)
    source_chat_title = await db.get_setting("source_chat_title", "O'rnatilmagan")
    drop_author = await db.get_setting("drop_author", False)
    
    cycle_min = await db.get_setting("cycle_min", 60)
    cycle_max = await db.get_setting("cycle_max", 90)
    jitter_min = await db.get_setting("jitter_min", 1.5)
    jitter_max = await db.get_setting("jitter_max", 2.0)
    
    groups = await db.get_all_groups()
    active_groups = len([g for g in groups if g['is_active']])
    total_groups = len(groups)
    
    source_display = f"📢 **{source_chat_title}**" if source_chat_id else "⚠️ **O'rnatilmagan (Ulash zarur!)**"
    forward_mode_text = "Toza post (Muallifsiz / Original)" if drop_author else "Asl nusxa (Forwarded from...)"
    
    # Calculate estimated round duration
    est_seconds = active_groups * ((float(jitter_min) + float(jitter_max)) / 2)
    est_minutes = est_seconds / 60
    
    text = (
        "🎛 **Xabarlar Tarqatish Boshqaruv Paneli**\n\n"
        f"**Holat:** {'🟢 FAOL (Ishlayapti)' if is_running else '🔴 TO\'XTATILGAN (Pauza)'}\n"
        f"**📥 Manba guruh:** {source_display}\n"
        f"**🔄 Forward rejimi:** {forward_mode_text}\n"
        f"**👥 Guruhlar:** {active_groups} ta Faol / {total_groups} ta Jami\n"
        f"**⏱ Doira oralig'i:** {cycle_min}s - {cycle_max}s\n"
        f"**⚡️ Yuborish tezligi (Jitter):** {jitter_min}s - {jitter_max}s (~{est_minutes:.1f} daqiqada {active_groups} ta guruh)\n"
    )
    
    markup = kb.main_dashboard_kb(is_running, drop_author)
    
    if isinstance(message_or_call, Message):
        await message_or_call.answer(text, reply_markup=markup, parse_mode="Markdown")
    else:
        with contextlib.suppress(TelegramBadRequest):
            await message_or_call.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")

@router.message(CommandStart())
@router.message(Command("menu"))
async def start_cmd(message: Message, state: FSMContext):
    await render_dashboard(message, state)

@router.callback_query(F.data == "back_dashboard")
async def back_dashboard_call(call: CallbackQuery, state: FSMContext):
    await render_dashboard(call, state)
    await safe_answer(call)

@router.callback_query(F.data == "toggle_state")
async def toggle_state_call(call: CallbackQuery):
    is_running = await db.get_setting("is_running", False)
    source_chat_id = await db.get_setting("source_chat_id", None)
    
    if not is_running and not source_chat_id:
        await safe_answer(call, "Avval 'Manba guruhni sozlash' tugmasi orqali xabar olinadigan guruhni ulang!", show_alert=True)
        return
        
    await db.set_setting("is_running", not is_running)
    await render_dashboard(call)
    await safe_answer(call, "Holat o'zgartirildi!")

@router.callback_query(F.data == "toggle_drop_author")
async def toggle_drop_author_call(call: CallbackQuery):
    drop_author = await db.get_setting("drop_author", False)
    await db.set_setting("drop_author", not drop_author)
    await render_dashboard(call)
    await safe_answer(call, "Forward rejimi o'zgartirildi!")

# ==================== SOURCE CHAT SETUP ====================
@router.callback_query(F.data == "set_source_chat")
async def set_source_chat_call(call: CallbackQuery, state: FSMContext):
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(
            "📥 **Manba guruhni sozlash**\n\n"
            "Xabarlar qaysi guruh yoki kanaldan olinib tarqatilishi kerak?\n\n"
            "👉 O'sha guruh/kanaldagi **biron bir xabarni to'g'ridan-to'g'ri ushbu botga Forward (Uzatish)** qilib yuboring,\n"
            "yoki guruhning `@username` yoki `https://t.me/...` havolasini yuboring.\n\n"
            "*(Bot har doim o'sha guruhdagi eng oxirgi yuborilgan yangi xabarni avtomatik oladi)*",
            reply_markup=kb.back_kb(),
            parse_mode="Markdown"
        )
    await state.set_state(BotStates.waiting_for_source_chat)
    await safe_answer(call)

@router.message(BotStates.waiting_for_source_chat)
async def process_source_chat_input(message: Message, state: FSMContext, bot: Bot):
    worker_client = getattr(bot, 'worker_client', None)
    source_chat_id = None
    source_chat_title = None
    
    # 1. Check if user forwarded a message
    if message.forward_from_chat:
        source_chat_id = message.forward_from_chat.id
        source_chat_title = message.forward_from_chat.title or f"Chat {source_chat_id}"
    
    # 2. Check if user sent a link or @username
    elif message.text and (message.text.startswith("@") or "t.me/" in message.text or message.text.startswith("-100")):
        if not worker_client:
            await message.answer("⚠️ Worker akkaunti ulanmagan.", reply_markup=kb.back_kb())
            return
        try:
            entity_input = message.text.strip()
            if entity_input.startswith("-100"):
                entity_input = int(entity_input)
            entity = await worker_client.get_entity(entity_input)
            source_chat_id = entity.id
            source_chat_title = getattr(entity, 'title', f"Chat {entity.id}")
            if not str(source_chat_id).startswith("-100"):
                from telethon.tl.types import Channel
                if isinstance(entity, Channel):
                    source_chat_id = int(f"-100{entity.id}")
        except Exception as e:
            logger.error(f"Error resolving source chat: {e}")
            await message.answer(
                f"⚠️ Guruhni havola orqali aniqlab bo'lmadi.\nIltimos, guruhdan birorta xabarni to'g'ridan-to'g'ri Forward (Uzatish) qilib yuboring!",
                reply_markup=kb.back_kb()
            )
            return
            
    if source_chat_id:
        await db.set_setting("source_chat_id", source_chat_id)
        await db.set_setting("source_chat_title", source_chat_title)
        await message.answer(
            f"✅ **Manba guruh muvaffaqiyatli ulandi!**\n\n"
            f"📢 **Nomi:** {source_chat_title}\n"
            f"🆔 **ID:** `{source_chat_id}`\n\n"
            f"Endi ushbu guruhga yangi e'lon yozsangiz, bot har bir aylanmada o'sha eng oxirgi xabarni barcha guruhlarga tarqatadi!",
            parse_mode="Markdown"
        )
        await render_dashboard(message, state)
    else:
        await message.answer(
            "⚠️ Noma'lum format. Iltimos, manba guruhingizdan birorta xabarni botga Forward qilib yuboring!",
            reply_markup=kb.back_kb()
        )

# ==================== TIMING CONFIGURATION ====================
@router.callback_query(F.data == "adjust_timing")
async def adjust_timing_call(call: CallbackQuery):
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(
            "⏱ **Doira oralig'ini sozlash (Round Cooldown)**\n\n"
            "Barcha guruhlarga xabar yuborib bo'lingach, keyingi to'liq aylanmagacha bo'lgan kutish vaqti:",
            reply_markup=kb.timing_kb(),
            parse_mode="Markdown"
        )
    await safe_answer(call)

@router.callback_query(F.data.startswith("time_preset_"))
async def time_preset_call(call: CallbackQuery):
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
        
    await db.set_setting("cycle_min", c_min)
    await db.set_setting("cycle_max", c_max)
    await render_dashboard(call)
    await safe_answer(call, f"Doira vaqti sozlandi: {label}")

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
    try:
        parts = message.text.strip().split()
        if len(parts) != 2:
            raise ValueError()
        c_min, c_max = int(parts[0]), int(parts[1])
        if c_min < 0 or c_max < c_min:
            raise ValueError()
            
        await db.set_setting("cycle_min", c_min)
        await db.set_setting("cycle_max", c_max)
        await render_dashboard(message, state)
    except ValueError:
        await message.answer(
            "⚠️ Noto'g'ri format. Iltimos, ikkita musbat son kiriting, masalan: `60 90` yoki `180 300`.",
            reply_markup=kb.back_kb()
        )

# ==================== JITTER CONFIGURATION ====================
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
        
    await db.set_setting("jitter_min", j_min)
    await db.set_setting("jitter_max", j_max)
    await render_dashboard(call)
    await safe_answer(call, f"Yuborish tezligi: {label}")

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
    try:
        parts = message.text.strip().split()
        if len(parts) != 2:
            raise ValueError()
        j_min, j_max = float(parts[0]), float(parts[1])
        if j_min < 0.5 or j_max < j_min:
            raise ValueError()
            
        await db.set_setting("jitter_min", j_min)
        await db.set_setting("jitter_max", j_max)
        await render_dashboard(message, state)
    except ValueError:
        await message.answer(
            "⚠️ Noto'g'ri format. Iltimos, ikkita son kiriting (kamida 0.5), masalan: `1.5 2.0` yoki `2 4`.",
            reply_markup=kb.back_kb()
        )

# ==================== GROUP MANAGEMENT ====================
@router.callback_query(F.data == "manage_groups")
async def manage_groups_call(call: CallbackQuery, bot: Bot):
    worker_client = getattr(bot, 'worker_client', None)
    if not worker_client:
        await safe_answer(call, "Worker akkaunti ulanmagan.", show_alert=True)
        return
        
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text("⏳ Guruhlar tekshirilmoqda, iltimos kuting...")
    
    try:
        from telethon.tl.types import Channel, Chat
        dialogs = await worker_client.get_dialogs()
        source_chat_id = await db.get_setting("source_chat_id", None)
        
        for d in dialogs:
            if (d.is_group or d.is_channel) and d.id != source_chat_id:
                is_valid = False
                if getattr(d.entity, 'megagroup', False):
                    is_valid = True
                elif isinstance(d.entity, Chat):
                    is_valid = True
                    
                if is_valid:
                    username = getattr(d.entity, 'username', None)
                    await db.add_or_update_group(
                        chat_id=d.id,
                        title=d.name,
                        username=username,
                        is_active=True
                    )
                    
        groups = await db.get_all_groups()
        with contextlib.suppress(TelegramBadRequest):
            await call.message.edit_text(
                f"👥 **Guruhlarni Boshqarish**\n"
                f"Jami {len(groups)} ta guruh topildi.\n"
                "Xabar tarqatiladigan guruhlarni belgilang (✅ - faol, ⬜️ - o'chirilgan):",
                reply_markup=kb.paginated_groups_kb(groups, 0)
            )
    except Exception as e:
        logger.error(f"Error scanning groups: {e}")
        with contextlib.suppress(TelegramBadRequest):
            await call.message.edit_text("Guruhlarni yuklashda xatolik yuz berdi. Loglarni tekshiring.", reply_markup=kb.back_kb())
    await safe_answer(call)

@router.callback_query(F.data == "noop")
async def noop_call(call: CallbackQuery):
    await safe_answer(call)

@router.callback_query(F.data.startswith("bulk_groups_on_"))
async def bulk_groups_on_call(call: CallbackQuery):
    page = int(call.data.split("_")[3])
    await db.set_all_groups_active(True)
    groups = await db.get_all_groups()
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_reply_markup(reply_markup=kb.paginated_groups_kb(groups, page))
    await safe_answer(call, "Barcha guruhlar faollashtirildi!")

@router.callback_query(F.data.startswith("bulk_groups_off_"))
async def bulk_groups_off_call(call: CallbackQuery):
    page = int(call.data.split("_")[3])
    await db.set_all_groups_active(False)
    groups = await db.get_all_groups()
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_reply_markup(reply_markup=kb.paginated_groups_kb(groups, page))
    await safe_answer(call, "Barcha guruhlar o'chirildi!")

@router.callback_query(F.data.startswith("page_groups_"))
async def page_groups_call(call: CallbackQuery):
    page = int(call.data.split("_")[2])
    groups = await db.get_all_groups()
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_reply_markup(reply_markup=kb.paginated_groups_kb(groups, page))
    await safe_answer(call)

@router.callback_query(F.data.startswith("toggle_group_"))
async def toggle_group_call(call: CallbackQuery):
    parts = call.data.split("_")
    chat_id = int(parts[2])
    page = int(parts[3])
    
    groups = await db.get_all_groups()
    target = next((g for g in groups if g['chat_id'] == chat_id), None)
    if target:
        new_status = not target['is_active']
        await db.update_group_status(chat_id, target['status'], is_active=new_status)
        
    groups = await db.get_all_groups()
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_reply_markup(reply_markup=kb.paginated_groups_kb(groups, page))
    await safe_answer(call)

# ==================== QUICK TARGET GROUP ADD ====================
@router.message(F.forward_from_chat)
async def forward_inspector(message: Message, state: FSMContext):
    # If in source chat setup state, don't intercept as target group
    current_state = await state.get_state()
    if current_state == BotStates.waiting_for_source_chat.state:
        return
        
    chat = message.forward_from_chat
    if chat.type in ["group", "supergroup"]:
        title = chat.title or f"Guruh {chat.id}"
        username = chat.username
        await db.add_or_update_group(chat_id=chat.id, title=title, username=username, is_active=True)
        
        user_link = f"@{username}" if username else f"`{chat.id}`"
        text = (
            f"✅ **Guruh muvaffaqiyatli qo'shildi va faollashtirildi!**\n\n"
            f"👥 **Nomi:** [{title}](https://t.me/{username})\n" if username else
            f"✅ **Guruh muvaffaqiyatli qo'shildi va faollashtirildi!**\n\n"
            f"👥 **Nomi:** **{title}**\n"
            f"🆔 **ID:** `{chat.id}`\n"
            f"🔗 **Havola/Username:** {user_link}\n\n"
            f"Ushbu guruh keyingi xabar tarqatish doirasida hisobga olinadi."
        )
        await message.answer(text, parse_mode="Markdown")
    else:
        await message.answer("⚠️ Uzatilgan xabar guruh yoki superguruhdan emas.")

@router.message(F.text.startswith("@") | F.text.contains("t.me/"))
async def link_group_inspector(message: Message, bot: Bot, state: FSMContext):
    current_state = await state.get_state()
    if current_state:
        return
        
    worker_client = getattr(bot, 'worker_client', None)
    if not worker_client:
        await message.answer("⚠️ Worker akkaunti ulanmagan.")
        return
        
    link_or_user = message.text.strip()
    try:
        from telethon.tl.types import Channel, Chat
        entity = await worker_client.get_entity(link_or_user)
        is_group = False
        if getattr(entity, 'megagroup', False) or isinstance(entity, Chat) or (isinstance(entity, Channel) and not entity.broadcast):
            is_group = True
            
        if is_group:
            title = getattr(entity, 'title', f"Guruh {entity.id}")
            username = getattr(entity, 'username', None)
            chat_id = entity.id
            if not str(chat_id).startswith("-100") and isinstance(entity, Channel):
                chat_id = int(f"-100{entity.id}")
                
            await db.add_or_update_group(chat_id=chat_id, title=title, username=username, is_active=True)
            user_link = f"@{username}" if username else f"`{chat_id}`"
            await message.answer(
                f"✅ **Guruh muvaffaqiyatli qo'shildi va faollashtirildi!**\n\n"
                f"👥 **Nomi:** **{title}**\n"
                f"🆔 **ID:** `{chat_id}`\n"
                f"🔗 **Havola/Username:** {user_link}\n\n"
                f"Ushbu guruh keyingi doirada xabar oluvchilar ro'yxatiga kiritildi.",
                parse_mode="Markdown"
            )
        else:
            await message.answer("⚠️ Kiritilgan havola guruhga tegishli emas (kanal yoki shaxsiy profil).")
    except Exception as e:
        logger.error(f"Error adding group from link/username: {e}")
        await message.answer(
            f"⚠️ Guruhni havola orqali topib bo'lmadi.\n"
            f"**Maslahat:** Guruhdagi birorta xabarni to'g'ridan-to'g'ri ushbu botga **Forward (Uzatish)** qilib yuboring!"
        )

# ==================== MANUAL TEST TRIGGER ====================
@router.callback_query(F.data == "trigger_test")
async def trigger_test_call(call: CallbackQuery, bot: Bot):
    source_chat_id = await db.get_setting("source_chat_id", None)
    if not source_chat_id:
        await safe_answer(call, "Avval 'Manba guruhni sozlash' tugmasi orqali xabar olinadigan guruhni ulang!", show_alert=True)
        return
        
    worker_event = getattr(bot, 'worker_test_event', None)
    if worker_event:
        worker_event.set()
        await safe_answer(call, "Sinov yuborish boshlandi!", show_alert=True)
    else:
        await safe_answer(call, "Worker tizimi ulanmagan.", show_alert=True)
