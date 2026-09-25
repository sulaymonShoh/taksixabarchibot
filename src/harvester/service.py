"""
HarvesterService: Manages the lifecycle of the dedicated Telethon userbot client,
group entity resolution, auto-joining, and connects real-time MTProto streams
to HarvesterListener.
"""
import os
import asyncio
import inspect
import contextlib
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from telethon import TelegramClient
from telethon.utils import get_peer_id
from telethon.tl.functions import PingRequest
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest, CheckChatInviteRequest
from telethon.errors import UserAlreadyParticipantError

from src.config import API_ID, API_HASH, SESSIONS_DIR, HARVESTER_SESSION_NAME, ADMIN_ID
from src.harvester.listener import HarvesterListener
from src.harvester.geo_tagger import detect_group_region
from src import database as db
from src.logger import setup_logger

logger = setup_logger("harvester_service")

class HarvesterService:
    def __init__(self, session_name: Optional[str] = None):
        self.session_name = session_name or HARVESTER_SESSION_NAME
        self.session_path = os.path.join(SESSIONS_DIR, self.session_name)
        self.client: Optional[TelegramClient] = None
        self.listener: Optional[HarvesterListener] = None
        self._user_info: Optional[Dict[str, Any]] = None
        self._is_running = False

        # Watchdog & Supervisor telemetry
        self._status: str = "IDLE"  # "ONLINE", "RECONNECTING", "OFFLINE", "ERROR", "IDLE"
        self._watchdog_task: Optional[asyncio.Task] = None
        self._watchdog_active: bool = False
        self._watchdog_interval: int = 20  # seconds between health checks
        self._consecutive_failures: int = 0
        self._last_heartbeat: Optional[datetime] = None
        self._last_error: Optional[str] = None
        self._alert_sent: bool = False
        self.bot: Any = None  # aiogram Bot instance for admin alerting

    def is_session_available(self) -> bool:
        """Returns True if the .session file exists on disk."""
        return os.path.exists(f"{self.session_path}.session") or os.path.exists(self.session_path)

    def is_connected(self) -> bool:
        """Returns True if userbot client is connected and authorized."""
        return bool(self.client and self.client.is_connected() and self._is_running)

    async def start(self) -> bool:
        """Connects the userbot client, starts the real-time HarvesterListener and watchdog."""
        self.start_watchdog()
        if self.is_connected():
            return True

        if not self.is_session_available():
            self._status = "OFFLINE"
            logger.warning(
                f"Harvester session file '{self.session_path}.session' not found. "
                "Harvester userbot is idle. Session not connected."
            )
            return False

        try:
            self.client = TelegramClient(
                self.session_path,
                API_ID,
                API_HASH,
                timeout=15,
                request_retries=3,
                connection_retries=None,
                retry_delay=1,
                auto_reconnect=True,
                flood_sleep_threshold=60
            )
            await self.client.connect()

            if not await self.client.is_user_authorized():
                self._status = "ERROR"
                self._last_error = "Harvester userbot session is not authorized"
                logger.warning("Harvester userbot session is not authorized. Please log in.")
                await self.client.disconnect()
                self.client = None
                return False

            me = await self.client.get_me()
            self._user_info = {
                "id": me.id,
                "first_name": me.first_name,
                "last_name": me.last_name,
                "username": f"@{me.username}" if me.username else None,
                "phone": getattr(me, "phone", None)
            }
            logger.info(
                f"✅ Harvester Userbot connected: {me.first_name} "
                f"({self._user_info['username'] or self._user_info['phone'] or me.id})"
            )

            # Foreground dialog warmup: loads entity cache and registers active MTProto viewport with DC
            with contextlib.suppress(Exception):
                await self.client.get_dialogs(limit=50)

            # Initialize and start the HarvesterListener
            self.listener = HarvesterListener(client=self.client)
            await self.listener.start()
            self._is_running = True
            self._status = "ONLINE"
            self._consecutive_failures = 0
            self._last_heartbeat = datetime.utcnow()
            self._last_error = None

            # Start background watchdog supervisor
            self.start_watchdog()
            return True
        except Exception as e:
            self._status = "ERROR"
            self._last_error = str(e)
            logger.error(f"Failed to start HarvesterService: {e}", exc_info=True)
            self._is_running = False
            return False

    async def stop(self):
        """Stops the harvester listener, supervisor watchdog, and disconnects client."""
        self._is_running = False
        self._status = "OFFLINE"
        self.stop_watchdog()
        if self.listener:
            with contextlib.suppress(Exception):
                res = self.listener.stop()
                if inspect.isawaitable(res):
                    await res
        if self.client and self.client.is_connected():
            with contextlib.suppress(Exception):
                await self.client.disconnect()
        logger.info("HarvesterService stopped.")

    def start_watchdog(self):
        """Starts background supervisor watchdog if not already running."""
        self._watchdog_active = True
        if self._watchdog_task is None or self._watchdog_task.done():
            self._watchdog_task = asyncio.create_task(self._watchdog_loop())
            logger.info("Harvester watchdog supervisor started.")

    def stop_watchdog(self):
        """Cancels background supervisor watchdog."""
        self._watchdog_active = False
        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()
            self._watchdog_task = None
            logger.info("Harvester watchdog supervisor stopped.")

    async def _watchdog_loop(self):
        """
        Periodic watchdog loop that inspects the health of Harvester userbot and listener.
        Triggers auto-reconnection if the client socket drops or listener stops.
        Alerts SuperAdmin on repeated persistent failures.
        """
        while self._watchdog_active:
            try:
                await asyncio.sleep(self._watchdog_interval)
                if not self._watchdog_active:
                    break

                if not self.is_session_available():
                    self._status = "OFFLINE"
                    self._last_error = "Session file not found"
                    self._consecutive_failures += 1
                    continue

                healthy = False
                if self.client and self.client.is_connected():
                    try:
                        # Active MTProto keepalive: sends raw ping packet through the socket to Telegram DC.
                        # Keeps NAT router port mappings open and detects dropped sockets in < 5 seconds.
                        ping_call = self.client(PingRequest(ping_id=int(datetime.now(timezone.utc).timestamp())))
                        if inspect.isawaitable(ping_call):
                            await asyncio.wait_for(ping_call, timeout=5.0)
                        elif hasattr(self.client, "is_user_authorized"):
                            await self.client.is_user_authorized()

                        if self.listener and self.listener._is_running:
                            healthy = True
                    except Exception as e:
                        logger.warning(f"Harvester MTProto active ping failed: {e}")
                        healthy = False

                if healthy:
                    self._status = "ONLINE"
                    self._last_heartbeat = datetime.now(timezone.utc)
                    self._consecutive_failures = 0
                    if self._alert_sent:
                        await self._notify_admin_recovery()
                        self._alert_sent = False
                else:
                    self._consecutive_failures += 1
                    logger.warning(
                        f"⚠️ Harvester watchdog detected unhealthy state! "
                        f"(Failures: {self._consecutive_failures}, Status: {self._status})"
                    )

                    if self._consecutive_failures >= 3 and not self._alert_sent:
                        await self._notify_admin_disconnect()
                        self._alert_sent = True

                    await self.reconnect()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Unexpected error in harvester watchdog loop: {e}", exc_info=True)

    async def reconnect(self, backoff_seconds: Optional[int] = None) -> bool:
        """
        Attempts clean reconnection of the userbot client and restarts listener.
        Uses exponential backoff based on consecutive failures unless specified.
        """
        self._status = "RECONNECTING"

        if backoff_seconds is None:
            # 5s, 10s, 20s, up to 60s
            backoff_seconds = min(60, 5 * (2 ** max(0, min(self._consecutive_failures - 1, 4))))

        if backoff_seconds > 0:
            logger.info(f"Harvester reconnecting in {backoff_seconds}s (attempt #{self._consecutive_failures})...")
            await asyncio.sleep(backoff_seconds)

        # 1. Cleanly disconnect previous client if exists
        try:
            if self.listener:
                await self.listener.stop()
            if self.client:
                with contextlib.suppress(Exception):
                    await self.client.disconnect()
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.debug(f"Error during harvester client cleanup: {e}")
        finally:
            self.client = None
            self.listener = None

        # 2. Check session existence
        if not self.is_session_available():
            self._status = "OFFLINE"
            self._last_error = "Session file not found"
            return False

        # 3. Connect fresh client
        try:
            self.client = TelegramClient(
                self.session_path,
                API_ID,
                API_HASH,
                timeout=15,
                request_retries=3,
                connection_retries=None,
                retry_delay=1,
                auto_reconnect=True,
                flood_sleep_threshold=60
            )
            await self.client.connect()

            if not await self.client.is_user_authorized():
                logger.warning("Harvester userbot session is not authorized during reconnect.")
                await self.client.disconnect()
                self.client = None
                self._status = "ERROR"
                self._last_error = "Session not authorized"
                return False

            me = await self.client.get_me()
            self._user_info = {
                "id": me.id,
                "first_name": me.first_name,
                "last_name": me.last_name,
                "username": f"@{me.username}" if me.username else None,
                "phone": getattr(me, "phone", None)
            }

            # Foreground dialog warmup: loads entity cache and registers active MTProto viewport with DC
            with contextlib.suppress(Exception):
                await self.client.get_dialogs(limit=50)

            # 4. Re-attach and restart HarvesterListener
            self.listener = HarvesterListener(client=self.client)
            await self.listener.start()

            self._is_running = True
            self._status = "ONLINE"
            self._last_heartbeat = datetime.now(timezone.utc)
            self._consecutive_failures = 0
            self._last_error = None
            logger.info(f"✅ Harvester Userbot successfully reconnected and listening! ({me.first_name})")

            if self._alert_sent:
                await self._notify_admin_recovery()
                self._alert_sent = False

            return True
        except Exception as e:
            self._status = "ERROR"
            self._last_error = str(e)
            logger.error(f"Harvester reconnection attempt failed: {e}")
            return False

    async def _notify_admin_disconnect(self):
        """Sends an urgent notification to SuperAdmin on persistent disconnection."""
        if not self.bot or not ADMIN_ID:
            return
        try:
            err_msg = self._last_error or "Telegram bilan aloqa uzildi"
            text = (
                "⚠️ <b>DIQQAT: Harvester Userbot uzilib qoldi!</b>\n\n"
                f"📡 Holat: <code>{self._status}</code>\n"
                f"❌ Muvaffaqiyatsiz urinishlar: <b>{self._consecutive_failures}</b> marta\n"
                f"📝 Sabab: <i>{err_msg}</i>\n\n"
                "Tizim avtomatik qayta ulanishga harakat qilmoqda. "
                "Web panel yoki /admin orqali holatni tekshirishingiz mumkin."
            )
            await self.bot.send_message(chat_id=int(ADMIN_ID), text=text, parse_mode="HTML")
            logger.info("Sent harvester disconnect alert to SuperAdmin.")
        except Exception as e:
            logger.warning(f"Failed to send harvester disconnect alert to admin: {e}")

    async def _notify_admin_recovery(self):
        """Sends a notification to SuperAdmin when harvester recovers connection."""
        if not self.bot or not ADMIN_ID:
            return
        try:
            u_title = (self._user_info.get('first_name') or 'Userbot') if self._user_info else 'Userbot'
            u_contact = (self._user_info.get('username') or self._user_info.get('phone') or 'Ulangan') if self._user_info else ''
            text = (
                "✅ <b>Harvester Userbot aloqasi tiklandi!</b>\n\n"
                f"👤 Akkaunt: <b>{u_title}</b> ({u_contact})\n"
                "📡 Holat: <code>🟢 ONLINE</code>\n"
                "Buyurtmalarni monitoring qilish davom etmoqda."
            )
            await self.bot.send_message(chat_id=int(ADMIN_ID), text=text, parse_mode="HTML")
            logger.info("Sent harvester recovery alert to SuperAdmin.")
        except Exception as e:
            logger.warning(f"Failed to send harvester recovery alert to admin: {e}")

    async def broadcast_to_groups(self, text: str) -> Dict[str, Any]:
        """Broadcasts a text message to all active monitored harvester groups."""
        if not self.is_connected() or not self.client:
            return {"success": False, "error": "Userbot ulanmagan"}
        groups = await db.get_harvester_groups(active_only=True)
        if not groups:
            return {"success": False, "error": "Faol guruhlar mavjud emas"}
        sent = 0
        failed = 0
        for g in groups:
            try:
                await self.client.send_message(g["group_id"], text)
                sent += 1
                await asyncio.sleep(1.0)
            except Exception as e:
                logger.warning(f"Failed to broadcast to group {g.get('group_id')}: {e}")
                failed += 1
        return {"success": True, "sent": sent, "failed": failed}

    async def reload_groups(self):
        """Refreshes monitored groups in the active listener."""
        if not self.is_connected() and self.is_session_available():
            await self.start()
        if self.listener:
            await self.listener.reload_monitored_groups()

    async def resolve_and_join_group(self, target: str, region_tag: Optional[str] = "auto", fallback_title: Optional[str] = None) -> Dict[str, Any]:
        """
        Resolves a group username, invite link, or ID using Telethon.
        If public or invite link, attempts to join the channel/group.
        Automatically detects geographic context tag from title/username if not specified.
        Saves group to database and triggers in-memory listener reload.
        """
        if not self.is_connected() and self.is_session_available():
            await self.start()

        clean_target = target.strip()
        
        # Remove common URL prefixes
        for prefix in ["https://t.me/", "http://t.me/", "t.me/", "https://telegram.me/", "http://telegram.me/", "telegram.me/"]:
            if prefix in clean_target:
                clean_target = clean_target.split(prefix)[-1]
                break
        clean_target = clean_target.strip().lstrip("/")

        # Handle internal message links like c/1234567890/123 -> -1001234567890
        if clean_target.startswith("c/"):
            parts = clean_target.split("/")
            if len(parts) >= 2 and parts[1].isdigit():
                clean_target = f"-100{parts[1]}"

        def _compute_tag(title_str: str, user_str: Optional[str]) -> str:
            if not region_tag or region_tag.lower() in ("auto", "all"):
                reg, dist = detect_group_region(title_str, user_str or clean_target)
                return f"{reg}:{dist}" if dist else reg
            return region_tag

        if not self.is_connected() or not self.client:
            # Userbot not online, check if numeric ID
            try:
                numeric_id = int(clean_target)
                group_id = numeric_id
                title = fallback_title or f"Guruh {numeric_id}"
                final_tag = _compute_tag(title, None)
                await db.add_harvester_group(group_id, title, None, final_tag)
                await self.reload_groups()
                return {"success": True, "group_id": group_id, "title": title, "username": None, "region_tag": final_tag}
            except ValueError:
                return {
                    "success": False,
                    "error": "Userbot ulanmagan. Iltimos, oldin Userbot akkauntini ulang."
                }

        try:
            entity = None

            # Case 1: Invite hash (+hash or joinchat/hash)
            if clean_target.startswith("+") or clean_target.startswith("joinchat/"):
                invite_hash = clean_target.replace("joinchat/", "").lstrip("+").strip()
                try:
                    res = await self.client(ImportChatInviteRequest(invite_hash))
                    chats = getattr(res, "chats", [])
                    if chats:
                        entity = chats[0]
                except UserAlreadyParticipantError:
                    check_res = await self.client(CheckChatInviteRequest(invite_hash))
                    entity = getattr(check_res, "chat", None)
                except Exception:
                    check_res = await self.client(CheckChatInviteRequest(invite_hash))
                    entity = getattr(check_res, "chat", None)

            # Case 2: Numeric group ID (-100... or numeric)
            elif clean_target.lstrip("-").isdigit():
                numeric_id = int(clean_target)
                try:
                    entity = await self.client.get_entity(numeric_id)
                except Exception:
                    dialogs = await self.client.get_dialogs()
                    for d in dialogs:
                        if get_peer_id(d.entity) == numeric_id or getattr(d.entity, "id", 0) == abs(numeric_id):
                            entity = d.entity
                            break
                if not entity:
                    # If still not found by entity resolution, save directly by numeric ID
                    group_id = numeric_id
                    title = fallback_title or f"Guruh {numeric_id}"
                    final_tag = _compute_tag(title, None)
                    await db.add_harvester_group(group_id, title, None, final_tag)
                    await self.reload_groups()
                    return {"success": True, "group_id": group_id, "title": title, "username": None, "region_tag": final_tag}

            # Case 3: Public username or channel name
            else:
                username_clean = clean_target.lstrip("@").split("/")[0]
                entity = await self.client.get_entity(username_clean)
                with contextlib.suppress(Exception):
                    await self.client(JoinChannelRequest(entity))

            if not entity:
                return {"success": False, "error": f"Guruh ma'lumotlarini olib bo'lmadi: '{target}'"}

            peer_id = get_peer_id(entity)
            title = getattr(entity, "title", None) or fallback_title or str(peer_id)
            username = getattr(entity, "username", None)
            if username:
                username = f"@{username}"

            final_tag = _compute_tag(title, username)

            await db.add_harvester_group(
                group_id=peer_id,
                title=title,
                username=username,
                region_tag=final_tag
            )
            await self.reload_groups()
            logger.info(f"Resolved and added harvester group: '{title}' (ID: {peer_id}, Tag: {final_tag})")
            return {
                "success": True,
                "group_id": peer_id,
                "title": title,
                "username": username,
                "region_tag": final_tag
            }
        except Exception as e:
            logger.warning(f"Failed to resolve entity for '{target}': {e}")
            return {"success": False, "error": f"Guruhni topib bo'lmadi: {str(e)}"}

    def get_status(self) -> Dict[str, Any]:
        """Returns the current connection, watchdog and user status."""
        return {
            "status": self._status,
            "is_available": self.is_session_available(),
            "is_connected": self.is_connected(),
            "consecutive_failures": self._consecutive_failures,
            "last_heartbeat": self._last_heartbeat.strftime('%Y-%m-%d %H:%M:%S') if self._last_heartbeat else None,
            "last_error": self._last_error,
            "user_info": self._user_info or {},
            "session_name": self.session_name
        }

# Global singleton instance
default_harvester_service = HarvesterService()
