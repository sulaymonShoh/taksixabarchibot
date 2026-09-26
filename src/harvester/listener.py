"""
Telethon Real-Time Supergroup Harvester Listener for Taksi Xabarchi v3.0.
Captures incoming messages via MTProto event stream in < 200ms,
applies in-memory deduplication, runs fast NLP parsing, and archives to DB.
"""
import asyncio
import time
import inspect
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Callable, Awaitable, List
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError

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
        self._pulse_task: Optional[asyncio.Task] = None
        self._stale_tracker: Dict[int, Dict[str, Any]] = {}
        self._last_seen_msg_ids: Dict[int, int] = {}
        self._recent_seen_count: int = 0
        self._recent_spam_count: int = 0
        self._recent_dedup_count: int = 0
        self._recent_orders_count: int = 0
        self._summary_task: Optional[asyncio.Task] = None

    async def reload_monitored_groups(self):
        """Refreshes active group IDs and metadata cache from the database."""
        groups = await db.get_harvester_groups(active_only=True)
        self._monitored_chat_ids = [g["group_id"] for g in groups]
        self._monitored_groups_cache = {g["group_id"]: g for g in groups}
        logger.info(f"Harvester listening to {len(self._monitored_chat_ids)} active groups.")

        # Pre-resolve input entities so get_messages never fails with "Could not find input entity"
        if self.client and self.client.is_connected():
            for g in groups:
                cid = g["group_id"]
                username = g.get("username")
                try:
                    target = username or cid
                    await self.client.get_input_entity(target)
                except Exception as e:
                    logger.warning(f"Could not resolve entity for harvester group '{g.get('title')}' ({cid}): {e}")

    async def process_raw_message(
        self,
        chat_id: int,
        chat_title: str,
        text: str,
        sender_username: Optional[str] = None,
        message_id: Optional[int] = None,
        message_link: Optional[str] = None,
        sender_id: Optional[int] = None,
        preparsed_order: Optional[Dict[str, Any]] = None,
        transit_lag_seconds: Optional[float] = None
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
                clean_preview = text.replace('\n', ' ').strip()[:45]
                logger.info(f"[DEDUP] Takroriy xabar e'tiborsiz qoldirildi ('{chat_title}'): \"{clean_preview}...\"")
                return None

            # 2. In-memory NLP parsing (Rejects driver ads, extracts routes)
            order = self.parser.parse(text, author_username=sender_username)
            if not order:
                clean_preview = text.replace('\n', ' ').strip()[:45]
                logger.info(f"[NLP] Haydovchi e'loni/spam rad etildi ('{chat_title}'): \"{clean_preview}...\"")
                return None

        phone = order.get("phone_number")
        orig_id = (order.get("origin") or {}).get("region_id") or (order.get("origin") or {}).get("id")
        dest_id = (order.get("destination") or order.get("dest") or {}).get("region_id") or (order.get("destination") or order.get("dest") or {}).get("id")
        route_tuple = (orig_id, dest_id)
        order_type = order.get("order_type")
        p_count = order.get("passenger_count", 1)
        
        # Second-pass composite deduplication (Identity + Route + Content Similarity)
        if (phone or sender_id) and self.dedup.is_duplicate(
            text,
            phone=phone,
            sender_id=sender_id,
            route=route_tuple,
            order_type=order_type,
            passenger_count=p_count
        ):
            contact_label = f"Raqam ({phone})" if phone else f"Foydalanuvchi ({sender_id})"
            logger.info(f"[DEDUP] {contact_label} bo'yicha takroriy xabar e'tiborsiz qoldirildi ('{chat_title}')")
            return None

        # Record into deduplication cache
        msg_hash = self.dedup.record(
            text,
            phone=phone,
            sender_id=sender_id,
            route=route_tuple,
            order_type=order_type,
            passenger_count=p_count
        )
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
        if transit_lag_seconds is not None:
            order["transit_lag_seconds"] = transit_lag_seconds

        # 3. Persist order to SQLite database
        order_id = await db.save_harvested_order(order)
        if order_id is None:
            # Hash already existed in DB
            return None

        self._recent_orders_count += 1
        order["id"] = order_id
        orig_name = (order.get("origin") or {}).get("name", "?")
        dest_name = (order.get("destination") or order.get("dest") or {}).get("name", "?")
        lag_str = f" | Transit Lag: {transit_lag_seconds:.1f}s" if transit_lag_seconds is not None else ""
        logger.info(
            f"New Order #{order_id} captured from '{chat_title}': "
            f"[{order['order_type']}] {orig_name} -> "
            f"{dest_name} ({phone or 'No phone'}){lag_str}"
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
            raw_text = getattr(event, "raw_text", None) or getattr(event, "message", "") or ""
            if len(raw_text.strip()) < 5:
                return

            message_id = getattr(event, "id", None)
            if message_id:
                if message_id > self._last_seen_msg_ids.get(chat_id, 0):
                    self._last_seen_msg_ids[chat_id] = message_id

            # Record raw message seen in group telemetry buffer
            self.record_activity(chat_id, seen=1)
            self._recent_seen_count += 1

            # 1. Message freshness guard: Drop messages older than 300 seconds (5 minutes)
            transit_lag_seconds: Optional[float] = None
            msg_date = getattr(event, "date", None)
            if msg_date:
                now_utc = datetime.now(timezone.utc)
                if getattr(msg_date, "tzinfo", None) is None:
                    msg_date = msg_date.replace(tzinfo=timezone.utc)
                transit_lag_seconds = max(0.0, (now_utc - msg_date).total_seconds())
                if transit_lag_seconds > 300:  # 5-minute guard threshold
                    logger.debug(
                        f"Skipping stale message #{getattr(event, 'id', '?')} from group {chat_id} "
                        f"(Transit lag: {transit_lag_seconds:.1f}s > 300s threshold)"
                    )
                    self._record_stale(chat_id, transit_lag_seconds)
                    return

            # 2. Fast in-memory deduplication check (<0.05ms)
            if self.dedup.is_duplicate(raw_text):
                self._recent_dedup_count += 1
                group_info = self._monitored_groups_cache.get(chat_id, {})
                title = group_info.get("title") or str(chat_id)
                clean_preview = raw_text.replace('\n', ' ').strip()[:45]
                logger.info(f"[DEDUP] Takroriy xabar e'tiborsiz qoldirildi ('{title}'): \"{clean_preview}...\"")
                return

            # 3. Fast in-memory NLP parsing (<0.06ms)
            # Rejects 95%+ of messages (driver ads, spam, greetings) immediately!
            order = self.parser.parse(raw_text)
            if not order:
                self._recent_spam_count += 1
                # Driver ad / spam rejected!
                self.record_activity(chat_id, spam=1)
                group_info = self._monitored_groups_cache.get(chat_id, {})
                title = group_info.get("title") or str(chat_id)
                clean_preview = raw_text.replace('\n', ' ').strip()[:45]
                logger.debug(f"[NLP] Haydovchi e'loni/spam rad etildi ('{title}'): \"{clean_preview}...\"")
                return

            # Message is a verified passenger or cargo order!
            # Resolve group metadata from in-memory cache with zero network calls
            group_info = self._monitored_groups_cache.get(chat_id, {})
            chat_obj = getattr(event, "chat", None)
            chat_title = group_info.get("title") or getattr(chat_obj, "title", str(chat_id))
            chat_username = group_info.get("username") or getattr(chat_obj, "username", None)
            if chat_username and chat_username.startswith("@"):
                chat_username = chat_username[1:]

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
                preparsed_order=order,
                transit_lag_seconds=transit_lag_seconds
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

    def _record_stale(self, chat_id: int, lag: float):
        """Buffers stale message events to emit a single aggregated summary log instead of flooding."""
        now = time.time()
        info = self._stale_tracker.get(chat_id)
        if not info or (now - info.get("last_log", 0) > 3.0):
            self._stale_tracker[chat_id] = {
                "count": 1,
                "max_lag": lag,
                "last_log": now
            }
            asyncio.create_task(self._delayed_stale_summary(chat_id))
        else:
            info["count"] += 1
            info["max_lag"] = max(info["max_lag"], lag)
            info["last_log"] = now

    async def _delayed_stale_summary(self, chat_id: int):
        """Emits an aggregated summary for a burst of stale messages after a brief delay."""
        await asyncio.sleep(1.0)
        info = self._stale_tracker.pop(chat_id, None)
        if info and info["count"] > 0:
            group_info = self._monitored_groups_cache.get(chat_id, {})
            title = group_info.get("title") or str(chat_id)
            c = info["count"]
            max_min = info["max_lag"] / 60.0
            logger.info(f"[STALE]     {c} ta eskirgan xabar o'tkazib yuborildi ('{title}' | Lag: ~{max_min:.1f} daqiqa)")

    async def _active_poller_loop(self):
        """
        Hybrid Active Poller:
        Sweeps all monitored taxi supergroups on a 60-second cycle using bounded concurrency (Semaphore=4).
        Fetches live messages directly via Telegram MTProto RPC (messages.getHistory).
        Guarantees orders are captured in < 60s even when Telegram DC delays socket push events.
        """
        sem = asyncio.Semaphore(4)
        while self._is_running:
            try:
                sweep_start = time.time()
                cycle_new_msgs = 0
                if not self._is_running or not self.client or not self.client.is_connected():
                    await asyncio.sleep(5)
                    continue

                chat_ids = list(self._monitored_chat_ids)
                total_groups = len(chat_ids)
                stagger = max(0.1, min(1.0, 30.0 / max(1, total_groups)))

                async def _sweep_single_group(cid: int):
                    nonlocal cycle_new_msgs
                    async with sem:
                        try:
                            msgs_call = self.client.get_messages(cid, limit=20)
                            if inspect.isawaitable(msgs_call):
                                msgs = await asyncio.wait_for(msgs_call, timeout=5.0)
                            else:
                                msgs = msgs_call

                            if msgs:
                                last_known_id = self._last_seen_msg_ids.get(cid)

                                # First time inspecting this group: establish baseline watermark
                                if last_known_id is None:
                                    max_id = max(getattr(m, "id", 0) for m in msgs)
                                    self._last_seen_msg_ids[cid] = max_id
                                    # Only process messages that are ACTUALLY fresh (<300s) right now;
                                    # silently ignore historical messages from hours/days ago without false [STALE] spam
                                    for msg in reversed(msgs):
                                        msg_date = getattr(msg, "date", None)
                                        if msg_date:
                                            now_utc = datetime.now(timezone.utc)
                                            if getattr(msg_date, "tzinfo", None) is None:
                                                msg_date = msg_date.replace(tzinfo=timezone.utc)
                                            if (now_utc - msg_date).total_seconds() <= 300:
                                                cycle_new_msgs += 1
                                                asyncio.create_task(self._process_event(msg, cid))
                                else:
                                    # Normal sweep: ONLY process messages strictly NEWER than last_known_id!
                                    new_msgs = [m for m in msgs if getattr(m, "id", 0) > last_known_id]
                                    if new_msgs:
                                        cycle_new_msgs += len(new_msgs)
                                        self._last_seen_msg_ids[cid] = max(getattr(m, "id", 0) for m in new_msgs)
                                        for msg in reversed(new_msgs):
                                            asyncio.create_task(self._process_event(msg, cid))

                        except FloodWaitError as e:
                            logger.warning(f"Telegram FloodWait in harvester active poller: sleeping {e.seconds}s")
                            await asyncio.sleep(e.seconds)
                        except asyncio.CancelledError:
                            raise
                        except Exception as e:
                            logger.warning(f"Harvester active poller error for group {cid}: {e}")

                sweep_tasks = []
                for cid in chat_ids:
                    if not self._is_running:
                        break
                    sweep_tasks.append(asyncio.create_task(_sweep_single_group(cid)))
                    await asyncio.sleep(stagger)

                if sweep_tasks:
                    await asyncio.gather(*sweep_tasks, return_exceptions=True)

                # Rest for the remainder of the 60-second cycle
                elapsed = time.time() - sweep_start
                sleep_remainder = max(5.0, 60.0 - elapsed)
                logger.info(
                    f"[POLLER]    Cycle finished in {elapsed:.1f}s | "
                    f"Checked {len(chat_ids)} groups | New msgs: {cycle_new_msgs} | "
                    f"Sleeping {sleep_remainder:.1f}s"
                )
                await asyncio.sleep(sleep_remainder)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Unexpected error in harvester active poller loop: {e}", exc_info=True)
                await asyncio.sleep(5)

    async def _summary_loop(self):
        """Emits a 60-second summary of harvester throughput without emojis."""
        while self._is_running:
            try:
                await asyncio.sleep(60)
                if not self._is_running:
                    break
                seen = self._recent_seen_count
                spam = self._recent_spam_count
                dedup = self._recent_dedup_count
                orders = self._recent_orders_count

                self._recent_seen_count = 0
                self._recent_spam_count = 0
                self._recent_dedup_count = 0
                self._recent_orders_count = 0

                logger.info(
                    f"[HARVESTER] Summary: Seen: {seen} msgs | "
                    f"Driver Ads/Spam: {spam} | Duplicates: {dedup} | "
                    f"Orders Captured: {orders}"
                )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in harvester summary loop: {e}")

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
        """Starts the harvester listener, stats flush loop, active poller loop, and 60s summary loop."""
        self._is_running = True
        await self.reload_monitored_groups()
        self.setup_event_handlers()
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._flush_loop())
        if self._pulse_task is None or self._pulse_task.done():
            self._pulse_task = asyncio.create_task(self._active_poller_loop())
        if self._summary_task is None or self._summary_task.done():
            self._summary_task = asyncio.create_task(self._summary_loop())
        logger.info("HarvesterListener started successfully.")

    async def stop(self):
        """Stops the harvester listener, active poller loop, summary loop, and flushes pending telemetry."""
        self._is_running = False
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            self._flush_task = None
        if self._pulse_task and not self._pulse_task.done():
            self._pulse_task.cancel()
            self._pulse_task = None
        if self._summary_task and not self._summary_task.done():
            self._summary_task.cancel()
            self._summary_task = None
        await self.flush_stats_buffer()
        logger.info("HarvesterListener stopped.")
