"""
Real-Time Order Dispatcher Grid & Paywall Teaser Delivery for Taksi Xabarchi v3.0.
Dispatches matching passenger and cargo orders directly to active drivers via Telegram DM.
- VIP Drivers: Receive full uncensored client details in sub-second speed (< 500ms).
- Expired / Free Drivers: Receive masked Paywall Teasers driving VIP subscription conversions.
"""
import re
import asyncio
import time
from typing import Dict, Any, List, Optional, Tuple
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

from src import database as db
from src.harvester.matcher import CorridorMatcher, default_matcher
from src.logger import setup_logger

logger = setup_logger("harvester_dispatcher")

def mask_phone_number(phone: Optional[str]) -> str:
    """
    Masks a phone number for paywall teaser display:
    +998901234567 -> +998 90 ••• •• 67
    """
    if not phone:
        return "Mavjud emas"
    digits = re.sub(r"\D", "", phone)
    if len(digits) >= 12 and digits.startswith("998"):
        return f"+998 {digits[3:5]} ••• •• {digits[-2:]}"
    elif len(digits) >= 9:
        return f"+998 {digits[-9:-7]} ••• •• {digits[-2:]}"
    return "+998 •• ••• •• ••"

def mask_telegram_username(username: Optional[str]) -> str:
    """Masks a Telegram username for paywall teaser display."""
    if not username:
        return ""
    return "@••••••"

def mask_raw_text(text: str, placeholder: str = "[VIP raqam yashirilgan]") -> str:
    """Replaces phone numbers in raw client text with masked placeholders."""
    return re.sub(
        r"(\+?998[\s\-]?)?\d{2}[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}",
        placeholder,
        text
    )

def build_order_action_keyboard(
    order_id: int,
    username: Optional[str] = None,
    is_vip: bool = True,
    message_link: Optional[str] = None,
    script: str = "lat",
    can_claim_trial: bool = False
) -> InlineKeyboardMarkup:
    """Constructs Telegram inline action buttons for the order alert."""
    keyboard = []

    if is_vip:
        claim_text = "⚡️ Буюртмани олиш (Банд қилиш)" if script == "cyr" else "⚡️ Buyurtmani olish (Band qilish)"
        dead_text = "❌ Мижоз такси топган" if script == "cyr" else "❌ Mijoz taksi topgan"
        keyboard.append([
            InlineKeyboardButton(text=claim_text, callback_data=f"claim_order_{order_id}")
        ])
        keyboard.append([
            InlineKeyboardButton(text=dead_text, callback_data=f"dead_order_{order_id}")
        ])
    else:
        # Paywall Teaser Keyboard -> Direct 1-tap conversion button
        if can_claim_trial:
            trial_text = "🎁 24 соат бепул синаб кўриш" if script == "cyr" else "🎁 24 soat bepul sinab ko'rish"
            keyboard.append([
                InlineKeyboardButton(text=trial_text, callback_data="claim_trial")
            ])
        vip_cta = "⭐️ VIP Обунани фаоллаштириш (25,000 сўм)" if script == "cyr" else "⭐️ VIP Obunani faollashtirish (25,000 so'm)"
        keyboard.append([
            InlineKeyboardButton(text=vip_cta, callback_data="show_plans")
        ])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def build_order_claimed_keyboard(script: str = "lat") -> InlineKeyboardMarkup:
    """Keyboard for the winning driver who successfully claimed the order."""
    text = "✅ Қабул қилинган" if script == "cyr" else "✅ Qabul qilingan"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data="noop")]
    ])


def build_order_locked_keyboard(status: str = "CLAIMED", script: str = "lat") -> InlineKeyboardMarkup:
    """Keyboard for other drivers when an order is claimed or marked taken elsewhere."""
    if status == "TAKEN_ELSEWHERE":
        text = "❌ Такси топилган" if script == "cyr" else "❌ Taksi topilgan"
    else:
        text = "🔒 Банд қилинди" if script == "cyr" else "🔒 Band qilindi"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data="noop")]
    ])


class OrderDispatcher:
    """
    Sub-second dispatch engine delivering real-time order notifications
    to drivers matching highway corridors.
    """

    def __init__(
        self,
        bot: Optional[Bot] = None,
        matcher: Optional[CorridorMatcher] = None,
        teaser_cooldown_seconds: int = 3600
    ):
        self.bot = bot
        self.matcher = matcher or default_matcher
        self.teaser_cooldown_seconds = teaser_cooldown_seconds
        self._teaser_last_sent: Dict[int, float] = {}
        self._total_vip_dispatched = 0
        self._total_teasers_dispatched = 0
        self._send_semaphore = asyncio.Semaphore(25)  # Telegram Bot API global broadcast limit protection

    def format_vip_notification(self, order: Dict[str, Any], match_meta: Dict[str, Any], script: str = "lat") -> str:
        """Formats full uncensored order alert for active VIP drivers."""
        return self.matcher.format_notification(order, match_meta, script=script)

    def format_teaser_notification(self, order: Dict[str, Any], match_meta: Dict[str, Any], script: str = "lat") -> str:
        """Formats clean paywall teaser for expired/free drivers without contacts or marketing bluff."""
        order_type = order.get("order_type", "PASSENGER")
        if script == "cyr":
            header = "📦 Почта" if order_type == "CARGO" else "👤 Йўловчи"
            teaser_note = "🔒 <i>Мижоз хабари ва контактларини кўриш учун VIP обунани фаоллаштиринг.</i>"
        else:
            header = "📦 Pochta" if order_type == "CARGO" else "👤 Yo'lovchi"
            teaser_note = "🔒 <i>Mijoz xabari va kontaktlarini ko'rish uchun VIP obunani faollashtiring.</i>"

        origin = order.get("origin") or {}
        dest = order.get("destination") or order.get("dest") or {}
        orig_name = origin.get("name") or order.get("origin_district") or order.get("origin_region")
        dest_name = dest.get("name") or order.get("dest_district") or order.get("dest_region")

        lines = [
            f"<b>{header}</b>",
            ""
        ]
        if orig_name and dest_name:
            lines.append(f"📍 {orig_name} ➡️ {dest_name}")
            lines.append("")

        lines.append(teaser_note)
        return "\n".join(lines).strip()

    async def send_to_driver(
        self,
        driver_id: int,
        is_vip: bool,
        order: Dict[str, Any],
        match_meta: Dict[str, Any],
        script: str = "lat"
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Dispatches an alert to a single driver."""
        if not self.bot:
            logger.warning("No bot instance configured for OrderDispatcher.")
            return False, None

        order_id = order.get("id", 0)
        username = order.get("telegram_username")
        message_link = order.get("message_link")
        sound_alert = match_meta.get("sound_alerts", True)

        try:
            async with self._send_semaphore:
                if is_vip:
                    text = self.format_vip_notification(order, match_meta, script=script)
                    kb_markup = build_order_action_keyboard(order_id, username, is_vip=True, message_link=message_link, script=script)
                    sent_msg = await self.bot.send_message(
                        chat_id=driver_id,
                        text=text,
                        reply_markup=kb_markup,
                        parse_mode="HTML",
                        disable_notification=not sound_alert
                    )
                    self._total_vip_dispatched += 1
                    msg_id = getattr(sent_msg, "message_id", None) or (sent_msg.get("message_id") or sent_msg.get("id") if isinstance(sent_msg, dict) else None)
                    rec = {"order_id": order_id, "driver_id": driver_id, "message_id": msg_id, "is_vip": True} if (order_id and msg_id) else None
                    return True, rec
                else:
                    # Teaser check: rate limit
                    now = time.time()
                    last_sent = self._teaser_last_sent.get(driver_id, 0)
                    if now - last_sent < self.teaser_cooldown_seconds:
                        return False, None

                    text = self.format_teaser_notification(order, match_meta, script=script)
                    can_trial = await db.can_user_claim_trial(driver_id)
                    kb_markup = build_order_action_keyboard(
                        order_id,
                        username,
                        is_vip=False,
                        script=script,
                        can_claim_trial=can_trial
                    )
                    sent_msg = await self.bot.send_message(
                        chat_id=driver_id,
                        text=text,
                        reply_markup=kb_markup,
                        parse_mode="HTML",
                        disable_notification=True
                    )
                    self._teaser_last_sent[driver_id] = now
                    self._total_teasers_dispatched += 1
                    msg_id = getattr(sent_msg, "message_id", None) or (sent_msg.get("message_id") or sent_msg.get("id") if isinstance(sent_msg, dict) else None)
                    rec = {"order_id": order_id, "driver_id": driver_id, "message_id": msg_id, "is_vip": False} if (order_id and msg_id) else None
                    return True, rec

        except (TelegramForbiddenError, TelegramBadRequest) as e:
            logger.debug(f"Could not send order #{order_id} to driver #{driver_id}: {e}")
            return False, None
        except Exception as e:
            logger.error(f"Error sending order #{order_id} to driver #{driver_id}: {e}")
            return False, None

    async def dispatch_to_order_pool(self, order: Dict[str, Any]) -> Optional[int]:
        """
        Dispatches the order directly to the designated VIP Order Pool Group
        with Telegram anti-sharing and copy-paste security (protect_content=True).
        """
        if not self.bot:
            logger.warning("No bot instance configured for OrderDispatcher.")
            return None

        order_pool_chat_id = await db.get_order_pool_chat_id()
        if not order_pool_chat_id:
            return None

        order_id = order.get("id", 0)
        username = order.get("telegram_username")
        message_link = order.get("message_link")

        # Full alert card for the VIP group
        text = self.matcher.format_notification(order, {}, script="lat")
        kb_markup = build_order_action_keyboard(
            order_id,
            username,
            is_vip=True,
            message_link=message_link,
            script="lat"
        )

        try:
            async with self._send_semaphore:
                sent_msg = await self.bot.send_message(
                    chat_id=order_pool_chat_id,
                    text=text,
                    reply_markup=kb_markup,
                    parse_mode="HTML",
                    protect_content=True  # Anti-sharing & copy-paste restriction
                )
            msg_id = getattr(sent_msg, "message_id", None) or (sent_msg.get("message_id") or sent_msg.get("id") if isinstance(sent_msg, dict) else None) or 1
            if order_id and order_id > 0 and msg_id:
                try:
                    await db.record_order_dispatch(order_id, order_pool_chat_id, msg_id, is_vip=True)
                except Exception as d_err:
                    logger.debug(f"Failed to record group dispatch: {d_err}")
            return msg_id
        except Exception as e:
            logger.error(f"Failed to dispatch order #{order_id} to order pool ({order_pool_chat_id}): {e}")
            return None

    async def send_test_order_pool_message(self) -> Dict[str, Any]:
        """Sends a test message with protect_content=True to verify bot permissions in the group."""
        if not self.bot:
            return {"success": False, "error": "Bot instansiyasi ulanmagan"}
        order_pool_chat_id = await db.get_order_pool_chat_id()
        if not order_pool_chat_id:
            return {"success": False, "error": "Order pool guruhi sozlanmagan"}
        try:
            test_text = (
                "🔒 <b>TEST: TAKSI XABARCHI BUYURTMALAR GURUHI</b>\n\n"
                "✅ <i>Ushbu guruhga yangi mijoz va pochta buyurtmalari avtomatik yuboriladi.</i>\n"
                "🛡 <i>Anti-sharing va nusxa ko'chirish himoyasi (protect_content) yoqilgan.</i>"
            )
            async with self._send_semaphore:
                sent = await self.bot.send_message(
                    chat_id=order_pool_chat_id,
                    text=test_text,
                    parse_mode="HTML",
                    protect_content=True
                )
            msg_id = getattr(sent, "message_id", None) or (sent.get("message_id") if isinstance(sent, dict) else None)
            return {"success": True, "message_id": msg_id, "chat_id": order_pool_chat_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def dispatch_order(
        self,
        order: Dict[str, Any],
        active_drivers: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Main entry point for dispatching a newly harvested order:
        1. Dispatches directly to VIP Order Pool Group with anti-sharing (protect_content=True).
        2. Optionally finds matching drivers along highway corridors and sends DM alerts in parallel.
        """
        pool_msg_id = await self.dispatch_to_order_pool(order)
        order_pool_active = bool(pool_msg_id)

        if active_drivers is None:
            active_drivers = await db.get_active_radar_drivers()

        # If order pool group is active, VIP drivers receive the stream directly in the group.
        # To prevent double notification spam, only send teaser notifications to non-VIP drivers via DM.
        if order_pool_active:
            active_drivers = [d for d in active_drivers if not d.get("is_vip")]

        if not active_drivers:
            return {
                "order_id": order.get("id"),
                "order_pool_sent": order_pool_active,
                "vip_sent": 0,
                "teaser_sent": 0,
                "matched_count": 0
            }

        tasks = []
        matched_drivers = []

        for driver in active_drivers:
            # We match without enforcing VIP so we can send Teaser cards to non-VIP drivers
            match_meta = self.matcher.match_driver(order, driver, enforce_vip=False)
            if not match_meta:
                continue

            driver_id = driver["user_id"]
            is_vip = bool(driver.get("is_vip", False))
            matched_drivers.append(driver_id)

            driver_script = driver.get("script", "lat")
            tasks.append(self.send_to_driver(driver_id, is_vip, order, match_meta, script=driver_script))

        if not tasks:
            return {
                "order_id": order.get("id"),
                "order_pool_sent": bool(pool_msg_id),
                "vip_sent": 0,
                "teaser_sent": 0,
                "matched_count": 0
            }

        start_time = time.perf_counter()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        duration_ms = (time.perf_counter() - start_time) * 1000

        successful_sends = 0
        dispatch_records = []
        for r in results:
            if isinstance(r, tuple) and len(r) == 2:
                success, rec = r
                if success:
                    successful_sends += 1
                if rec:
                    dispatch_records.append(rec)
            elif r is True:
                successful_sends += 1

        if dispatch_records:
            try:
                await db.record_order_dispatches_batch(dispatch_records)
            except Exception as b_err:
                logger.debug(f"Failed to record batch dispatches: {b_err}")

        transit_lag = order.get("transit_lag_seconds")
        lag_str = f" | Transit Lag: {transit_lag:.1f}s" if transit_lag is not None else ""
        logger.info(
            f"[LATENCY] Dispatched Order #{order.get('id')}{lag_str} to {successful_sends}/{len(tasks)} "
            f"matched drivers in {duration_ms:.2f}ms."
        )

        return {
            "order_id": order.get("id"),
            "order_pool_sent": bool(pool_msg_id),
            "matched_count": len(tasks),
            "sent_count": successful_sends,
            "duration_ms": duration_ms
        }

    async def sync_order_status(
        self,
        order_id: int,
        status: str,
        claimer_id: int,
        claimer_name: Optional[str] = None
    ) -> int:
        """
        Synchronizes order status in real-time across all drivers who received the alert.
        - The claimer's message is updated to confirmed '✅ SIZ BAND QILDINGIZ'.
        - Other drivers' messages are updated to locked '🔒 BAND QILINDI' or '❌ BEKOR QILINDI'.
        """
        if not self.bot:
            logger.warning("No bot instance configured for OrderDispatcher.")
            return 0

        dispatches = await db.get_order_dispatches(order_id)
        if not dispatches:
            return 0

        order = await db.get_harvested_order(order_id)

        async def _edit_single(dispatch: Dict[str, Any]):
            driver_id = dispatch["driver_id"]
            msg_id = dispatch["message_id"]
            is_winner = (driver_id == claimer_id)
            driver_script = "lat"
            try:
                driver_script = await db.get_user_script(driver_id)
            except Exception:
                pass

            if is_winner:
                if status == "CLAIMED":
                    banner = (
                        "\n\n<b>✅ СИЗ БУ БУЮРТМАНИ БАНД ҚИЛДИНГИЗ!</b>\n<i>Мижоз билан келишилди. Оқ йўл!</i>"
                        if driver_script == "cyr" else
                        "\n\n<b>✅ SIZ BU BUYURTMANI BAND QILDINGIZ!</b>\n<i>Mijoz bilan kelishildi. Oq yo'l!</i>"
                    )
                    kb = build_order_claimed_keyboard(script=driver_script)
                else:
                    banner = (
                        "\n\n<b>❌ БЕКОР ҚИЛИНДИ</b>\n<i>Сиз мижоз бошқа такси топган деб белгиладингиз.</i>"
                        if driver_script == "cyr" else
                        "\n\n<b>❌ BEKOR QILINDI</b>\n<i>Siz mijoz boshqa taksi topgan deb belgiladingiz.</i>"
                    )
                    kb = build_order_locked_keyboard(status=status, script=driver_script)
            else:
                if status == "CLAIMED":
                    banner = (
                        "\n\n<b>🔒 БАНД ҚИЛИНДИ</b>\n<i>Ушбу буюртма бошқа ҳайдовчи томонидан олинди.</i>"
                        if driver_script == "cyr" else
                        "\n\n<b>🔒 BAND QILINDI</b>\n<i>Ushbu buyurtma boshqa haydovchi tomonidan olindi.</i>"
                    )
                else:
                    banner = (
                        "\n\n<b>❌ БЕКОР ҚИЛИНДИ</b>\n<i>Мижоз аллақачон бошқа транспорт топган.</i>"
                        if driver_script == "cyr" else
                        "\n\n<b>❌ BEKOR QILINDI</b>\n<i>Mijoz allaqachon boshqa transport topgan.</i>"
                    )
                kb = build_order_locked_keyboard(status=status, script=driver_script)

            try:
                if order:
                    if not is_winner and status == "CLAIMED":
                        order_copy = dict(order)
                        order_copy["phone_number"] = "[Band qilingan]"
                        order_copy["telegram_username"] = ""
                        if order_copy.get("raw_text"):
                            order_copy["raw_text"] = mask_raw_text(order_copy["raw_text"], "[Band qilingan]")
                        base_text = self.matcher.format_notification(order_copy, {}, script=driver_script)
                    else:
                        base_text = self.matcher.format_notification(order, {}, script=driver_script)
                else:
                    base_text = "<b>Taksi Xabarchi Buyurtmasi</b>"

                new_text = base_text + banner
                async with self._send_semaphore:
                    await self.bot.edit_message_text(
                        chat_id=driver_id,
                        message_id=msg_id,
                        text=new_text,
                        reply_markup=kb,
                        parse_mode="HTML"
                    )
                return True
            except (TelegramBadRequest, TelegramForbiddenError):
                return False
            except Exception as e:
                logger.debug(f"Could not edit message for driver #{driver_id}: {e}")
                return False

        results = await asyncio.gather(*[_edit_single(d) for d in dispatches], return_exceptions=True)
        synced = sum(1 for r in results if r is True)
        logger.info(f"Synchronized order #{order_id} ({status}) across {synced}/{len(dispatches)} driver cards.")
        return synced


# Singleton dispatcher instance
default_dispatcher = OrderDispatcher()
