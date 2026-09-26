"""
Automated VIP Subscription Expiration Reminder & Retention Scheduler.
Notifies VIP drivers and trial users ahead of their due dates:
- Track A (Regular VIP Subscribers):
    * DAY_3: 3 days before expiry
    * DAY_2: 2 days before expiry
    * DAY_1: Final day of expiry
- Track B (24-Hour Free Trial Users):
    * TRIAL_EXPIRING: 3-4 hours before trial expiry

Guarantees:
1. Active window: strictly between 08:00 and 20:00 Tashkent time (UTC+5).
2. Idempotency: exactly 1 message per reminder type per subscription cycle.
3. Clean bold typography (NO cursive/italic text).
4. Full bilingual support (Latin and Cyrillic).
"""
import asyncio
import contextlib
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

from src import database as db
from src.logger import setup_logger

logger = setup_logger("reminder_scheduler")

def is_within_sending_window(now_utc: Optional[datetime] = None) -> bool:
    """
    Checks if current time in Tashkent (UTC+5) is within 08:00 - 20:00.
    """
    utc_time = now_utc or datetime.utcnow()
    tashkent_time = utc_time + timedelta(hours=5)
    return 8 <= tashkent_time.hour < 20

def classify_reminder(
    user: Dict[str, Any],
    is_trial_user: bool,
    now_utc: Optional[datetime] = None
) -> Optional[str]:
    """
    Evaluates which reminder (if any) the user is eligible for.
    Returns: 'DAY_3', 'DAY_2', 'DAY_1', 'TRIAL_EXPIRING', or None.
    """
    expiry_str = user.get("subscription_expiry")
    if not expiry_str:
        return None

    try:
        expiry_dt = datetime.strptime(expiry_str, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None

    utc_now = now_utc or datetime.utcnow()
    diff = expiry_dt - utc_now

    # Already expired or negative
    if diff <= timedelta(0):
        return None

    # Track B: 24-Hour Trial User
    if is_trial_user:
        # Check if 10 min < diff <= 4 hours
        if timedelta(minutes=10) < diff <= timedelta(hours=4):
            return "TRIAL_EXPIRING"
        return None

    # Track A: Regular Paid VIP Subscriber
    if timedelta(days=2) < diff <= timedelta(days=3):
        return "DAY_3"
    elif timedelta(days=1) < diff <= timedelta(days=2):
        return "DAY_2"
    elif timedelta(0) < diff <= timedelta(days=1):
        return "DAY_1"

    return None

def format_reminder_message(
    reminder_type: str,
    script: str = "lat"
) -> Tuple[str, InlineKeyboardMarkup]:
    """
    Generates notification text and keyboard in Latin or Cyrillic.
    Strictly uses bold tags (<b>...</b>) with NO italics/cursive tags.
    """
    if reminder_type == "DAY_3":
        if script == "cyr":
            text = (
                "⏳ <b>VIP Обунангиз тугашига 3 кун қолди!</b>\n\n"
                "Ҳурматли ҳайдовчи, шахсий радарингиз ва йўловчилар билан тўғридан-тўғри боғланиш имкониятингиз 3 кундан сўнг тўхтатилади.\n\n"
                "💡 <b>Буюртмалар оқими ва махсус тариф имтиёзларингизни узлуксиз сақлаб қолиш учун обунани ҳозирдан узайтиришингиз мумкин.</b>"
            )
            btn_text = "⭐️ Обунани узайтириш (25,000 сўм)"
        else:
            text = (
                "⏳ <b>VIP Obunangiz tugashiga 3 kun qoldi!</b>\n\n"
                "Hurmatli haydovchi, shaxsiy radaringiz va yo'lovchilar bilan to'g'ridan-to'g'ri bog'lanish imkoniyatingiz 3 kundan so'ng to'xtatiladi.\n\n"
                "💡 <b>Buyurtmalar oqimi va maxsus tarif imtiyozlaringizni uzluksiz saqlab qolish uchun obunani hozirdan uzaytirishingiz mumkin.</b>"
            )
            btn_text = "⭐️ Obunani uzaytirish (25,000 so'm)"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=btn_text, callback_data="show_plans")]
        ])

    elif reminder_type == "DAY_2":
        if script == "cyr":
            text = (
                "⚠️ <b>VIP Обунангиз тугашига 2 кун қолди!</b>\n\n"
                "Йўналишингиздаги энг қайноқ буюртмаларни бошқа ҳайдовчилар олиб кетмаслиги учун VIP хизматингизни узайтиришни унутманг.\n\n"
                "💡 <b>Обунани бугун узайтиринг ва барча имтиёзларингизни сақлаб қолинг.</b>"
            )
            btn_text = "⭐️ Обунани узайтириш"
        else:
            text = (
                "⚠️ <b>VIP Obunangiz tugashiga 2 kun qoldi!</b>\n\n"
                "Yo'nalishingizdagi eng qaynoq buyurtmalarni boshqa haydovchilar olib ketmasligi uchun VIP xizmatingizni uzaytirishni unutmang.\n\n"
                "💡 <b>Obunani bugun uzaytiring va barcha imtiyozlaringizni saqlab qoling.</b>"
            )
            btn_text = "⭐️ Obunani uzaytirish"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=btn_text, callback_data="show_plans")]
        ])

    elif reminder_type == "DAY_1":
        if script == "cyr":
            text = (
                "🚨 <b>ДИҚҚАТ: VIP Обунангиз бугун тугайди!</b>\n\n"
                "Бугун VIP хизматингизнинг охирги куни. Обуна муддати тугагач, буюртмалардаги мижоз телефон рақамлари яширилади ва шахсий радар хабарлари тўхтатилади.\n\n"
                "<b>Оқ йўл ва баракали даромад тилаймиз!</b>"
            )
            btn_text = "⚡️ Ҳозир узайтириш"
        else:
            text = (
                "🚨 <b>DIQQAT: VIP Obunangiz bugun tugaydi!</b>\n\n"
                "Bugun VIP xizmatingizning oxirgi kuni. Obuna muddati tugagach, buyurtmalardagi mijoz telefon raqamlari yashiriladi va shaxsiy radar xabarlari to'xtatiladi.\n\n"
                "<b>Oq yo'l va barakali daromad tilaymiz!</b>"
            )
            btn_text = "⚡️ Hozir uzaytirish"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=btn_text, callback_data="show_plans")]
        ])

    elif reminder_type == "TRIAL_EXPIRING":
        if script == "cyr":
            text = (
                "⏳ <b>24 соатлик бепул синов муддатиңиз тугашига 3 соат қолди!</b>\n\n"
                "Бугун сиз радардан фойдаланиб, тизим тезлиги ва қулайлигини амалда синаб кўрдингиз. Синов муддати тугагач, буюртмалардаги мижоз телефон рақамлари яширилади.\n\n"
                "💡 <b>Янги йўловчиларни биринчи бўлиб қабул қилишда давом этиш учун VIP обунани фаоллаштиринг:</b>"
            )
            btn_text = "⭐️ VIP Обунани фаоллаштириш (25,000 сўм)"
        else:
            text = (
                "⏳ <b>24 soatlik bepul sinov muddatingiz tugashiga 3 soat qoldi!</b>\n\n"
                "Bugun siz radardan foydalanib, tizim tezligi va qulayligini amalda sinab ko'rdingiz. Sinov muddati tugagach, buyurtmalardagi mijoz telefon raqamlari yashiriladi.\n\n"
                "💡 <b>Yangi yo'lovchilarni birinchi bo'lib qabul qilishda davom etish uchun VIP obunani faollashtiring:</b>"
            )
            btn_text = "⭐️ VIP Obunani faollashtirish (25,000 so'm)"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=btn_text, callback_data="show_plans")]
        ])
    else:
        text = "<b>VIP Obunangiz haqida eslatma</b>"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⭐️ Tariflar", callback_data="show_plans")]
        ])

    return text, kb


class SubscriptionReminderScheduler:
    """
    Background worker that runs periodic checks and dispatches
    expiry reminder alerts to VIP subscribers and 24h trial drivers.
    """
    def __init__(self, bot: Optional[Bot] = None, check_interval_seconds: int = 1800):
        self.bot = bot
        self.check_interval_seconds = check_interval_seconds
        self._is_running = False
        self._task: Optional[asyncio.Task] = None

    def start(self):
        """Starts background periodic reminder loop."""
        if self._task is None or self._task.done():
            self._is_running = True
            self._task = asyncio.create_task(self._loop())
            logger.info("Subscription reminder scheduler started.")

    def stop(self):
        """Stops background periodic reminder loop."""
        self._is_running = False
        if self._task and not self._task.done():
            self._task.cancel()
            self._task = None
            logger.info("Subscription reminder scheduler stopped.")

    async def _loop(self):
        last_prune_time = 0.0
        while self._is_running:
            try:
                await self.check_and_dispatch()
                await self.cleanup_expired_order_pool_members()

                # Daily database retention pruning (> 7 days)
                now_ts = datetime.utcnow().timestamp()
                if now_ts - last_prune_time > 86400:
                    with contextlib.suppress(Exception):
                        await db.prune_harvested_data(retention_days=7)
                    last_prune_time = now_ts

                await asyncio.sleep(self.check_interval_seconds)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in subscription reminder scheduler loop: {e}", exc_info=True)
                await asyncio.sleep(60)

    async def cleanup_expired_order_pool_members(self) -> int:
        """
        Kicks expired subscribers from the private VIP Order Pool group.
        Bans and then unbans each expired user so they are removed from the group,
        but can rejoin when they renew their subscription.
        Idempotent: marks users as evicted to avoid repeated spam.
        """
        if not self.bot:
            return 0

        order_pool_chat_id = await db.get_order_pool_chat_id()
        if not order_pool_chat_id:
            return 0

        expired_users = await db.get_recently_expired_users(hours=48)
        kicked_count = 0

        for u in expired_users:
            uid = u["user_id"]
            try:
                await self.bot.ban_chat_member(order_pool_chat_id, uid)
                await self.bot.unban_chat_member(order_pool_chat_id, uid)
                kicked_count += 1
                logger.info(f"Removed expired driver #{uid} from order pool group ({order_pool_chat_id}).")
            except Exception as e:
                logger.debug(f"Could not remove driver #{uid} from order pool group: {e}")
            finally:
                # Mark user as evicted so we never repeatedly execute ban/unban on every pass
                await db.mark_user_order_pool_kicked(uid, True)

        return kicked_count

    async def check_and_dispatch(self, now_utc: Optional[datetime] = None) -> int:
        """
        Executes a single evaluation pass across all active subscribers.
        Returns total number of reminder messages successfully dispatched.
        """
        if not is_within_sending_window(now_utc):
            logger.debug("Outside 08:00 - 20:00 Tashkent sending window. Skipping reminder dispatch.")
            return 0

        users = await db.get_active_subscribed_users()
        if not users:
            return 0

        dispatched_count = 0

        for user in users:
            user_id = user["user_id"]
            expiry_str = user.get("subscription_expiry")
            if not expiry_str:
                continue

            # Determine if this user is a 24-hour trial user
            has_used_trial = bool(user.get("has_used_trial", 0))
            is_trial = False
            if has_used_trial:
                has_paid = await db.has_user_ever_purchased(user_id)
                if not has_paid:
                    is_trial = True

            reminder_type = classify_reminder(user, is_trial_user=is_trial, now_utc=now_utc)
            if not reminder_type:
                continue

            # Idempotency check: has this reminder already been sent for this cycle?
            already_sent = await db.has_subscription_reminder_been_sent(user_id, reminder_type, expiry_str)
            if already_sent:
                continue

            # Dispatch message
            script = user.get("script", "lat")
            text, kb = format_reminder_message(reminder_type, script=script)

            if self.bot:
                try:
                    await self.bot.send_message(
                        chat_id=user_id,
                        text=text,
                        reply_markup=kb,
                        parse_mode="HTML"
                    )
                    await db.record_subscription_reminder(user_id, reminder_type, expiry_str)
                    dispatched_count += 1
                    logger.info(f"Dispatched {reminder_type} reminder to driver #{user_id} (Expires: {expiry_str}).")
                except (TelegramForbiddenError, TelegramBadRequest) as e:
                    logger.debug(f"Could not send reminder to driver #{user_id}: {e}")
                    await db.record_subscription_reminder(user_id, reminder_type, expiry_str)
                except Exception as e:
                    logger.error(f"Error dispatching reminder to driver #{user_id}: {e}")
            else:
                # Dry-run or test mode without live bot
                await db.record_subscription_reminder(user_id, reminder_type, expiry_str)
                dispatched_count += 1

        return dispatched_count
