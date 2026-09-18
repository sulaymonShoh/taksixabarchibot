import os
import sys
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from telethon.errors import (
    FloodWaitError,
    SlowModeWaitError,
    UserBannedInChannelError,
    ChatWriteForbiddenError,
    ChannelPrivateError
)

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath("."))

os.environ["BOT_TOKEN"] = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
os.environ["ADMIN_ID"] = "123456789"
os.environ["API_ID"] = "12345"
os.environ["API_HASH"] = "0123456789abcdef0123456789abcdef"
os.environ["DB_PATH"] = "data/test_worker_suite.db"

from src import database as db
from src.worker.worker import UserBroadcastWorker, format_group_display
from src.worker.worker_manager import WorkerManager

async def test_worker_formatting_and_errors():
    print(">>> 1. Testing Worker Error Interceptors & Formatting")
    if os.path.exists("data/test_worker_suite.db"):
        os.remove("data/test_worker_suite.db")
    await db.init_db()

    user_id = 7001
    await db.get_or_create_user(user_id, "Worker Test User", "worker_tester")
    await db.add_or_update_user_group(user_id, -100123, "Test Group 1", "test_group_1", True)

    # Mock client and bot
    mock_client = MagicMock()
    mock_client.send_message = AsyncMock()
    mock_client.forward_messages = AsyncMock()
    
    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()

    test_event = asyncio.Event()
    worker = UserBroadcastWorker(user_id, mock_client, mock_bot, test_event)

    # 1.1 Test format_group_display
    g_with_user = {"chat_id": -100123, "title": "Taxi Group", "username": "taxigroup"}
    assert format_group_display(g_with_user) == "[Taxi Group](https://t.me/taxigroup)"

    g_supergroup = {"chat_id": -100987654321, "title": "Supergroup", "username": None}
    assert format_group_display(g_supergroup) == "[Supergroup](https://t.me/c/987654321/1)"

    g_plain = {"chat_id": 0, "title": "Plain Group", "username": None}
    assert format_group_display(g_plain) == "**Plain Group**"
    print("   [PASS] Group formatting helper verified.")

    # 1.2 Test normal forward (drop_author=False)
    mock_msg = MagicMock()
    mock_msg.id = 55
    group = {"chat_id": -100123, "title": "Test Group 1", "username": "test_group_1"}
    await worker.process_group(group, -100999, mock_msg, drop_author=False)
    mock_client.forward_messages.assert_called_with(-100123, 55, -100999)
    g_status = (await db.get_user_groups(user_id))[0]
    assert g_status["status"] == "Healthy"
    print("   [PASS] Native forward verified.")

    # 1.3 Test clean copy forward (drop_author=True)
    await worker.process_group(group, -100999, mock_msg, drop_author=True)
    mock_client.send_message.assert_called_with(-100123, mock_msg)
    print("   [PASS] Clean copy forward verified.")

    # 1.4 Test SlowModeWaitError handling
    mock_client.forward_messages.side_effect = SlowModeWaitError(request=None)
    mock_client.forward_messages.side_effect.seconds = 30
    await worker.process_group(group, -100999, mock_msg, drop_author=False)
    g_status = (await db.get_user_groups(user_id))[0]
    assert g_status["status"] == "SlowMode"
    assert mock_bot.send_message.called
    print("   [PASS] SlowMode interception verified.")

    # 1.5 Test ChatWriteForbiddenError -> deactivates group
    mock_client.forward_messages.side_effect = ChatWriteForbiddenError(request=None)
    await worker.process_group(group, -100999, mock_msg, drop_author=False)
    g_status = (await db.get_user_groups(user_id))[0]
    assert g_status["status"] == "Banned/Muted"
    assert g_status["is_active"] == 0
    print("   [PASS] Permission ban / group deactivation verified.")

    # 1.6 Test ChannelPrivateError -> deactivates group
    mock_client.forward_messages.side_effect = ChannelPrivateError(request=None)
    await worker.process_group(group, -100999, mock_msg, drop_author=False)
    g_status = (await db.get_user_groups(user_id))[0]
    assert g_status["status"] == "Private/Kicked"
    assert g_status["is_active"] == 0
    print("   [PASS] Private/kicked group deactivation verified.")

async def test_worker_manager_lifecycle():
    print(">>> 2. Testing WorkerManager Lifecycle")
    mock_bot = MagicMock()
    manager = WorkerManager(mock_bot)

    # 2.1 Unauthenticated user cannot start worker
    can_start = await manager.start_user_worker(888888)
    assert can_start is False
    print("   [PASS] Unauthenticated worker rejection verified.")

    # 2.2 Test stopping non-existent worker (safe no-op)
    await manager.stop_user_worker(888888)
    assert len(manager.active_workers) == 0

    # 2.3 Test trigger_test_round on unauthenticated returns False
    res = await manager.trigger_test_round(888888)
    assert res is False
    print("   [PASS] Safe test trigger on inactive session verified.")

    # 2.4 Stop all
    await manager.stop_all()
    assert manager._is_running is False
    print("   [PASS] Clean manager shutdown verified.")

async def main():
    print("=" * 60)
    print("TEST SUITE: PHASE 3 (UserBroadcastWorker & WorkerManager)")
    print("=" * 60)
    await test_worker_formatting_and_errors()
    await test_worker_manager_lifecycle()
    
    if os.path.exists("data/test_worker_suite.db"):
        os.remove("data/test_worker_suite.db")

    print("=" * 60)
    print("ALL PHASE 3 WORKER TESTS PASSED CLEANLY (100% SUCCESS)")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
