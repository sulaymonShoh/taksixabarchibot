"""
Telethon Real-Time Supergroup Harvester Listener for Taksi Xabarchi v3.0.
Captures incoming messages via MTProto event stream in < 200ms,
applies in-memory deduplication, runs fast NLP parsing, and archives to DB.
"""
import asyncio
from typing import Dict, Any, Optional, Callable, Awaitable, List
from telethon import TelegramClient, events

from src import database as db
from src.harvester.nlp_engine import OrderParser
from src.harvester.dedup import Deduplicator, default_deduplicator
from src.logger import setup_logger

logger = setup_logger("harvester_listener")

class HarvesterListener:
    """
    Asynchronous event listener monitoring target Telegram taxi supergroups.
    """

    def __init__(
        self,
        client: Optional[TelegramClient] = None,
        parser: Optional[OrderParser] = None,
        deduplicator: Optional[Deduplicator] = None,
        on_order_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None
    ):
        self.client = client
        self.parser = parser or OrderParser()
        self.dedup = deduplicator or default_deduplicator
        if on_order_callback is not None:
            self.on_order_callback = on_order_callback
        else:
            from src.harvester.dispatcher import default_dispatcher
            self.on_order_callback = default_dispatcher.dispatch_order
        self._is_running = False
        self._monitored_chat_ids: List[int] = []

    async def reload_monitored_groups(self):
        """Refreshes active group IDs from the database."""
        groups = await db.get_harvester_groups(active_only=True)
        self._monitored_chat_ids = [g["group_id"] for g in groups]
        logger.info(f"Harvester listening to {len(self._monitored_chat_ids)} active groups.")

    async def process_raw_message(
        self,
        chat_id: int,
        chat_title: str,
        text: str,
        sender_username: Optional[str] = None,
        message_id: Optional[int] = None,
        message_link: Optional[str] = None,
        sender_id: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Core processing pipeline for any incoming message:
        1. Deduplication check (<0.1ms).
        2. In-Memory NLP extraction (<0.05ms).
        3. Database persistence.
        4. Dispatch callback triggering.
        """
        if not text or len(text.strip()) < 5:
            return None

        # 1. Deduplication check
        if self.dedup.is_duplicate(text):
            return None

        # 2. In-memory NLP parsing (Rejects driver ads, extracts routes)
        order = self.parser.parse(text, author_username=sender_username)
        if not order:
            return None

        phone = order.get("phone_number")
        
        # Second-pass phone-based deduplication
        if phone and self.dedup.is_duplicate(text, phone=phone):
            return None

        # Record into deduplication cache
        msg_hash = self.dedup.record(text, phone=phone)
        order["message_hash"] = msg_hash
        order["source_group_id"] = chat_id
        order["source_group_title"] = chat_title
        if sender_id:
            order["sender_id"] = sender_id
        if message_id:
            order["message_id"] = message_id
        if message_link:
            order["message_link"] = message_link

        # 3. Persist order to SQLite database
        order_id = await db.save_harvested_order(order)
        if order_id is None:
            # Hash already existed in DB
            return None

        order["id"] = order_id
        orig_name = (order.get("origin") or {}).get("name", "?")
        dest_name = (order.get("destination") or order.get("dest") or {}).get("name", "?")
        logger.info(
            f"New Order #{order_id} captured from '{chat_title}': "
            f"[{order['order_type']}] {orig_name} -> "
            f"{dest_name} ({phone or 'No phone'})"
        )

        # 4. Trigger dispatch callback for active drivers (Stage 3 & 4)
        if self.on_order_callback:
            try:
                await self.on_order_callback(order)
            except Exception as e:
                logger.error(f"Error in on_order_callback: {e}")

        return order

    def setup_event_handlers(self):
        """Attaches Telethon events.NewMessage handler to the client."""
        if not self.client:
            logger.warning("No Telethon client provided to HarvesterListener.")
            return

        @self.client.on(events.NewMessage)
        async def _handle_new_message(event: events.NewMessage.Event):
            if not self._is_running:
                return

            chat_id = event.chat_id
            # If monitored groups list is active, only process matching chats
            if self._monitored_chat_ids and chat_id not in self._monitored_chat_ids:
                return

            chat = await event.get_chat()
            chat_title = getattr(chat, "title", str(chat_id))
            chat_username = getattr(chat, "username", None)
            sender = await event.get_sender()
            sender_id = getattr(sender, "id", None) or getattr(event, "sender_id", None)
            sender_username = getattr(sender, "username", None)
            if sender_username:
                sender_username = f"@{sender_username}"

            message_id = getattr(event, "id", None)
            message_link = None
            if message_id:
                if chat_username:
                    message_link = f"https://t.me/{chat_username}/{message_id}"
                else:
                    clean_id = str(chat_id).replace("-100", "").replace("-", "")
                    message_link = f"https://t.me/c/{clean_id}/{message_id}"

            raw_text = event.raw_text or ""
            await self.process_raw_message(
                chat_id=chat_id,
                chat_title=chat_title,
                text=raw_text,
                sender_username=sender_username,
                message_id=message_id,
                message_link=message_link,
                sender_id=sender_id
            )

    async def start(self):
        """Starts the harvester listener."""
        self._is_running = True
        await self.reload_monitored_groups()
        self.setup_event_handlers()
        logger.info("HarvesterListener started successfully.")

    async def stop(self):
        """Stops the harvester listener."""
        self._is_running = False
        logger.info("HarvesterListener stopped.")
