from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, Update
from src import database as db
from src.logger import setup_logger

logger = setup_logger("middleware")

class UserRegistrationMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any]
    ) -> Any:
        
        user = None
        if isinstance(event, Message) and event.from_user:
            user = event.from_user
        elif isinstance(event, CallbackQuery) and event.from_user:
            user = event.from_user
            
        if user:
            user_id = user.id
            full_name = user.full_name or "Foydalanuvchi"
            username = user.username
            
            # Auto-register new users & grant 3-day trial
            user_record, is_new = await db.get_or_create_user(user_id, full_name, username)
            
            if user_record.get('is_banned'):
                logger.warning(f"Banned user {user_id} attempted access.")
                if isinstance(event, Message):
                    await event.answer("🚫 **Hisobingiz ma'muriyat tomonidan bloklangan.**", parse_mode="Markdown")
                elif isinstance(event, CallbackQuery):
                    await event.answer("🚫 Hisobingiz bloklangan.", show_alert=True)
                return None
                
            data['db_user'] = user_record
            
        return await handler(event, data)

