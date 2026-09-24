"""
Automated Test Suite for Taksi Xabarchi v3.0:
Group Quality Analytics (Guruhlar Sifati Tahlili) & Intelligence Engine.
Tests:
1. Database schema migration with quality analytics columns.
2. Ingestion of Passenger & Cargo orders and metric tracking.
3. Real-time spam buffering & batched database persistence.
4. Quality score formula calculation, tier grading (A/B/C) & recommendations.
5. Aggregated analytics intelligence (avg quality, spam rate, goldmines, spam pits).
6. Web REST API endpoint (/api/harvester/analytics).
7. SuperAdmin Bot UI callback handler (admin_group_analytics).
"""
import os
import sys
import asyncio
import base64
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath("."))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

os.environ["BOT_TOKEN"] = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
os.environ["ADMIN_ID"] = "123456789"
os.environ["ADMIN_USERNAME"] = "zypherus"
os.environ["ADMIN_PASSWORD"] = "Qoriy006$"
os.environ["DB_PATH"] = "data/test_v3_analytics.db"

import aiosqlite
from src import database as db
from src.config import ADMIN_ID
from src.harvester.listener import HarvesterListener
from src.harvester.nlp_engine import OrderParser
from src.harvester.dedup import Deduplicator
from src.web.app import app
from src.bot import keyboards as kb
from src.bot.handlers import admin_group_analytics_call, group_info_call

async def init_test_db():
    if os.path.exists("data/test_v3_analytics.db"):
        os.remove("data/test_v3_analytics.db")
    await db.init_db()

def run_group_analytics_tests():
    print("=" * 70)
    print("TEST SUITE: GROUP QUALITY ANALYTICS & SPAM INTELLIGENCE")
    print("=" * 70)

    async def _async_tests():
        await init_test_db()

        # ==================== 1. DATABASE SCHEMA MIGRATION ====================
        print("\n>>> 1. Testing Harvester Groups Analytics Schema...")
        async with aiosqlite.connect(db.DB_PATH) as conn:
            async with conn.execute("PRAGMA table_info(harvester_groups)") as cur:
                columns = [row[1] for row in await cur.fetchall()]
        assert "total_messages_seen" in columns
        assert "passenger_orders" in columns
        assert "cargo_orders" in columns
        assert "spam_messages" in columns
        assert "last_order_at" in columns
        print("   [PASS] harvester_groups table contains all analytics tracking columns.")

        # ==================== 2. SEED SAMPLE GROUPS & ORDERS ====================
        print("\n>>> 2. Populating Test Supergroups & Ingesting Orders...")
        # Group 1: High Quality "Goldmine" Group (Asaka Pitak)
        g1_id = -1001111111111
        await db.add_harvester_group(g1_id, "Asaka Toshkent Pitak", "@asaka_pitak", "andijon:asaka")

        # Group 2: Moderate Group (Andijon Express)
        g2_id = -1002222222222
        await db.add_harvester_group(g2_id, "Andijon Toshkent Express", "@andijon_express", "andijon")

        # Group 3: Low Quality Spam Pit (Reklama Bozori)
        g3_id = -1003333333333
        await db.add_harvester_group(g3_id, "Vodiy Taksi Reklama Bozori", "@reklama_bozor", "ALL")

        # Ingest 3 passenger orders and 1 cargo order into Group 1
        for i in range(3):
            await db.save_harvested_order({
                "message_hash": f"hash_p_g1_{i}",
                "raw_text": f"Asakadan Toshkentga 2 kishi bor tel 90111223{i}",
                "order_type": "PASSENGER",
                "origin": {"region_id": "andijon", "district_id": "asaka"},
                "destination": {"region_id": "toshkent_shahar", "district_id": "quyliq"},
                "source_group_id": g1_id,
                "source_group_title": "Asaka Toshkent Pitak"
            })

        await db.save_harvested_order({
            "message_hash": "hash_c_g1_0",
            "raw_text": "Qoyliqdan Asakaga kichik sumka pochta bor tel 909998877",
            "order_type": "CARGO",
            "origin": {"region_id": "toshkent_shahar", "district_id": "quyliq"},
            "destination": {"region_id": "andijon", "district_id": "asaka"},
            "source_group_id": g1_id,
            "source_group_title": "Asaka Toshkent Pitak"
        })

        # Ingest 1 passenger order into Group 2
        await db.save_harvested_order({
            "message_hash": "hash_p_g2_0",
            "raw_text": "Andijondan Toshkentga bitta odam bor 912223344",
            "order_type": "PASSENGER",
            "origin": {"region_id": "andijon"},
            "destination": {"region_id": "toshkent_shahar"},
            "source_group_id": g2_id,
            "source_group_title": "Andijon Toshkent Express"
        })

        g1_data = await db.get_harvester_group(g1_id)
        assert g1_data["passenger_orders"] == 3
        assert g1_data["cargo_orders"] == 1
        assert g1_data["total_harvested"] == 4
        assert g1_data["last_order_at"] is not None
        print("   [PASS] Passenger & cargo order breakdown persisted accurately.")

        # ==================== 3. IN-MEMORY BUFFERING & BATCH SPAM RECORDING ====================
        print("\n>>> 3. Testing Real-Time In-Memory Spam Buffering & Persistence...")
        listener = HarvesterListener(parser=OrderParser(), deduplicator=Deduplicator())
        
        # Simulate Group 1: 4 spam ads received
        listener.record_activity(g1_id, seen=4, spam=4)
        # Simulate Group 2: 15 spam ads received
        listener.record_activity(g2_id, seen=15, spam=15)
        # Simulate Group 3 (Spam pit): 100 spam ads, 0 orders
        listener.record_activity(g3_id, seen=100, spam=100)

        assert listener._stats_buffer[g1_id]["spam"] == 4
        assert listener._stats_buffer[g3_id]["spam"] == 100

        # Flush buffer to database
        await listener.flush_stats_buffer()
        assert len(listener._stats_buffer) == 0
        print("   [PASS] In-memory telemetry buffer flushed cleanly to database.")

        # ==================== 4. QUALITY SCORES & GRADING ====================
        print("\n>>> 4. Testing Quality Score Formulas & Tier Grading...")
        g1_eval = await db.get_harvester_group(g1_id)
        # Group 1: 4 orders, 4 spam = 8 total messages -> 50.0% quality
        assert g1_eval["total_messages_seen"] == 8
        assert g1_eval["quality_score"] == 50.0
        assert g1_eval["quality_grade"] in ("A", "B")
        print(f"   [PASS] Group 1 (Asaka): {g1_eval['quality_score']}% ({g1_eval['quality_grade_label']}) - {g1_eval['recommendation']}")

        g2_eval = await db.get_harvester_group(g2_id)
        # Group 2: 1 order, 15 spam = 16 total messages -> ~6.2% quality
        assert g2_eval["total_messages_seen"] == 16
        assert g2_eval["quality_score"] == 6.2
        assert g2_eval["quality_grade"] == "B"
        print(f"   [PASS] Group 2 (Express): {g2_eval['quality_score']}% ({g2_eval['quality_grade_label']})")

        g3_eval = await db.get_harvester_group(g3_id)
        # Group 3: 0 orders, 100 spam = 100 total messages -> 0.0% quality
        assert g3_eval["total_messages_seen"] == 100
        assert g3_eval["quality_score"] == 0.0
        assert g3_eval["quality_grade"] == "C"
        assert "To'xtatish tavsiya" in g3_eval["recommendation"]
        print(f"   [PASS] Group 3 (Spam Pit): {g3_eval['quality_score']}% (Grade C) - Warning recommendation flagged.")

        # ==================== 5. AGGREGATED ANALYTICS INTELLIGENCE ====================
        print("\n>>> 5. Testing Aggregated Quality Intelligence...")
        analytics = await db.get_group_quality_analytics()
        assert analytics["total_groups"] == 3
        assert analytics["active_groups"] == 3
        assert analytics["total_orders"] == 5
        assert analytics["total_passenger"] == 4
        assert analytics["total_cargo"] == 1
        assert analytics["total_spam"] == 119
        assert analytics["total_messages_seen"] == 124
        assert analytics["top_goldmines"][0]["group_id"] == g1_id
        assert analytics["worst_spam"][0]["group_id"] == g3_id
        print(f"   [PASS] Platform Intelligence: Avg Quality: {analytics['avg_quality_score']}%, Spam Rate: {analytics['spam_rate']}%.")

        # ==================== 6. SUPERADMIN BOT UI HANDLERS ====================
        print("\n>>> 6. Testing SuperAdmin Telegram Bot UI Handlers...")
        # Check keyboard
        hub_kb = kb.admin_harvester_hub_kb(userbot_online=True)
        btn_texts = [btn.text for row in hub_kb.inline_keyboard for btn in row]
        assert any("Sifat tahlili" in b for b in btn_texts)
        print("   [PASS] admin_harvester_hub_kb includes 'Sifat tahlili' button.")

        # Test group analytics call
        mock_call = MagicMock()
        mock_call.from_user.id = ADMIN_ID
        mock_call.answer = AsyncMock()
        mock_call.message.edit_text = AsyncMock()

        await admin_group_analytics_call(mock_call)
        assert mock_call.message.edit_text.called
        text_sent = mock_call.message.edit_text.call_args[0][0]
        assert "Guruhlar Sifati va Spam Tahlili" in text_sent
        assert "Top Eng Foydali Guruhlar" in text_sent
        assert "Asaka Toshkent Pitak" in text_sent
        print("   [PASS] admin_group_analytics_call rendered intelligence leaderboard.")

        # Test group info call
        mock_call.data = f"group_info_{g1_id}"
        await group_info_call(mock_call)
        info_text = mock_call.message.edit_text.call_args[0][0]
        assert "Sifat Ko'rsatkichi" in info_text
        assert "50.0%" in info_text
        assert "Yo'lovchilar" in info_text
        print("   [PASS] group_info_call rendered detailed group quality breakdown.")

    asyncio.run(_async_tests())

    # ==================== 7. WEB REST API ENDPOINT ====================
    print("\n>>> 7. Testing Web REST API Endpoint (/api/harvester/analytics)...")
    client = TestClient(app)
    cred_str = base64.b64encode(b"zypherus:Qoriy006$").decode("ascii")
    auth_headers = {"Authorization": f"Basic {cred_str}"}

    res = client.get("/api/harvester/analytics", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert "avg_quality_score" in data
    assert "spam_rate" in data
    assert "top_goldmines" in data
    assert "worst_spam" in data
    assert len(data["top_goldmines"]) >= 1
    print("   [PASS] GET /api/harvester/analytics returned complete analytics payload.")

    print("\n" + "=" * 70)
    print("ALL GROUP QUALITY ANALYTICS TESTS PASSED (100% SUCCESS)!")
    print("=" * 70)

if __name__ == "__main__":
    run_group_analytics_tests()
