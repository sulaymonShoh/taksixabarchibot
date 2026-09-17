import os
import contextlib
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest

from src import database as db
from src.bot import keyboards as kb
from src.config import MEDIA_DIR, DEFAULT_CYCLE_MIN, DEFAULT_CYCLE_MAX, DEFAULT_JITTER_MIN, DEFAULT_JITTER_MAX
from src.worker.spintax import parse_spintax
from src.logger import setup_logger

logger = setup_logger("handlers")
router = Router()

class BotStates(StatesGroup):
    waiting_for_message = State()
    waiting_for_custom_timing = State()

async def safe_answer(call: CallbackQuery, text: str = None, show_alert: bool = False):
    """Safely answer callback queries ignoring timeout/invalid query errors."""
    with contextlib.suppress(TelegramBadRequest):
        await call.answer(text=text, show_alert=show_alert)

async def render_dashboard(message_or_call, state: FSMContext = None):
    if state:
        await state.clear()
        
    is_running = await db.get_setting("is_running", False)
    auto_cleanup = await db.get_setting("auto_cleanup", False)
    
    cycle_min = await db.get_setting("cycle_min", DEFAULT_CYCLE_MIN)
    cycle_max = await db.get_setting("cycle_max", DEFAULT_CYCLE_MAX)
    jitter_min = await db.get_setting("jitter_min", DEFAULT_JITTER_MIN)
    jitter_max = await db.get_setting("jitter_max", DEFAULT_JITTER_MAX)
    
    groups = await db.get_all_groups()
    active_groups = len([g for g in groups if g['is_active']])
    total_groups = len(groups)
    
    content = await db.get_setting("content_text", "Xabar hali o'rnatilmagan.")
    media_path = await db.get_setting("media_path", None)
    
    # Truncate content for dashboard preview snippet
    preview_snippet = content
    if len(preview_snippet) > 100:
        preview_snippet = preview_snippet[:97] + "..."
        
    text = (
        "🎛 **Xabarlar Tarqatish Boshqaruv Paneli**\n\n"
        f"**Holat:** {'🟢 FAOL (Ishlayapti)' if is_running else '🔴 TO\'XTATILGAN (Pauza)'}\n"
        f"**Guruhlar:** {active_groups} ta Faol / {total_groups} ta Jami\n"
        f"**Doira oralig'i:** {cycle_min}s - {cycle_max}s\n"
        f"**Yuborish tezligi (Jitter):** {jitter_min}s - {jitter_max}s\n"
        f"**Oldingi xabarni tozalash:** {'YOQILGAN' if auto_cleanup else 'O\'CHIRILGAN'}\n\n"
        "**📝 O'rnatilgan xabar:**\n"
        f"_{preview_snippet}_\n"
        f"*{'🖼 Rasm/Video biriktirilgan' if media_path else 'Faqat matn'}*"
    )
    
    markup = kb.main_dashboard_kb(is_running, auto_cleanup)
    
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
    await db.set_setting("is_running", not is_running)
    await render_dashboard(call)
    await safe_answer(call, "Holat o'zgartirildi!")

@router.callback_query(F.data == "toggle_cleanup")
async def toggle_cleanup_call(call: CallbackQuery):
    auto_cleanup = await db.get_setting("auto_cleanup", False)
    await db.set_setting("auto_cleanup", not auto_cleanup)
    await render_dashboard(call)
    await safe_answer(call, "Avto-tozalash sozlamasi o'zgartirildi!")

# Message Preview Handler
@router.callback_query(F.data == "preview_message")
async def preview_message_call(call: CallbackQuery, bot: Bot):
    content = await db.get_setting("content_text", "")
    media_path = await db.get_setting("media_path", None)
    
    if not content and not media_path:
        await safe_answer(call, "Xabar hali o'rnatilmagan! Avval 'Xabarni tahrirlash' tugmasini bosing.", show_alert=True)
        return
        
    await safe_answer(call, "Xabar namunasi tayyorlanmoqda...")
    
    # Parse spintax to show a live variation
    sample_text = parse_spintax(content) if content else ""
    
    try:
        await call.message.answer("👁 **Guruhlarda ko'rinadigan xabar namunasi (Spintax varianti bilan):**", parse_mode="Markdown")
        
        if media_path and os.path.exists(media_path):
            ext = media_path.split('.')[-1].lower()
            file = FSInputFile(media_path)
            if ext in ['mp4', 'mov', 'avi', 'mkv']:
                await bot.send_video(call.from_user.id, file, caption=sample_text, parse_mode="HTML")
            else:
                await bot.send_photo(call.from_user.id, file, caption=sample_text, parse_mode="HTML")
        else:
            await bot.send_message(call.from_user.id, sample_text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error sending preview: {e}")
        await call.message.answer(f"⚠️ Xabarni ko'rsatishda xatolik yuz berdi: {e}")

@router.callback_query(F.data == "adjust_timing")
async def adjust_timing_call(call: CallbackQuery):
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(
            "⏱ **Vaqt oralig'ini sozlash**\n\n"
            "Guruhlarga xabar tarqatish doiralari (har bir to'liq aylanma) orasidagi kutish vaqtini tanlang:",
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
    await safe_answer(call, f"Vaqt sozlandi: {label}")

@router.callback_query(F.data == "time_custom")
async def time_custom_call(call: CallbackQuery, state: FSMContext):
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(
            "✍️ **O'zingiz vaqt kiriting**\n\n"
            "Minimal va maksimal kutish vaqtini soniyalarda probel bilan yuboring.\n"
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

@router.callback_query(F.data == "edit_message")
async def edit_message_call(call: CallbackQuery, state: FSMContext):
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(
            "📝 **Tarqatiladigan xabarni tahrirlash**\n\n"
            "Yangi matnni yuboring (Spintax variantlaridan foydalanishingiz mumkin, masalan: `{Salom|Assalomu alaykum}` va formatlash teglari).\n\n"
            "Agar rasm yoki video qo'shmoqchi bo'lsangiz, uni izoh (caption) bilan birga to'g'ridan-to'g'ri botga yuboring.\n\n"
            "_Eslatma: Yangi media yuborilsa, avvalgi media fayl yangilanadi._",
            reply_markup=kb.back_kb(),
            parse_mode="Markdown"
        )
    await state.set_state(BotStates.waiting_for_message)
    await safe_answer(call)

@router.message(BotStates.waiting_for_message)
async def process_new_message(message: Message, state: FSMContext, bot: Bot):
    text = ""
    media_path = None
    
    # Process text/caption
    if message.text:
        text = message.html_text
    elif message.caption:
        text = message.html_text
        
    # Process media
    if message.photo:
        photo = message.photo[-1]
        file_id = photo.file_id
        file_info = await bot.get_file(file_id)
        ext = file_info.file_path.split('.')[-1]
        media_path = os.path.join(MEDIA_DIR, f"broadcast_media.{ext}")
        await bot.download_file(file_info.file_path, media_path)
        
    elif message.video:
        file_id = message.video.file_id
        file_info = await bot.get_file(file_id)
        ext = file_info.file_path.split('.')[-1]
        media_path = os.path.join(MEDIA_DIR, f"broadcast_media.{ext}")
        await bot.download_file(file_info.file_path, media_path)
    
    # If it's pure text, clear media path
    if not message.photo and not message.video:
        old_path = await db.get_setting("media_path")
        if old_path and os.path.exists(old_path):
            os.remove(old_path)
            
    await db.set_setting("content_text", text)
    await db.set_setting("media_path", media_path)
    
    await message.answer("✅ Xabar muvaffaqiyatli saqlandi!")
    await render_dashboard(message, state)

# Group Management
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
        group_count = 0
        for d in dialogs:
            if d.is_group or d.is_channel:
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
                    group_count += 1
                    
        groups = await db.get_all_groups()
        with contextlib.suppress(TelegramBadRequest):
            await call.message.edit_text(
                f"👥 **Guruhlarni Boshqarish**\n"
                f"Jami {len(groups)} ta guruh topildi.\n"
                "Xabar yuboriladigan guruhlarni belgilang (✅ - faol, ⬜️ - o'chirilgan):",
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
        
    # Refresh list
    groups = await db.get_all_groups()
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_reply_markup(reply_markup=kb.paginated_groups_kb(groups, page))
    await safe_answer(call)

# Forward Inspector for Quick Add
# Forward Inspector for Quick Add
@router.message(F.forward_from_chat)
async def forward_inspector(message: Message):
    chat = message.forward_from_chat
    if chat.type in ["group", "supergroup"]:
        title = chat.title or f"Guruh {chat.id}"
        username = chat.username
        # Store group in DB immediately with active=True and proper title/username
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

# Direct Group Link or Username Inspector
@router.message(F.text.startswith("@") | F.text.contains("t.me/"))
async def link_group_inspector(message: Message, bot: Bot, state: FSMContext):
    current_state = await state.get_state()
    if current_state:
        # User is in FSM state (like editing message or custom timing), let state handler handle it
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

@router.callback_query(F.data.startswith("add_group_"))
async def add_forward_group_call(call: CallbackQuery, bot: Bot):
    chat_id = int(call.data.split("_")[2])
    await db.add_or_update_group(chat_id=chat_id, title=f"Guruh {chat_id}", is_active=True)
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text("✅ Guruh muvaffaqiyatli qo'shildi va faollashtirildi!")
    await safe_answer(call)

@router.callback_query(F.data == "dismiss")
async def dismiss_call(call: CallbackQuery):
    with contextlib.suppress(TelegramBadRequest):
        await call.message.delete()
    await safe_answer(call)

# Manual Test Trigger
@router.callback_query(F.data == "trigger_test")
async def trigger_test_call(call: CallbackQuery, bot: Bot):
    worker_event = getattr(bot, 'worker_test_event', None)
    if worker_event:
        worker_event.set()
        await safe_answer(call, "Sinov yuborish boshlandi!", show_alert=True)
    else:
        await safe_answer(call, "Worker tizimi ulanmagan.", show_alert=True)
