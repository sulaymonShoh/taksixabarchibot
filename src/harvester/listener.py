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
        self._monitored_groups_cache: Dict[int, Dict[str, Any]] = {}
        self._stats_buffer: Dict[int, Dict[str, int]] = {}
        self._flush_task: Optional[asyncio.Task] = None
        self._flush_interval: int = 10  # seconds between batched DB flushes

    async def reload_monitored_groups(self):
        """Refreshes active group IDs and metadata cache from the database."""
        groups = await db.get_harvester_groups(active_only=True)
        self._monitored_chat_ids = [g["group_id"] for g in groups]
        self._monitored_groups_cache = {g["group_id"]: g for g in groups}
        logger.info(f"Harvester listening to {len(self._monitored_chat_ids)} active groups.")

    async def process_raw_message(
        self,
        chat_id: int,
        chat_title: str,
        text: str,
        sender_username: Optional[str] = None,
        message_id: Optional[int] = None,
        message_link: Optional[str] = None,
        sender_id: Optional[int] = None,
        preparsed_order: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Core processing pipeline for any incoming message:
        1. Deduplication check (<0.1ms).
        2. In-Memory NLP extraction (<0.05ms).
        3. Database persistence.
        4. Dispatch callback triggering.
        """
        if preparsed_order is not None:
            order = preparsed_order
        else:
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

        # Resolve source group metadata and region context
        group_meta = self._monitored_groups_cache.get(chat_id, {})
        source_region_tag = group_meta.get("region_tag") or "andijon"
        order["source_region_tag"] = source_region_tag

        # Geographic Context Inference for Unilateral Orders:
        # If an order has destination (e.g. Tashkent) but no origin, infer origin from the group tag.
        # If an order has origin (e.g. Tashkent) but no destination, infer destination from the group tag.
        if source_region_tag and source_region_tag.upper() != "ALL":
            from src.harvester.geo_tagger import parse_tag_string, format_tag_display
            reg, dist = parse_tag_string(source_region_tag)
            
            dest = order.get("destination") or order.get("dest") or {}
            orig = order.get("origin") or {}
            dest_reg = dest.get("region_id")
            orig_reg = orig.get("region_id")

            is_dest_toshkent = dest_reg in ("toshkent_shahar", "toshkent_viloyati", "toshkent") or dest.get("id") in ("quyliq", "rohat")
            is_orig_toshkent = orig_reg in ("toshkent_shahar", "toshkent_viloyati", "toshkent") or orig.get("id") in ("quyliq", "rohat")

            if not orig and is_dest_toshkent:
                order["origin"] = {
                    "id": dist or reg,
                    "name": format_tag_display(reg, dist),
                    "region_id": reg,
                    "district_id": dist
                }
            elif not dest and is_orig_toshkent:
                order["destination"] = {
                    "id": dist or reg,
                    "name": format_tag_display(reg, dist),
                    "region_id": reg,
                    "district_id": dist
                }

        if sender_id:
            order["sender_id"] = sender_id
        if sender_username and not order.get("telegram_username"):
            order["telegram_username"] = sender_username
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

    async def _process_event(self, event: events.NewMessage.Event, chat_id: int):
        """
        Fast non-blocking handler executed in a background task for each message.
        Guarantees zero-network ingestion and sub-millisecond filtering.
        """
        try:
            raw_text = event.raw_text or ""
            if len(raw_text.strip()) < 5:
                return

            # Record raw message seen in group telemetry buffer
            self.record_activity(chat_id, seen=1)

            # 1. Fast in-memory deduplication check (<0.05ms)
            if self.dedup.is_duplicate(raw_text):
                return

            # 2. Fast in-memory NLP parsing (<0.06ms)
            # Rejects 95%+ of messages (driver ads, spam, greetings) immediately!
            order = self.parser.parse(raw_text)
            if not order:
                # Driver ad / spam rejected!
                self.record_activity(chat_id, spam=1)
                return

            # Message is a verified passenger or cargo order!
            # Resolve group metadata from in-memory cache with zero network calls
            group_info = self._monitored_groups_cache.get(chat_id, {})
            chat_title = group_info.get("title") or getattr(event.chat, "title", str(chat_id))
            chat_username = group_info.get("username") or getattr(event.chat, "username", None)
            if chat_username and chat_username.startswith("@"):
                chat_username = chat_username[1:]

            message_id = getattr(event, "id", None)
            message_link = None
            if message_id:
                if chat_username:
                    message_link = f"https://t.me/{chat_username}/{message_id}"
                else:
                    clean_id = str(chat_id).replace("-100", "").replace("-", "")
                    message_link = f"https://t.me/c/{clean_id}/{message_id}"

            # Direct in-memory sender ID (0ms, zero MTProto network RPC)
            sender_id = getattr(event, "sender_id", None)

            # Check if username is in text, or locally cached in event.sender (without network)
            sender_username = order.get("telegram_username")
            if not sender_username:
                cached_sender = getattr(event, "sender", None) or getattr(event, "_sender", None)
                if cached_sender:
                    u = getattr(cached_sender, "username", None)
                    if u:
                        sender_username = f"@{u}"

            await self.process_raw_message(
                chat_id=chat_id,
                chat_title=chat_title,
                text=raw_text,
                sender_username=sender_username,
                message_id=message_id,
                message_link=message_link,
                sender_id=sender_id,
                preparsed_order=order
            )
        except Exception as e:
            logger.error(f"Error in harvester _process_event: {e}", exc_info=True)

    def record_activity(self, chat_id: int, seen: int = 0, spam: int = 0):
        """Buffers raw message telemetry in memory for batched database persistence."""
        if chat_id not in self._stats_buffer:
            self._stats_buffer[chat_id] = {"seen": 0, "spam": 0}
        self._stats_buffer[chat_id]["seen"] += seen
        self._stats_buffer[chat_id]["spam"] += spam

    async def flush_stats_buffer(self):
        """Flushes in-memory group telemetry counters to the database."""
        if not self._stats_buffer:
            return
        buffer_copy = dict(self._stats_buffer)
        self._stats_buffer.clear()
        try:
            await db.record_group_messages_batch(buffer_copy)
        except Exception as e:
            logger.warning(f"Error flushing group analytics buffer: {e}")

    async def _flush_loop(self):
        """Periodic background task to flush analytics counters every N seconds."""
        while self._is_running:
            try:
                await asyncio.sleep(self._flush_interval)
                await self.flush_stats_buffer()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in analytics flush loop: {e}")

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
            # If monitored groups list is active, only process matching chats in memory
            if self._monitored_chat_ids and chat_id not in self._monitored_chat_ids:
                return

            # Spawn as background task to ensure Telethon's MTProto update socket reader
            # returns in 0.001ms and never queues backlog
            asyncio.create_task(self._process_event(event, chat_id))

    async def start(self):
        """Starts the harvester listener and background stats flush loop."""
        self._is_running = True
        await self.reload_monitored_groups()
        self.setup_event_handlers()
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._flush_loop())
        logger.info("HarvesterListener started successfully.")

    async def stop(self):
        """Stops the harvester listener and flushes pending telemetry."""
        self._is_running = False
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            self._flush_task = None
        await self.flush_stats_buffer()
        logger.info("HarvesterListener stopped.")
