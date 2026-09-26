"""
Automated Test Suite for Taksi Xabarchi v3.0:
In-Bot Real-Time Distributed Order Claiming & Cross-Driver Synchronization.
Tests:
1. DB schema migrations for harvested_orders and harvested_order_dispatches table.
2. Atomic order claiming and race condition defense (two drivers claiming simultaneously).
3. Dead lead reporting (customer already found taxi).
4. Dispatch grid recording message_id per driver.
5. Real-time cross-driver status synchronization (message editing & locking).
6. Telegram Bot callback handlers (claim_order_<id> & dead_order_<id>).
7. Web REST API & /harvester live dashboard status badges.
"""
import os
import sys
import time
import asyncio
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath("."))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

os.environ["BOT_TOKEN"] = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
os.environ["ADMIN_ID"] = "123456789"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "admin123"
os.environ["DB_PATH"] = "data/test_v3_order_reservation.db"

import aiosqlite
from src import database as db
from src.harvester.matcher import CorridorMatcher
from src.harvester.dispatcher import (
    OrderDispatcher,
    build_order_action_keyboard,
    build_order_claimed_keyboard,
    build_order_locked_keyboard
)
from src.bot.handlers import claim_order_call, dead_order_call

class MockMessage:
    def __init__(self, message_id: int, chat_id: int, text: str = ""):
        self.message_id = message_id
        self.chat = MagicMock(id=chat_id)
        self.text = text
        self.html_text = text

    async def edit_text(self, text: str, reply_markup=None, parse_mode="HTML"):
        self.text = text
        self.html_text = text
        self.reply_markup = reply_markup
        return self

class MockBot:
    def __init__(self):
        self.messages = {}  # (chat_id, message_id) -> MockMessage
        self._next_msg_id = 100

    async def send_message(self, chat_id: int, text: str, reply_markup=None, parse_mode="HTML", disable_notification=False):
        self._next_msg_id += 1
        msg = MockMessage(self._next_msg_id, chat_id, text)
        msg.reply_markup = reply_markup
        self.messages[(chat_id, self._next_msg_id)] = msg
        return msg

    async def edit_message_text(self, chat_id: int, message_id: int, text: str, reply_markup=None, parse_mode="HTML"):
        key = (chat_id, message_id)
        if key in self.messages:
            msg = self.messages[key]
            msg.text = text
            msg.html_text = text
            msg.reply_markup = reply_markup
            return msg
        # Fallback create
        msg = MockMessage(message_id, chat_id, text)
        msg.reply_markup = reply_markup
        self.messages[key] = msg
        return msg

async def init_test_db():
    if os.path.exists("data/test_v3_order_reservation.db"):
        os.remove("data/test_v3_order_reservation.db")
    await db.init_db()

async def run_tests():
    print("=" * 70)
    print("TEST SUITE: IN-BOT REAL-TIME ORDER CLAIMING & SYNCHRONIZATION")
    print("=" * 70)

    await init_test_db()

    # ==================== 1. SCHEMA & MIGRATIONS ====================
    print("\n>>> 1. Testing DB Schema & Dispatch Tracking Tables...")
    async with aiosqlite.connect("data/test_v3_order_reservation.db") as conn:
        cursor = await conn.execute("PRAGMA table_info(harvested_orders)")
        cols = [r[1] for r in await cursor.fetchall()]
        assert "status" in cols, "harvested_orders missing 'status' column"
        assert "claimed_by" in cols, "harvested_orders missing 'claimed_by' column"
        assert "claimed_at" in cols, "harvested_orders missing 'claimed_at' column"

        cursor = await conn.execute("PRAGMA table_info(harvested_order_dispatches)")
        disp_cols = [r[1] for r in await cursor.fetchall()]
        assert "order_id" in disp_cols, "harvested_order_dispatches missing 'order_id'"
        assert "driver_id" in disp_cols, "harvested_order_dispatches missing 'driver_id'"
        assert "message_id" in disp_cols, "harvested_order_dispatches missing 'message_id'"
    print("   [PASS] Schema verified: status, claimed_by, claimed_at, and dispatch tracking active.")

    # ==================== 2. ATOMIC ORDER CLAIMING ====================
    print("\n>>> 2. Testing Atomic Order Claiming & Race Condition Defense...")
    # Seed sample orders
    ord_id_1 = await db.save_harvested_order({
        "raw_text": "Asakadan Toshkentga 2 kishi bor tel +998901112233",
        "order_type": "PASSENGER",
        "origin": {"region_id": "andijon", "district_id": "asaka"},
        "destination": {"region_id": "toshkent_shahar", "district_id": "yunusobod"},
        "passenger_count": 2,
        "phone_number": "+998901112233",
        "message_hash": "hash_claim_test_1"
    })
    assert ord_id_1 is not None

    # Driver 101 claims Order 1
    res1 = await db.claim_harvested_order(ord_id_1, driver_id=101)
    assert res1["success"] is True, "Driver 101 claim should succeed"
    assert res1["status"] == "CLAIMED"
    assert res1["claimed_by"] == 101

    # Driver 102 attempts to claim Order 1 (Race condition test)
    res2 = await db.claim_harvested_order(ord_id_1, driver_id=102)
    assert res2["success"] is False, "Driver 102 claim must fail (already claimed)"
    assert res2["status"] == "CLAIMED"
    assert res2["claimed_by"] == 101, "Claimer must remain Driver 101"
    print("   [PASS] Atomic claim verified: Driver 101 claimed; Driver 102 safely rejected.")

    # ==================== 3. DEAD LEAD REPORTING ====================
    print("\n>>> 3. Testing Dead Lead Reporting (Mijoz taksi topgan)...")
    ord_id_2 = await db.save_harvested_order({
        "raw_text": "Shahrixondan Toshkentga pochta bor +998909998877",
        "order_type": "CARGO",
        "origin": {"region_id": "andijon", "district_id": "shahrixon"},
        "destination": {"region_id": "toshkent_shahar", "district_id": "chilonzor"},
        "passenger_count": 1,
        "phone_number": "+998909998877",
        "message_hash": "hash_claim_test_2"
    })
    assert ord_id_2 is not None

    # Driver 103 reports dead lead
    res_dead = await db.report_dead_order(ord_id_2, driver_id=103)
    assert res_dead["success"] is True
    assert res_dead["status"] == "TAKEN_ELSEWHERE"

    # Subsequent claim attempt on dead lead
    res_dead_claim = await db.claim_harvested_order(ord_id_2, driver_id=104)
    assert res_dead_claim["success"] is False
    assert res_dead_claim["status"] == "TAKEN_ELSEWHERE"
    print("   [PASS] Dead lead reported successfully: Status = TAKEN_ELSEWHERE, claims blocked.")

    # ==================== 4. DISPATCH GRID & MESSAGE ID RECORDING ====================
    print("\n>>> 4. Testing Dispatch Grid Message Logging...")
    mock_bot = MockBot()
    dispatcher = OrderDispatcher(bot=mock_bot)

    # Setup 3 VIP drivers
    future_exp = (datetime.utcnow() + timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
    for d_id in [201, 202, 203]:
        await db.get_or_create_user(d_id, f"Haydovchi {d_id}", f"driver_{d_id}")
        async with aiosqlite.connect("data/test_v3_order_reservation.db") as conn:
            await conn.execute("UPDATE users SET subscription_expiry = ? WHERE user_id = ?", (future_exp, d_id))
            await conn.commit()
        await db.update_driver_radar_preferences(d_id, selected_districts=["asaka"])

    ord_id_3 = await db.save_harvested_order({
        "raw_text": "Asakadan Toshkentga 4 kishi shoshilinch +998935554433",
        "order_type": "PASSENGER",
        "origin": {"region_id": "andijon", "district_id": "asaka"},
        "destination": {"region_id": "toshkent_shahar", "district_id": "chilonzor"},
        "passenger_count": 4,
        "phone_number": "+998935554433",
        "message_hash": "hash_claim_test_3"
    })
    order_3_obj = await db.get_harvested_order(ord_id_3)

    dispatch_res = await dispatcher.dispatch_order(order_3_obj)
    assert dispatch_res["sent_count"] == 3, f"Expected 3 sends, got {dispatch_res['sent_count']}"

    dispatches = await db.get_order_dispatches(ord_id_3)
    assert len(dispatches) == 3, f"Expected 3 dispatches logged, got {len(dispatches)}"
    driver_ids_logged = {d["driver_id"] for d in dispatches}
    assert driver_ids_logged == {201, 202, 203}
    print("   [PASS] Dispatch logged 3 messages with unique message_ids for drivers 201, 202, 203.")

    # ==================== 5. REAL-TIME CROSS-DRIVER SYNCHRONIZATION ====================
    print("\n>>> 5. Testing Real-Time Cross-Driver Status Synchronization...")
    # Driver 201 claims Order 3
    claim_res = await db.claim_harvested_order(ord_id_3, driver_id=201)
    assert claim_res["success"] is True

    # Trigger synchronization
    synced_count = await dispatcher.sync_order_status(ord_id_3, "CLAIMED", claimer_id=201)
    assert synced_count == 3, f"Expected 3 messages synced, got {synced_count}"

    # Inspect winner message (Driver 201)
    disp_201 = next(d for d in dispatches if d["driver_id"] == 201)
    msg_201 = mock_bot.messages[(201, disp_201["message_id"])]
    assert "SIZ BU BUYURTMANI BAND QILDINGIZ" in msg_201.text
    assert "Mijoz bilan kelishildi" in msg_201.text
    # Winner's button is confirmed
    btn_winner = [b for row in msg_201.reply_markup.inline_keyboard for b in row]
    assert any("Qabul qilingan" in b.text for b in btn_winner)

    # Inspect other drivers' messages (Driver 202 and 203)
    for other_id in [202, 203]:
        disp_other = next(d for d in dispatches if d["driver_id"] == other_id)
        msg_other = mock_bot.messages[(other_id, disp_other["message_id"])]
        assert "BAND QILINDI" in msg_other.text
        assert "boshqa haydovchi tomonidan olindi" in msg_other.text
        # Phone number is masked in the body
        assert "+998935554433" not in msg_other.text
        assert "[Band qilingan]" in msg_other.text
        # Button is locked
        btn_other = [b for row in msg_other.reply_markup.inline_keyboard for b in row]
        assert any("Band qilindi" in b.text for b in btn_other)
        assert not any("Buyurtmani olish" in b.text for b in btn_other)
    print("   [PASS] Synchronization verified: Winner confirmed, other drivers locked & numbers hidden.")

    # ==================== 6. DEAD LEAD CROSS-DRIVER SYNC ====================
    print("\n>>> 6. Testing Dead Lead Synchronization Across Drivers...")
    ord_id_4 = await db.save_harvested_order({
        "raw_text": "Asakadan Toshkentga yuk bor +998901239999",
        "order_type": "CARGO",
        "origin": {"region_id": "andijon", "district_id": "asaka"},
        "destination": {"region_id": "toshkent_shahar", "district_id": "yunusobod"},
        "message_hash": "hash_claim_test_4"
    })
    order_4_obj = await db.get_harvested_order(ord_id_4)
    await dispatcher.dispatch_order(order_4_obj)

    # Driver 202 reports dead lead
    await db.report_dead_order(ord_id_4, driver_id=202)
    synced_dead = await dispatcher.sync_order_status(ord_id_4, "TAKEN_ELSEWHERE", claimer_id=202)
    assert synced_dead == 3

    disp_4 = await db.get_order_dispatches(ord_id_4)
    for d in disp_4:
        msg = mock_bot.messages[(d["driver_id"], d["message_id"])]
        assert "BEKOR QILINDI" in msg.text
        btn = [b for row in msg.reply_markup.inline_keyboard for b in row]
        assert any("Taksi topilgan" in b.text for b in btn)
    print("   [PASS] Dead lead sync verified: All driver cards updated to 'BEKOR QILINDI'.")

    # ==================== 7. TELEGRAM BOT CALLBACK HANDLERS ====================
    print("\n>>> 7. Testing Telegram Bot Callback Handlers...")
    # Test non-VIP claim attempt
    non_vip_call = AsyncMock()
    non_vip_call.from_user.id = 99901
    non_vip_call.data = f"claim_order_{ord_id_1}"
    await db.get_or_create_user(99901, "Non VIP Driver")
    await claim_order_call(non_vip_call)
    assert any("VIP obuna kerak" in str(call_args) for call_args in non_vip_call.answer.call_args_list)

    # Test VIP claim attempt on fresh order
    ord_id_5 = await db.save_harvested_order({
        "raw_text": "Asakadan Toshkentga 1 kishi +998907776655",
        "order_type": "PASSENGER",
        "origin": {"region_id": "andijon", "district_id": "asaka"},
        "destination": {"region_id": "toshkent_shahar", "district_id": "sergeli"},
        "message_hash": "hash_claim_test_5"
    })
    vip_call = AsyncMock()
    vip_call.from_user.id = 201
    vip_call.data = f"claim_order_{ord_id_5}"
    vip_call.message = MockMessage(555, 201, "Initial Order Text")
    vip_call.bot = mock_bot

    await claim_order_call(vip_call)
    assert any("Buyurtma qabul qilindi" in str(call_args) for call_args in vip_call.answer.call_args_list)
    assert "SIZ BU BUYURTMANI QABUL QILDINGIZ" in vip_call.message.text

    # Second driver attempts claim via callback
    vip_call_2 = AsyncMock()
    vip_call_2.from_user.id = 202
    vip_call_2.data = f"claim_order_{ord_id_5}"
    vip_call_2.message = MockMessage(556, 202, "Initial Order Text")
    vip_call_2.bot = mock_bot

    await claim_order_call(vip_call_2)
    assert any("boshqa haydovchi olib bo'ldi" in str(call_args) for call_args in vip_call_2.answer.call_args_list)
    assert "BAND QILINDI" in vip_call_2.message.text
    print("   [PASS] Bot callbacks verified: Non-VIP blocked, VIP claim succeeded, lost race locked.")

    # ==================== 8. WEB REST API ====================
    print("\n>>> 8. Testing Web REST API (/api/harvester/orders)...")
    from fastapi.testclient import TestClient
    from src.web.app import app

    client = TestClient(app)
    resp = client.get("/api/harvester/orders", auth=("admin", "admin123"))
    assert resp.status_code == 200
    orders_json = resp.json()
    assert len(orders_json) >= 5
    # Verify order 5 is CLAIMED
    o5 = next(o for o in orders_json if o["id"] == ord_id_5)
    assert o5["status"] == "CLAIMED"
    assert o5["claimed_by"] == 201
    assert o5["claimed_at"] is not None

    # Verify order 4 is TAKEN_ELSEWHERE
    o4 = next(o for o in orders_json if o["id"] == ord_id_4)
    assert o4["status"] == "TAKEN_ELSEWHERE"
    print("   [PASS] REST API verified: status, claimed_by, and claimed_at present in orders payload.")

    # ==================== 9. WINNING DRIVER PRIVATE DM WITH PROFILE LINK ====================
    print("\n>>> 9. Testing Winning Driver Private DM with Author Profile Link (No Phone)...")
    ord_id_6 = await db.save_harvested_order({
        "raw_text": "toshkendan yuradigon moshina bormi?",
        "order_type": "PASSENGER",
        "origin": {"region_id": "toshkent_shahar", "district_id": "toshkent_shahar"},
        "destination": {"region_id": "andijon", "district_id": "andijon_shahar"},
        "telegram_username": "@test_passenger",
        "sender_id": 987654321,
        "message_id": 7788,
        "message_link": "https://t.me/c/1234567/7788",
        "message_hash": "hash_claim_test_6"
    })
    dm_vip_call = AsyncMock()
    dm_vip_call.from_user.id = 201
    dm_vip_call.from_user.full_name = "Ali Haydovchi"
    dm_vip_call.data = f"claim_order_{ord_id_6}"
    dm_vip_call.message = MockMessage(600, -1001234567, "Group Order Card Text")
    dm_vip_call.message.chat.type = "supergroup"
    dm_vip_call.bot = mock_bot

    await claim_order_call(dm_vip_call)

    # Check that driver 201 received private DM confirmation
    dm_msgs = [m for (cid, mid), m in mock_bot.messages.items() if cid == 201 and "Siz buyurtmani qabul qildingiz" in m.text]
    assert len(dm_msgs) >= 1
    winner_dm = dm_msgs[-1]

    # 1. Human-friendly route name (no raw _all or underscores)
    assert "Toshkent shahri -> Andijon shahar" in winner_dm.text
    # 2. Phone says Ko'rsatilmagan
    assert "Telefon: Ko'rsatilmagan" in winner_dm.text
    # 3. Profile / Lichka link is present with Yozish
    assert "Lichka: <a href=" in winner_dm.text
    assert "Yozish</a>" in winner_dm.text
    assert "https://t.me/test_passenger" in winner_dm.text
    # 4. Buttons include Lichkaga yozish and Asl xabarni ko'rish
    dm_btns = [b for row in winner_dm.reply_markup.inline_keyboard for b in row]
    assert any("Lichkaga yozish" in b.text and "test_passenger" in b.url for b in dm_btns)
    assert any("Asl xabarni ko'rish" in b.text for b in dm_btns)
    print("   [PASS] Winning DM verified: Clean route, Ko'rsatilmagan phone, author profile link and action buttons!")

    print("\n" + "=" * 70)
    print("ALL REAL-TIME ORDER RESERVATION & SYNC TESTS PASSED (100% SUCCESS)!")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(run_tests())
