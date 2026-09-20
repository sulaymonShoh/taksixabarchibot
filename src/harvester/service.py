"""
HarvesterService: Manages the lifecycle of the dedicated Telethon userbot client,
group entity resolution, auto-joining, and connects real-time MTProto streams
to HarvesterListener.
"""
import os
import contextlib
from typing import Optional, Dict, Any
from telethon import TelegramClient
from telethon.utils import get_peer_id
from telethon.tl.functions.channels import JoinChannelRequest

from src.config import API_ID, API_HASH, SESSIONS_DIR, HARVESTER_SESSION_NAME
from src.harvester.listener import HarvesterListener
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

    def is_session_available(self) -> bool:
        """Returns True if the .session file exists on disk."""
        return os.path.exists(f"{self.session_path}.session") or os.path.exists(self.session_path)

    def is_connected(self) -> bool:
        """Returns True if userbot client is connected and authorized."""
        return bool(self.client and self.client.is_connected() and self._is_running)

    async def start(self) -> bool:
        """Connects the userbot client and starts the real-time HarvesterListener."""
        if not self.is_session_available():
            logger.warning(
                f"Harvester session file '{self.session_path}.session' not found. "
                "Harvester userbot is idle. Run 'python scripts/login_harvester.py' to activate."
            )
            return False

        try:
            self.client = TelegramClient(self.session_path, API_ID, API_HASH)
            await self.client.connect()

            if not await self.client.is_user_authorized():
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

            # Initialize and start the HarvesterListener
            self.listener = HarvesterListener(client=self.client)
            await self.listener.start()
            self._is_running = True
            return True
        except Exception as e:
            logger.error(f"Failed to start HarvesterService: {e}", exc_info=True)
            self._is_running = False
            return False

    async def stop(self):
        """Stops the harvester listener and disconnects client."""
        self._is_running = False
        if self.listener:
            await self.listener.stop()
        if self.client and self.client.is_connected():
            await self.client.disconnect()
        logger.info("HarvesterService stopped.")

    async def reload_groups(self):
        """Refreshes monitored groups in the active listener."""
        if self.listener:
            await self.listener.reload_monitored_groups()

    async def resolve_and_join_group(self, target: str, region_tag: str = "andijon") -> Dict[str, Any]:
        """
        Resolves a group username, invite link, or ID using Telethon.
        If public, attempts to join the channel.
        Saves group to database and triggers in-memory listener reload.
        """
        clean_target = target.strip()
        # Remove common URL prefix
        if "t.me/" in clean_target:
            clean_target = clean_target.split("t.me/")[-1].replace("+", "").strip("/")
            if not clean_target.startswith("@") and not clean_target.startswith("joinchat"):
                clean_target = f"@{clean_target}"

        if not self.is_connected() or not self.client:
            # Userbot not online, check if numeric ID
            try:
                numeric_id = int(clean_target)
                group_id = numeric_id
                title = f"Guruh {numeric_id}"
                await db.add_harvester_group(group_id, title, None, region_tag)
                await self.reload_groups()
                return {"success": True, "group_id": group_id, "title": title, "username": None}
            except ValueError:
                return {
                    "success": False,
                    "error": "Userbot ulanmagan. Iltimos, oldin 'python scripts/login_harvester.py' orqali akkauntni ulang."
                }

        try:
            entity = await self.client.get_entity(clean_target)
            peer_id = get_peer_id(entity)
            title = getattr(entity, "title", str(peer_id))
            username = getattr(entity, "username", None)
            if username:
                username = f"@{username}"

            # Try to join if channel/supergroup
            with contextlib.suppress(Exception):
                await self.client(JoinChannelRequest(entity))

            await db.add_harvester_group(
                group_id=peer_id,
                title=title,
                username=username,
                region_tag=region_tag
            )
            await self.reload_groups()
            logger.info(f"Resolved and added harvester group: '{title}' (ID: {peer_id})")
            return {
                "success": True,
                "group_id": peer_id,
                "title": title,
                "username": username
            }
        except Exception as e:
            logger.warning(f"Failed to resolve entity for '{target}': {e}")
            return {"success": False, "error": f"Guruhni topib bo'lmadi: {str(e)}"}

    def get_status(self) -> Dict[str, Any]:
        """Returns the current connection and user status."""
        return {
            "is_available": self.is_session_available(),
            "is_connected": self.is_connected(),
            "user_info": self._user_info or {},
            "session_name": self.session_name
        }

# Global singleton instance
default_harvester_service = HarvesterService()
