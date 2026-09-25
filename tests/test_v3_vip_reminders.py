"""
Automated Test Suite for Taksi Xabarchi v3.0 - VIP Expiration Reminder & Retention System (Dunning Notifier)
Tests:
1. Sending window validation (strictly 08:00 - 20:00 Tashkent time, UTC+5).
2. Reminder classification logic (Track A: DAY_3, DAY_2, DAY_1; Track B: TRIAL_EXPIRING).
3. Typography & formatting validation (Strictly bold tags, zero italics/cursive).
4. Bilingual message content (Latin and Cyrillic).
5. Database operations and strict idempotency (anti-duplicate per subscription cycle).
6. Lifecycle management (scheduler start and stop).
7. End-to-end evaluation & dispatch pass with Mock Bot.
"""
import os
import sys
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath("."))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

TEST_DB_PATH = "data/test_v3_vip_reminders.db"
os.environ["DB_PATH"] = TEST_DB_PATH

import aiosqlite
from src import database as db
# Override DB_PATH on database module just in case it was imported before env var
db.DB_PATH = TEST_DB_PATH

from src.worker.reminder_scheduler import (
    is_within_sending_window,
    classify_reminder,
    format_reminder_message,
    SubscriptionReminderScheduler
)

async def init_test_db():
    if os.path.exists(TEST_DB_PATH):
        try:
            os.remove(TEST_DB_PATH)
        except Exception:
            pass
    await db.init_db()

async def run_reminder_tests():
    print("=" * 75)
    print("TEST SUITE: VIP EXPIRATION REMINDER & RETENTION SYSTEM")
    print("=" * 75)

    await init_test_db()

    # ==================== 1. SENDING WINDOW CHECKS ====================
    print("\n>>> 1. Testing Tashkent Time (UTC+5) 08:00 - 20:00 Sending Window...")
    # 02:59 UTC = 07:59 Tashkent -> Outside window (False)
    t_0759 = datetime(2026, 9, 25, 2, 59, 0)
    assert not is_within_sending_window(t_0759), "07:59 Tashkent should be outside window"

    # 03:00 UTC = 08:00 Tashkent -> Inside window (True)
    t_0800 = datetime(2026, 9, 25, 3, 0, 0)
    assert is_within_sending_window(t_0800), "08:00 Tashkent should be inside window"

    # 07:00 UTC = 12:00 Tashkent -> Inside window (True)
    t_1200 = datetime(2026, 9, 25, 7, 0, 0)
    assert is_within_sending_window(t_1200), "12:00 Tashkent should be inside window"

    # 14:59 UTC = 19:59 Tashkent -> Inside window (True)
    t_1959 = datetime(2026, 9, 25, 14, 59, 0)
    assert is_within_sending_window(t_1959), "19:59 Tashkent should be inside window"

    # 15:00 UTC = 20:00 Tashkent -> Outside window (False)
    t_2000 = datetime(2026, 9, 25, 15, 0, 0)
    assert not is_within_sending_window(t_2000), "20:00 Tashkent should be outside window"

    # 18:00 UTC = 23:00 Tashkent -> Outside window (False)
    t_2300 = datetime(2026, 9, 25, 18, 0, 0)
    assert not is_within_sending_window(t_2300), "23:00 Tashkent should be outside window"
    print("   [PASS] 08:00 - 20:00 Tashkent window boundary tests all passed.")

    # ==================== 2. REMINDER CLASSIFICATION ====================
    print("\n>>> 2. Testing Reminder Classification Logic...")
    simulated_now = datetime(2026, 9, 25, 6, 0, 0) # 11:00 Tashkent

    # Track A: Regular VIP Subscribers
    # Day 3: Expiry 2.5 days ahead
    u_day3 = {"subscription_expiry": (simulated_now + timedelta(days=2, hours=12)).strftime("%Y-%m-%d %H:%M:%S")}
    assert classify_reminder(u_day3, is_trial_user=False, now_utc=simulated_now) == "DAY_3"

    # Day 2: Expiry 1.5 days ahead
    u_day2 = {"subscription_expiry": (simulated_now + timedelta(days=1, hours=12)).strftime("%Y-%m-%d %H:%M:%S")}
    assert classify_reminder(u_day2, is_trial_user=False, now_utc=simulated_now) == "DAY_2"

    # Day 1: Expiry 12 hours ahead
    u_day1 = {"subscription_expiry": (simulated_now + timedelta(hours=12)).strftime("%Y-%m-%d %H:%M:%S")}
    assert classify_reminder(u_day1, is_trial_user=False, now_utc=simulated_now) == "DAY_1"

    # Non-eligible: Expiry 5 days ahead (> 3 days)
    u_safe = {"subscription_expiry": (simulated_now + timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")}
    assert classify_reminder(u_safe, is_trial_user=False, now_utc=simulated_now) is None

    # Non-eligible: Already expired (diff < 0)
    u_expired = {"subscription_expiry": (simulated_now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")}
    assert classify_reminder(u_expired, is_trial_user=False, now_utc=simulated_now) is None

    # Track B: 24-Hour Free Trial Users
    # 3 hours remaining: Eligible for TRIAL_EXPIRING
    u_trial_3h = {"subscription_expiry": (simulated_now + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")}
    assert classify_reminder(u_trial_3h, is_trial_user=True, now_utc=simulated_now) == "TRIAL_EXPIRING"

    # 1 hour remaining: Eligible for TRIAL_EXPIRING
    u_trial_1h = {"subscription_expiry": (simulated_now + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")}
    assert classify_reminder(u_trial_1h, is_trial_user=True, now_utc=simulated_now) == "TRIAL_EXPIRING"

    # 5 hours remaining (> 4 hours): Not eligible yet
    u_trial_5h = {"subscription_expiry": (simulated_now + timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S")}
    assert classify_reminder(u_trial_5h, is_trial_user=True, now_utc=simulated_now) is None

    # 5 minutes remaining (<= 10 min): Too late / ignored
    u_trial_5m = {"subscription_expiry": (simulated_now + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")}
    assert classify_reminder(u_trial_5m, is_trial_user=True, now_utc=simulated_now) is None

    # Paid subscriber with 3 hours left gets DAY_1, NEVER TRIAL_EXPIRING
    assert classify_reminder(u_trial_3h, is_trial_user=False, now_utc=simulated_now) == "DAY_1"
    print("   [PASS] Classification logic for Track A (regular) and Track B (trial) all passed.")

    # ==================== 3. TYPOGRAPHY & FORMATTING ====================
    print("\n>>> 3. Testing Typography & Clean Bold Formatting (NO Italics)...")
    for r_type in ["DAY_3", "DAY_2", "DAY_1", "TRIAL_EXPIRING"]:
        for script in ["lat", "cyr"]:
            text, kb_markup = format_reminder_message(r_type, script=script)
            
            # Assert bold tags exist
            assert "<b>" in text and "</b>" in text, f"Bold tags must be present in {r_type} ({script})"
            
            # Assert NO italic/cursive tags exist
            assert "<i>" not in text, f"Italic tag <i> found in {r_type} ({script})"
            assert "</i>" not in text, f"Italic tag </i> found in {r_type} ({script})"
            assert "<em>" not in text, f"Tag <em> found in {r_type} ({script})"
            assert "</em>" not in text, f"Tag </em> found in {r_type} ({script})"
            assert "*" not in text, f"Markdown italic * found in {r_type} ({script})"
            
            # Assert button exists and points to 'show_plans'
            all_callbacks = [btn.callback_data for row in kb_markup.inline_keyboard for btn in row]
            assert "show_plans" in all_callbacks, f"show_plans action must be present in {r_type} keyboard"

    print("   [PASS] All reminder texts strictly enforce bold tags with ZERO cursive/italics.")

    # ==================== 4. DATABASE IDEMPOTENCY & RENEWAL ====================
    print("\n>>> 4. Testing Database Operations & Strict Idempotency...")
    test_user_id = 888001
    expiry_cycle_1 = "2026-09-28 12:00:00"

    # Initial check
    assert not await db.has_subscription_reminder_been_sent(test_user_id, "DAY_3", expiry_cycle_1)

    # Record reminder
    ok = await db.record_subscription_reminder(test_user_id, "DAY_3", expiry_cycle_1)
    assert ok is True
    assert await db.has_subscription_reminder_been_sent(test_user_id, "DAY_3", expiry_cycle_1)

    # Attempt duplicate insert -> must return False and not raise unhandled exception
    duplicate_ok = await db.record_subscription_reminder(test_user_id, "DAY_3", expiry_cycle_1)
    assert duplicate_ok is False, "Duplicate reminder record must return False"

    # Different reminder type for same expiry cycle is allowed (e.g. DAY_2 next day)
    ok_day2 = await db.record_subscription_reminder(test_user_id, "DAY_2", expiry_cycle_1)
    assert ok_day2 is True

    # After Renewal: Expiry changes to expiry_cycle_2
    expiry_cycle_2 = "2026-10-28 12:00:00"
    assert not await db.has_subscription_reminder_been_sent(test_user_id, "DAY_3", expiry_cycle_2), \
        "New subscription cycle must allow fresh reminders!"
    print("   [PASS] Database idempotency and renewal cycle separation verified.")

    # ==================== 5. END-TO-END SCHEDULER DISPATCH PASS ====================
    print("\n>>> 5. Testing Scheduler Evaluation Pass with Mock Bot...")
    
    # Setup test users
    # Driver A: Paid VIP with 2.5 days left -> DAY_3
    driver_a = 888101
    await db.get_or_create_user(driver_a, "Ali Haydovchi", "ali_driver")
    exp_a = (simulated_now + timedelta(days=2, hours=12)).strftime("%Y-%m-%d %H:%M:%S")

    # Driver B: Paid VIP with 1.5 days left -> DAY_2 (Cyrillic)
    driver_b = 888102
    await db.get_or_create_user(driver_b, "Vali Haydovchi", "vali_driver")
    exp_b = (simulated_now + timedelta(days=1, hours=12)).strftime("%Y-%m-%d %H:%M:%S")
    await db.set_user_script(driver_b, "cyr")

    # Driver C: Paid VIP with 8 hours left -> DAY_1
    driver_c = 888103
    await db.get_or_create_user(driver_c, "Gani Haydovchi", "gani_driver")
    exp_c = (simulated_now + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")

    # Driver D: 24h Trial Driver with 3 hours left -> TRIAL_EXPIRING
    driver_d = 888104
    await db.get_or_create_user(driver_d, "Sinov Haydovchi", "trial_driver")
    exp_d = (simulated_now + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")

    # Driver E: Paid VIP with 20 days left -> NO reminder
    driver_e = 888105
    await db.get_or_create_user(driver_e, "Uzoq VIP", "uzoq_driver")
    exp_e = (simulated_now + timedelta(days=20)).strftime("%Y-%m-%d %H:%M:%S")

    # Update expirations and trial flags in test DB
    async with aiosqlite.connect(TEST_DB_PATH) as conn:
        await conn.execute("UPDATE users SET subscription_expiry = ? WHERE user_id = ?", (exp_a, driver_a))
        await conn.execute("UPDATE users SET subscription_expiry = ? WHERE user_id = ?", (exp_b, driver_b))
        await conn.execute("UPDATE users SET subscription_expiry = ? WHERE user_id = ?", (exp_c, driver_c))
        await conn.execute("UPDATE users SET subscription_expiry = ?, has_used_trial = 1 WHERE user_id = ?", (exp_d, driver_d))
        await conn.execute("UPDATE users SET subscription_expiry = ? WHERE user_id = ?", (exp_e, driver_e))
        await conn.commit()

    # Mock Bot to track sent messages
    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock(return_value=True)

    scheduler = SubscriptionReminderScheduler(bot=mock_bot, check_interval_seconds=60)

    # Pass 1: Daytime (11:00 Tashkent)
    dispatched = await scheduler.check_and_dispatch(now_utc=simulated_now)
    assert dispatched == 4, f"Expected 4 reminders dispatched, got {dispatched}"
    assert mock_bot.send_message.call_count == 4

    # Verify recipient IDs
    sent_chat_ids = [call.kwargs["chat_id"] for call in mock_bot.send_message.call_args_list]
    assert driver_a in sent_chat_ids
    assert driver_b in sent_chat_ids
    assert driver_c in sent_chat_ids
    assert driver_d in sent_chat_ids
    assert driver_e not in sent_chat_ids
    print("   [PASS] 4 eligible drivers correctly notified on first pass.")

    # Pass 2: Immediate re-run -> Strict idempotency (0 messages sent)
    mock_bot.send_message.reset_mock()
    dispatched_again = await scheduler.check_and_dispatch(now_utc=simulated_now)
    assert dispatched_again == 0, f"Expected 0 on immediate retry, got {dispatched_again}"
    assert mock_bot.send_message.call_count == 0
    print("   [PASS] Second evaluation pass sent 0 messages (100% duplicate prevention).")

    # Pass 3: Nighttime (23:00 Tashkent = 18:00 UTC) -> 0 messages sent
    night_now = datetime(2026, 9, 25, 18, 0, 0)
    mock_bot.send_message.reset_mock()
    dispatched_night = await scheduler.check_and_dispatch(now_utc=night_now)
    assert dispatched_night == 0
    assert mock_bot.send_message.call_count == 0
    print("   [PASS] Outside window pass sent 0 messages (Window restriction respected).")

    # Pass 4: Driver A renews subscription for 30 days -> Reminders immediately drop out
    renewed_exp = (simulated_now + timedelta(days=32)).strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(TEST_DB_PATH) as conn:
        await conn.execute("UPDATE users SET subscription_expiry = ? WHERE user_id = ?", (renewed_exp, driver_a))
        await conn.commit()
    # Re-evaluate
    user_a_updated = await db.get_user(driver_a)
    assert classify_reminder(user_a_updated, is_trial_user=False, now_utc=simulated_now) is None
    print("   [PASS] Subscription extension immediately removes driver from pending reminders.")

    # ==================== 6. SCHEDULER LIFECYCLE ====================
    print("\n>>> 6. Testing Scheduler Lifecycle (Start / Stop)...")
    scheduler.start()
    assert scheduler._is_running is True
    assert scheduler._task is not None and not scheduler._task.done()

    # Calling start() again when running does not create duplicate tasks
    existing_task = scheduler._task
    scheduler.start()
    assert scheduler._task is existing_task

    # Stop scheduler
    scheduler.stop()
    assert scheduler._is_running is False
    assert scheduler._task is None
    print("   [PASS] Scheduler start/stop lifecycle validated.")

    print("\n" + "=" * 75)
    print("ALL VIP EXPIRATION REMINDER TESTS PASSED SUCCESSFULLY! (100%)")
    print("=" * 75)

if __name__ == "__main__":
    asyncio.run(run_reminder_tests())
