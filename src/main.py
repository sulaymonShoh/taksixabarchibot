import asyncio
import signal
import uvicorn
from aiogram import Bot, Dispatcher
from src import database as db
from src.config import validate_config, BOT_TOKEN, WEB_HOST, WEB_PORT
from src.bot.middleware import UserRegistrationMiddleware
from src.bot.handlers import router
from src.worker.worker_manager import WorkerManager
from src.web.app import app as web_app
from src.logger import setup_logger

logger = setup_logger("main")

async def main():
    logger.info("Starting Taksi Xabarchi v2.0 Multi-User SaaS Platform...")
    validate_config()
    
    # 1. Initialize Multi-Tenant Database
    await db.init_db()

    # 2. Initialize Telegram Bot (aiogram)
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    
    # Wire Bot to Harvester Dispatcher Grid (Stage 4)
    from src.harvester.dispatcher import default_dispatcher
    default_dispatcher.bot = bot
    
    # Apply user auto-registration & access middleware
    dp.update.middleware(UserRegistrationMiddleware())
    dp.include_router(router)
    
    # 3. Initialize Multi-Worker Manager
    worker_manager = WorkerManager(bot)
    bot.worker_manager = worker_manager
    worker_manager.start_sync_loop()
    
    # 4. Attach dependencies to FastAPI web state
    web_app.state.bot = bot
    web_app.state.worker_manager = worker_manager
    
    # 5. Configure Uvicorn Web Server
    uvicorn_config = uvicorn.Config(
        app=web_app,
        host=WEB_HOST,
        port=WEB_PORT,
        log_level="warning",
        access_log=False
    )
    uvicorn_server = uvicorn.Server(uvicorn_config)
    
    logger.info(f"Web Admin & Mini App server configured on http://{WEB_HOST}:{WEB_PORT}")
    
    # 6. Run Bot Polling and Web Server Concurrently
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Bot polling and Web server starting...")
        
        await asyncio.gather(
            dp.start_polling(bot, drop_pending_updates=True),
            uvicorn_server.serve()
        )
    except asyncio.CancelledError:
        pass
    finally:
        logger.info("Gracefully shutting down Taksi Xabarchi services...")
        await worker_manager.stop_all()
        uvicorn_server.should_exit = True
        await bot.session.close()
        logger.info("Shutdown complete.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Process terminated by user. Exiting.")

