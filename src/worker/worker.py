import asyncio
import random
from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    SlowModeWaitError,
    UserBannedInChannelError,
    ChatWriteForbiddenError,
    ChannelPrivateError,
    MessageDeleteForbiddenError,
    MessageIdInvalidError
)
from aiogram import Bot
from src import database as db
from src.worker.spintax import parse_spintax
from src.config import ADMIN_ID
from src.logger import setup_logger

logger = setup_logger("worker")

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

    async def safe_delete_message(self, chat_id: int, message_id: int):
        try:
            await self.client.delete_messages(chat_id, [message_id])
            logger.info(f"Deleted old message {message_id} in {chat_id}")
        except (MessageDeleteForbiddenError, MessageIdInvalidError) as e:
            logger.warning(f"Could not delete message in {chat_id}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error deleting message in {chat_id}: {e}")

    async def process_group(self, group: dict, content: str, media_path: str, auto_cleanup: bool):
        chat_id = group['chat_id']
        title = group['title']
        
        try:
            # 1. Cleanup old message
            if auto_cleanup:
                old_msg_id = await db.get_message_history(chat_id)
                if old_msg_id:
                    await self.safe_delete_message(chat_id, old_msg_id)
            
            # 2. Spintax Generation
            final_text = parse_spintax(content)
            
            # 3. Transmission
            if media_path:
                msg = await self.client.send_file(chat_id, media_path, caption=final_text, parse_mode="html")
            else:
                msg = await self.client.send_message(chat_id, final_text, parse_mode="html")
                
            # 4. Record Update
            await db.set_message_history(chat_id, msg.id)
            await db.update_group_status(chat_id, "Healthy")
            logger.info(f"Successfully posted to {title} ({chat_id})")
            
        except FloodWaitError as e:
            wait_time = e.seconds + 3
            logger.error(f"FloodWaitError: Sleeping for {wait_time}s")
            await self.alert_admin(f"⚠️ **Telegram cheklovi (FloodWait)**\nWorker {wait_time} soniyaga to'xtatildi. Shundan so'ng avtomatik davom etadi.")
            await asyncio.sleep(wait_time)
            
        except SlowModeWaitError as e:
            logger.warning(f"SlowMode in {title}: must wait {e.seconds}s. Skipping.")
            await db.update_group_status(chat_id, "SlowMode")
            
        except (ChatWriteForbiddenError, UserBannedInChannelError):
            logger.error(f"Write forbidden/banned in {title}. Deactivating.")
            await db.update_group_status(chat_id, "Banned/Muted", is_active=False)
            await self.alert_admin(f"🚫 **Guruhda cheklov**\n`{title}` guruhida yozish taqiqlangan yoki hisob cheklangan. Guruh faolsizlantirildi.")
            
        except ChannelPrivateError:
            logger.error(f"Channel {title} is private/kicked. Deactivating.")
            await db.update_group_status(chat_id, "Private/Kicked", is_active=False)
            await db.clear_message_history(chat_id)
            await self.alert_admin(f"🚫 **Guruhga kirish yo'qolgan**\n`{title}` guruhidan chiqarilgan yoki guruh yopiq. Ro'yxatdan o'chirildi.")
            
        except Exception as e:
            logger.error(f"Failed to post to {title}: {e}")
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
                    await asyncio.sleep(10)
                    continue
                    
                active_groups = await db.get_active_groups()
                if not active_groups:
                    logger.info("No active groups. Sleeping.")
                    await asyncio.sleep(30)
                    continue
                    
                content = await db.get_setting("content_text", "")
                if not content:
                    logger.info("No content set. Sleeping.")
                    await asyncio.sleep(30)
                    continue
                    
                media_path = await db.get_setting("media_path", None)
                auto_cleanup = await db.get_setting("auto_cleanup", False)
                jitter_min = await db.get_setting("jitter_min", 6)
                jitter_max = await db.get_setting("jitter_max", 12)
                cycle_min = await db.get_setting("cycle_min", 180)
                cycle_max = await db.get_setting("cycle_max", 300)

                logger.info(f"Starting broadcast round to {len(active_groups)} groups.")
                
                for group in active_groups:
                    await self.process_group(group, content, media_path, auto_cleanup)
                    
                    # Human Simulation Delay (Jitter)
                    delay = random.randint(jitter_min, jitter_max)
                    logger.debug(f"Jitter delay: {delay}s")
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
                await asyncio.sleep(30)
