import asyncio
import random
from datetime import datetime
from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    SlowModeWaitError,
    UserBannedInChannelError,
    ChatWriteForbiddenError,
    ChannelPrivateError
)
from aiogram import Bot
from src import database as db
from src.bot import keyboards as kb
from src.logger import setup_logger

logger = setup_logger("worker")

def format_group_display(group: dict) -> str:
    """Returns a formatted Markdown link for the group if username or supergroup ID is available."""
    title = group.get('title', 'Noma\'lum guruh')
    username = group.get('username')
    chat_id = group.get('chat_id')
    
    if username:
        return f"[{title}](https://t.me/{username})"
    elif chat_id:
        str_id = str(chat_id)
        if str_id.startswith("-100"):
            clean_id = str_id[4:]
            return f"[{title}](https://t.me/c/{clean_id}/1)"
        elif str_id.startswith("-"):
            clean_id = str_id[1:]
            return f"[{title}](https://t.me/c/{clean_id}/1)"
    return f"**{title}**"

class UserBroadcastWorker:
    def __init__(self, user_id: int, client: TelegramClient, bot: Bot, test_event: asyncio.Event):
        self.user_id = user_id
        self.client = client
        self.bot = bot
        self.test_event = test_event
        self._is_running = True

    async def alert_user(self, text: str):
        try:
            await self.bot.send_message(chat_id=self.user_id, text=text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Failed to send alert to user {self.user_id}: {e}")

    async def process_group(self, group: dict, source_chat_id: int, message_to_forward, drop_author: bool):
        chat_id = group['chat_id']
        title = group['title']
        group_display = format_group_display(group)
        
        try:
            # Forward message from source chat
            if drop_author:
                # Copy / Send exact message without 'Forwarded from' header
                await self.client.send_message(chat_id, message_to_forward)
            else:
                # Standard native forward
                await self.client.forward_messages(chat_id, message_to_forward.id, source_chat_id)
                
            await db.update_user_group_status(self.user_id, chat_id, "Healthy")
            logger.debug(f"[User {self.user_id}] Forwarded to {title} ({chat_id})")
            
        except FloodWaitError as e:
            wait_time = e.seconds + 3
            logger.warning(f"[User {self.user_id}] FloodWait: Sleeping for {wait_time}s")
            await self.alert_user(
                f"⚠️ **Telegram cheklovi (FloodWait)**\n\n"
                f"Akkauntingiz {wait_time} soniyaga to'xtatildi.\n"
                f"Kutish tugagach avtomatik davom etadi."
            )
            await asyncio.sleep(wait_time)
            
        except SlowModeWaitError as e:
            logger.warning(f"[User {self.user_id}] SlowMode in {title}: must wait {e.seconds}s. Skipping.")
            await db.update_user_group_status(self.user_id, chat_id, "SlowMode")
            await self.alert_user(
                f"⏳ **Guruhda SlowMode aniqlandi**\n\n"
                f"👥 **Guruh:** {group_display}\n"
                f"🆔 **ID:** `{chat_id}`\n"
                f"⚠️ Guruh bu doirada o'tkazib yuborildi."
            )
            
        except (ChatWriteForbiddenError, UserBannedInChannelError):
            logger.warning(f"[User {self.user_id}] Write forbidden in {title}. Deactivating.")
            await db.update_user_group_status(self.user_id, chat_id, "Banned/Muted", is_active=False)
            await self.alert_user(
                f"🚫 **Guruhda cheklov (Muted/Banned)**\n\n"
                f"👥 **Guruh:** {group_display}\n"
                f"🆔 **ID:** `{chat_id}`\n"
                f"⚠️ Yozish taqiqlangan yoki hisob cheklangan. Guruh ro'yxatda faolsizlantirildi."
            )
            
        except ChannelPrivateError:
            logger.warning(f"[User {self.user_id}] Channel {title} is private/kicked. Deactivating.")
            await db.update_user_group_status(self.user_id, chat_id, "Private/Kicked", is_active=False)
            await self.alert_user(
                f"🚫 **Guruhga kirish yo'qolgan**\n\n"
                f"👥 **Guruh:** {group_display}\n"
                f"🆔 **ID:** `{chat_id}`\n"
                f"⚠️ Guruhdan chiqarilgan yoki guruh yopiq. Guruh faolsizlantirildi."
            )
            
        except Exception as e:
            logger.error(f"[User {self.user_id}] Failed to forward to {title}: {e}")
            await db.update_user_group_status(self.user_id, chat_id, f"Error: {str(e)[:50]}")

    async def run_loop(self):
        logger.info(f"Broadcast worker loop started for User {self.user_id}.")
        while self._is_running:
            try:
                # 1. Verify subscription
                user = await db.get_user(self.user_id)
                if not user or user.get('is_banned'):
                    logger.info(f"User {self.user_id} is banned or not found. Stopping worker.")
                    break
                    
                expiry_str = user.get('subscription_expiry')
                if expiry_str:
                    try:
                        expiry = datetime.strptime(expiry_str, '%Y-%m-%d %H:%M:%S')
                        if datetime.utcnow() > expiry:
                            logger.info(f"Subscription expired for User {self.user_id}. Stopping.")
                            await db.set_user_setting(self.user_id, "is_running", 0)
                            await self.alert_user(
                                "⚠️ **Obuna muddatingiz tugadi!**\n\n"
                                "Avtomatik e'lon tarqatish to'xtatildi.\n"
                                "Xizmatdan foydalanishni davom ettirish uchun obunangizni uzaytiring."
                            )
                            break
                    except Exception:
                        pass

                # 2. Check settings & running state
                settings = await db.get_user_settings(self.user_id)
                is_running = settings.get('is_running', False)
                
                is_test = False
                if self.test_event.is_set():
                    is_test = True
                    is_running = True
                    self.test_event.clear()
                    await self.alert_user("🧪 **Sinov yuborish (Test round) boshlandi...**")

                if not is_running:
                    await asyncio.sleep(5)
                    continue
                    
                source_chat_id = settings.get('source_chat_id')
                if not source_chat_id:
                    logger.debug(f"[User {self.user_id}] No source chat configured. Sleeping.")
                    await asyncio.sleep(15)
                    continue
                    
                # 3. Fetch latest message from source chat
                try:
                    messages = await self.client.get_messages(source_chat_id, limit=1)
                    if not messages or not messages[0]:
                        logger.debug(f"[User {self.user_id}] Source chat {source_chat_id} is empty.")
                        await asyncio.sleep(15)
                        continue
                    latest_message = messages[0]
                except Exception as e:
                    logger.error(f"[User {self.user_id}] Error fetching from source chat {source_chat_id}: {e}")
                    await asyncio.sleep(20)
                    continue

                # 4. Get active destination groups
                active_groups = await db.get_user_active_groups(self.user_id)
                if not active_groups:
                    logger.debug(f"[User {self.user_id}] No active target groups. Sleeping.")
                    await asyncio.sleep(20)
                    continue
                    
                drop_author = bool(settings.get('drop_author', False))
                jitter_min = float(settings.get('jitter_min', 1.5))
                jitter_max = float(settings.get('jitter_max', 2.0))
                cycle_min = int(settings.get('cycle_min', 60))
                cycle_max = int(settings.get('cycle_max', 90))

                logger.info(f"[User {self.user_id}] Starting round to {len(active_groups)} groups from source {source_chat_id}.")
                
                for group in active_groups:
                    if not self._is_running:
                        break
                    await self.process_group(group, source_chat_id, latest_message, drop_author)
                    
                    # Speed jitter between groups
                    delay = random.uniform(jitter_min, jitter_max)
                    await asyncio.sleep(delay)
                
                if is_test:
                    await self.alert_user("✅ **Sinov yuborish muvaffaqiyatli yakunlandi!**")
                    continue
                
                # Inter-round cooldown
                cooldown = random.randint(cycle_min, cycle_max)
                logger.info(f"[User {self.user_id}] Round complete. Sleeping for {cooldown}s.")
                await asyncio.sleep(cooldown)

            except asyncio.CancelledError:
                logger.info(f"Worker loop cancelled for User {self.user_id}.")
                break
            except Exception as e:
                logger.error(f"Error in User {self.user_id} worker loop: {e}", exc_info=True)
                await asyncio.sleep(20)
                
    def stop(self):
        self._is_running = False

