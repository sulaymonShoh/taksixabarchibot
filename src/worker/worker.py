import asyncio
import random
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
from src.config import ADMIN_ID
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

class BroadcastWorker:
    def __init__(self, client: TelegramClient, bot: Bot, test_event: asyncio.Event):
        self.client = client
        self.bot = bot
        self.test_event = test_event

    async def alert_admin(self, text: str):
        try:
            await self.bot.send_message(chat_id=ADMIN_ID, text=text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Failed to send alert to admin: {e}")

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
                
            await db.update_group_status(chat_id, "Healthy")
            logger.info(f"Successfully forwarded to {title} ({chat_id})")
            
        except FloodWaitError as e:
            wait_time = e.seconds + 3
            logger.error(f"FloodWaitError: Sleeping for {wait_time}s")
            await self.alert_admin(
                f"⚠️ **Telegram cheklovi (FloodWait)**\n\n"
                f"Worker {wait_time} soniyaga to'xtatildi.\n"
                f"Kutish tugagach avtomatik davom etadi."
            )
            await asyncio.sleep(wait_time)
            
        except SlowModeWaitError as e:
            logger.warning(f"SlowMode in {title}: must wait {e.seconds}s. Skipping.")
            await db.update_group_status(chat_id, "SlowMode")
            await self.alert_admin(
                f"⏳ **Guruhda SlowMode aniqlandi**\n\n"
                f"👥 **Guruh:** {group_display}\n"
                f"🆔 **ID:** `{chat_id}`\n"
                f"⚠️ **Kutish vaqti:** {e.seconds} soniya. Guruh bu doirada o'tkazib yuborildi."
            )
            
        except (ChatWriteForbiddenError, UserBannedInChannelError):
            logger.error(f"Write forbidden/banned in {title}. Deactivating.")
            await db.update_group_status(chat_id, "Banned/Muted", is_active=False)
            await self.alert_admin(
                f"🚫 **Guruhda cheklov (Muted/Banned)**\n\n"
                f"👥 **Guruh:** {group_display}\n"
                f"🆔 **ID:** `{chat_id}`\n"
                f"⚠️ **Holat:** Yozish taqiqlangan yoki hisob cheklangan. Guruh ro'yxatda faolsizlantirildi."
            )
            
        except ChannelPrivateError:
            logger.error(f"Channel {title} is private/kicked. Deactivating.")
            await db.update_group_status(chat_id, "Private/Kicked", is_active=False)
            await self.alert_admin(
                f"🚫 **Guruhga kirish yo'qolgan (Kicked/Private)**\n\n"
                f"👥 **Guruh:** {group_display}\n"
                f"🆔 **ID:** `{chat_id}`\n"
                f"⚠️ **Holat:** Guruhdan chiqarilgan yoki guruh yopiq. Ro'yxatdan o'chirildi."
            )
            
        except Exception as e:
            logger.error(f"Failed to forward to {title}: {e}")
            await db.update_group_status(chat_id, f"Error: {str(e)[:50]}")

    async def run_loop(self):
        logger.info("Worker loop started.")
        while True:
            try:
                # Check state
                is_running = await db.get_setting("is_running", False)
                
                # Check for test trigger
                is_test = False
                if self.test_event.is_set():
                    is_test = True
                    is_running = True
                    self.test_event.clear()
                    await self.alert_admin("🧪 **Sinov yuborish (Test round) boshlandi**")

                if not is_running:
                    await asyncio.sleep(5)
                    continue
                    
                source_chat_id = await db.get_setting("source_chat_id", None)
                if not source_chat_id:
                    logger.warning("No source chat configured. Sleeping.")
                    await asyncio.sleep(15)
                    continue
                    
                # Fetch latest message from source chat
                try:
                    messages = await self.client.get_messages(source_chat_id, limit=1)
                    if not messages or not messages[0]:
                        logger.warning("Source chat is empty. Sleeping.")
                        await asyncio.sleep(15)
                        continue
                    latest_message = messages[0]
                except Exception as e:
                    logger.error(f"Error fetching latest message from source chat {source_chat_id}: {e}")
                    await asyncio.sleep(15)
                    continue

                active_groups = await db.get_active_groups()
                if not active_groups:
                    logger.info("No active target groups. Sleeping.")
                    await asyncio.sleep(20)
                    continue
                    
                drop_author = await db.get_setting("drop_author", False)
                jitter_min = float(await db.get_setting("jitter_min", 1.5))
                jitter_max = float(await db.get_setting("jitter_max", 2.0))
                cycle_min = int(await db.get_setting("cycle_min", 60))
                cycle_max = int(await db.get_setting("cycle_max", 90))

                logger.info(f"Starting forward round to {len(active_groups)} groups from source chat {source_chat_id}.")
                
                for group in active_groups:
                    await self.process_group(group, source_chat_id, latest_message, drop_author)
                    
                    # Randomized Jitter Delay (Supports float seconds like 1.5s - 2.0s)
                    delay = random.uniform(jitter_min, jitter_max)
                    logger.debug(f"Jitter delay: {delay:.2f}s")
                    await asyncio.sleep(delay)
                
                if is_test:
                    await self.alert_admin("✅ **Sinov yuborish yakunlandi!**")
                    continue
                
                # Inter-round cooldown
                cooldown = random.randint(cycle_min, cycle_max)
                logger.info(f"Round finished. Cooling down for {cooldown}s.")
                await asyncio.sleep(cooldown)

            except asyncio.CancelledError:
                logger.info("Worker loop cancelled.")
                break
            except Exception as e:
                logger.error(f"Critical error in worker loop: {e}", exc_info=True)
                await asyncio.sleep(20)
