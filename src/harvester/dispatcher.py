"""
Real-Time Order Dispatcher Grid & Paywall Teaser Delivery for Taksi Xabarchi v3.0.
Dispatches matching passenger and cargo orders directly to active drivers via Telegram DM.
- VIP Drivers: Receive full uncensored client details in sub-second speed (< 500ms).
- Expired / Free Drivers: Receive masked Paywall Teasers driving VIP subscription conversions.
"""
import re
import asyncio
import time
from typing import Dict, Any, List, Optional
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

def mask_raw_text(text: str) -> str:
    """Replaces phone numbers in raw client text with masked placeholders."""
    return re.sub(
        r"(\+?998[\s\-]?)?\d{2}[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}",
        "[VIP raqam yashirilgan]",
        text
    )

def build_order_action_keyboard(
    order_id: int,
    username: Optional[str] = None,
    is_vip: bool = True
) -> InlineKeyboardMarkup:
    """Constructs Telegram inline action buttons for the order alert."""
    keyboard = []

    if is_vip:
        top_row = []
        if username:
            clean_user = username.replace("@", "").strip()
            top_row.append(InlineKeyboardButton(text="💬 Telegram profil", url=f"https://t.me/{clean_user}"))
        if top_row:
            keyboard.append(top_row)

        keyboard.append([
            InlineKeyboardButton(text="⚡️ Buyurtmani olish (Band qilish)", callback_data=f"claim_order_{order_id}")
        ])
    else:
        # Paywall Teaser Keyboard -> Direct 1-tap conversion button
        keyboard.append([
            InlineKeyboardButton(text="⭐️ VIP Obunani faollashtirish (25,000 so'm)", callback_data="show_plans")
        ])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


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

    def format_vip_notification(self, order: Dict[str, Any], match_meta: Dict[str, Any]) -> str:
        """Formats full uncensored order alert for active VIP drivers."""
        return self.matcher.format_notification(order, match_meta)

    def format_teaser_notification(self, order: Dict[str, Any], match_meta: Dict[str, Any]) -> str:
        """Formats masked paywall teaser for expired/free drivers."""
        origin = order.get("origin") or {}
        dest = order.get("destination") or order.get("dest") or {}

        orig_name = origin.get("name") or order.get("origin_district") or order.get("origin_region") or "Noma'lum"
        dest_name = dest.get("name") or order.get("dest_district") or order.get("dest_region") or "Toshkent"
        order_type = order.get("order_type", "PASSENGER")
        phone = order.get("phone_number")
        username = order.get("telegram_username")
        raw_text = order.get("raw_text", "").strip()
        count = order.get("passenger_count", 1)

        masked_phone = mask_phone_number(phone)
        masked_user = mask_telegram_username(username)
        masked_text = mask_raw_text(raw_text)

        type_icon = "👤" if order_type == "PASSENGER" else "📦"
        type_label = f"{count} kishi (Yo'lovchi)" if order_type == "PASSENGER" else "Pochta / Yuk"

        lines = [
            "🔒 <b>YANGI BUYURTMA! [Radar Teaser]</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            f"📍 <b>Yo'nalish:</b> {orig_name} ➡️ {dest_name}",
            f"{type_icon} <b>Turi:</b> {type_label}",
            f"📞 <b>Telefon:</b> <code>{masked_phone}</code>",
        ]

        if masked_user:
            lines.append(f"💬 <b>Telegram:</b> {masked_user}")

        lines.extend([
            "━━━━━━━━━━━━━━━━━━━━",
            f"📝 <i>\"{masked_text[:160]}\"</i>",
            "━━━━━━━━━━━━━━━━━━━━",
            "⚠️ <b>DIQQAT:</b> Mijoz telefon raqami va profilini to'liq ko'rish uchun <b>VIP obunani</b> faollashtiring!",
            "",
            "💡 <i>VIP haydovchilar buyurtmalarni guruhga chiqishi bilanoq 0.5 soniyada to'liq qabul qilishmoqda!</i>"
        ])

        return "\n".join(lines)

    async def send_to_driver(
        self,
        driver_id: int,
        is_vip: bool,
        order: Dict[str, Any],
        match_meta: Dict[str, Any]
    ) -> bool:
        """Dispatches an alert to a single driver."""
        if not self.bot:
            logger.warning("No bot instance configured for OrderDispatcher.")
            return False

        order_id = order.get("id", 0)
        username = order.get("telegram_username")
        sound_alert = match_meta.get("sound_alerts", True)

        try:
            if is_vip:
                text = self.format_vip_notification(order, match_meta)
                kb_markup = build_order_action_keyboard(order_id, username, is_vip=True)
                await self.bot.send_message(
                    chat_id=driver_id,
                    text=text,
                    reply_markup=kb_markup,
                    parse_mode="HTML",
                    disable_notification=not sound_alert
                )
                self._total_vip_dispatched += 1
                return True
            else:
                # Teaser check: rate limit
                now = time.time()
                last_sent = self._teaser_last_sent.get(driver_id, 0)
                if now - last_sent < self.teaser_cooldown_seconds:
                    return False

                text = self.format_teaser_notification(order, match_meta)
                kb_markup = build_order_action_keyboard(order_id, username, is_vip=False)
                await self.bot.send_message(
                    chat_id=driver_id,
                    text=text,
                    reply_markup=kb_markup,
                    parse_mode="HTML",
                    disable_notification=True
                )
                self._teaser_last_sent[driver_id] = now
                self._total_teasers_dispatched += 1
                return True

        except (TelegramForbiddenError, TelegramBadRequest) as e:
            logger.debug(f"Could not send order #{order_id} to driver #{driver_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Error sending order #{order_id} to driver #{driver_id}: {e}")
            return False

    async def dispatch_order(
        self,
        order: Dict[str, Any],
        active_drivers: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Main entry point for dispatching a newly harvested order.
        Finds matching drivers along highway corridors and sends alerts in parallel.
        """
        if active_drivers is None:
            active_drivers = await db.get_active_radar_drivers()

        if not active_drivers:
            return {"vip_sent": 0, "teaser_sent": 0, "matched_count": 0}

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

            tasks.append(self.send_to_driver(driver_id, is_vip, order, match_meta))

        if not tasks:
            return {"vip_sent": 0, "teaser_sent": 0, "matched_count": 0}

        start_time = time.perf_counter()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        duration_ms = (time.perf_counter() - start_time) * 1000

        successful_sends = sum(1 for r in results if r is True)
        logger.info(
            f"Dispatched Order #{order.get('id')} to {successful_sends}/{len(tasks)} "
            f"matched drivers in {duration_ms:.2f}ms."
        )

        return {
            "order_id": order.get("id"),
            "matched_count": len(tasks),
            "sent_count": successful_sends,
            "duration_ms": duration_ms
        }


# Singleton dispatcher instance
default_dispatcher = OrderDispatcher()
