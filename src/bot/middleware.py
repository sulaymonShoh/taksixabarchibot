from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, Update
from src.config import ADMIN_ID
from src.logger import setup_logger

logger = setup_logger("middleware")

class AdminWhitelistMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any]
    ) -> Any:
        
        user_id = None
        if isinstance(event, Message):
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id
            
        if user_id and user_id != ADMIN_ID:
            logger.warning(f"Unauthorized access attempt from user_id: {user_id}")
            return None # Drop the update
            
        return await handler(event, data)
