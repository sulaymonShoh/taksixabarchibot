import asyncio
import signal
from aiogram import Bot, Dispatcher
from telethon import TelegramClient
from src import database as db
from src.config import validate_config, BOT_TOKEN, API_ID, API_HASH, SESSION_NAME
from src.bot.middleware import AdminWhitelistMiddleware
from src.bot.handlers import router
from src.worker.worker import BroadcastWorker
from src.logger import setup_logger

logger = setup_logger("main")

async def main():
    logger.info("Starting Dual-Engine Telegram Broadcast System...")
    validate_config()
    
    # Init DB
    await db.init_db()

    # Initialize Bot (aiogram)
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    
    # Apply security middleware
    dp.update.middleware(AdminWhitelistMiddleware())
    dp.include_router(router)
    
    # Initialize MTProto Client (Telethon)
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    
    # Event for manual tests
    worker_test_event = asyncio.Event()
    
    # Share objects via bot instance for handlers
    bot.worker_client = client
    bot.worker_test_event = worker_test_event

    # Worker instance
    worker = BroadcastWorker(client, bot, worker_test_event)
    
    # Start MTProto client
    # Note: Requires auth.py to have been run to generate .session
    await client.start()
    logger.info("MTProto Worker Client started successfully.")
    
    # Start tasks
    loop = asyncio.get_running_loop()
    worker_task = loop.create_task(worker.run_loop())
    
    try:
        logger.info("Starting Bot Polling...")
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, drop_pending_updates=True)
    except asyncio.CancelledError:
        pass
    finally:
        logger.info("Shutting down...")
        worker_task.cancel()
        await client.disconnect()
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Process interrupted by user. Exiting cleanly.")
