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
from telethon.tl.functions.messages import ImportChatInviteRequest, CheckChatInviteRequest
from telethon.errors import UserAlreadyParticipantError

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
        if self.is_connected():
            return True

        if not self.is_session_available():
            logger.warning(
                f"Harvester session file '{self.session_path}.session' not found. "
                "Harvester userbot is idle. Session not connected."
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
        if not self.is_connected() and self.is_session_available():
            await self.start()
        if self.listener:
            await self.listener.reload_monitored_groups()

    async def resolve_and_join_group(self, target: str, region_tag: str = "andijon", fallback_title: Optional[str] = None) -> Dict[str, Any]:
        """
        Resolves a group username, invite link, or ID using Telethon.
        If public or invite link, attempts to join the channel/group.
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

        if not self.is_connected() or not self.client:
            # Userbot not online, check if numeric ID
            try:
                numeric_id = int(clean_target)
                group_id = numeric_id
                title = fallback_title or f"Guruh {numeric_id}"
                await db.add_harvester_group(group_id, title, None, region_tag)
                await self.reload_groups()
                return {"success": True, "group_id": group_id, "title": title, "username": None}
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
                    await db.add_harvester_group(group_id, title, None, region_tag)
                    await self.reload_groups()
                    return {"success": True, "group_id": group_id, "title": title, "username": None}

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
