import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from aiogram.types import CallbackQuery, Message, User, Chat
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.base import StorageKey

from src import database as db
from src.bot.handlers import (
    AdminStates,
    BotStates,
    router,
    render_admin_harvester_hub,
    admin_groups_list_call,
    admin_reload_groups_call,
    admin_recent_orders_call,
    admin_group_target_received,
    noop_call,
    forward_group_inspector,
    link_group_inspector,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from src.harvester.service import HarvesterService
from src.config import ADMIN_ID

class TestHarvesterAdminDebug(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.storage = MemoryStorage()
        self.user = User(id=ADMIN_ID, is_bot=False, first_name="SuperAdmin")
        self.chat = Chat(id=ADMIN_ID, type="private")
        self.key = StorageKey(bot_id=12345, chat_id=ADMIN_ID, user_id=ADMIN_ID)
        self.state = FSMContext(storage=self.storage, key=self.key)
        await self.state.clear()

    async def test_types_and_imports(self):
        """Verify InlineKeyboardMarkup and InlineKeyboardButton are defined and usable."""
        self.assertIsNotNone(InlineKeyboardMarkup)
        self.assertIsNotNone(InlineKeyboardButton)
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Test", callback_data="test")]])
        self.assertEqual(len(kb.inline_keyboard), 1)

    async def test_noop_callback(self):
        """Verify noop callback answers safely without error."""
        call = MagicMock(spec=CallbackQuery)
        call.from_user = self.user
        call.answer = AsyncMock()
        await noop_call(call)
        call.answer.assert_called_once()

    async def test_groups_list_empty_view(self):
        """Verify admin_groups_list handles empty group list gracefully with HTML."""
        call = MagicMock(spec=CallbackQuery)
        call.from_user = self.user
        call.message = MagicMock()
        call.message.edit_text = AsyncMock()
        call.answer = AsyncMock()

        with patch("src.database.get_harvester_groups", new=AsyncMock(return_value=[])):
            await admin_groups_list_call(call)

        call.message.edit_text.assert_called_once()
        args, kwargs = call.message.edit_text.call_args
        self.assertIn("Monitoring Guruhlari Ro'yxati", args[0])
        self.assertEqual(kwargs.get("parse_mode"), "HTML")
        self.assertIsInstance(kwargs.get("reply_markup"), InlineKeyboardMarkup)

    async def test_recent_orders_empty_view(self):
        """Verify admin_recent_orders handles 0 captured orders gracefully with HTML."""
        call = MagicMock(spec=CallbackQuery)
        call.from_user = self.user
        call.message = MagicMock()
        call.message.edit_text = AsyncMock()
        call.answer = AsyncMock()

        with patch("src.database.get_recent_harvested_orders", new=AsyncMock(return_value=[])):
            await admin_recent_orders_call(call)

        call.message.edit_text.assert_called_once()
        args, kwargs = call.message.edit_text.call_args
        self.assertIn("Oxirgi Buyurtmalar Ro'yxati", args[0])
        self.assertEqual(kwargs.get("parse_mode"), "HTML")

    async def test_admin_group_target_received_forwarded_and_text(self):
        """Verify admin_group_target_received parses target cleanly and resets state."""
        await self.state.set_state(AdminStates.waiting_for_group_target)

        msg = MagicMock(spec=Message)
        msg.from_user = self.user
        msg.text = "https://t.me/vodiy_pitak_group"
        msg.forward_from_chat = None
        msg.answer = AsyncMock(return_value=MagicMock(delete=AsyncMock()))

        with patch("src.harvester.service.default_harvester_service.resolve_and_join_group",
                   new=AsyncMock(return_value={"success": True, "title": "Vodiy Pitak", "group_id": -1001234567, "username": "@vodiy"})):
            await admin_group_target_received(msg, self.state)

        # State should be cleared
        current_state = await self.state.get_state()
        self.assertIsNone(current_state)
        self.assertTrue(msg.answer.called)

    async def test_harvester_service_link_normalization(self):
        """Verify HarvesterService normalizes c/ and invite links properly."""
        service = HarvesterService()
        with patch.object(service, "is_session_available", return_value=False):
            # Numeric ID with userbot offline should still save cleanly
            res = await service.resolve_and_join_group("https://t.me/c/1234567890/55", fallback_title="Test Chat")
            self.assertTrue(res["success"])
            self.assertEqual(res["group_id"], -1001234567890)
            self.assertEqual(res["title"], "Test Chat")

if __name__ == "__main__":
    unittest.main()
