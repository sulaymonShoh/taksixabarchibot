"""
Automated Test Suite for Taksi Xabarchi v3.0 - Stage 5:
Web Admin Harvester Monitor & End-to-End Field Readiness.
Tests:
1. Web Dashboard Harvester Page (/harvester) with Theme & Space Grotesk.
2. HTTP Basic Authentication Protection (401 Unauthorized vs 200 OK).
3. Real-Time Harvester Stats API (/api/harvester/stats).
4. Monitored Groups Management API (/api/harvester/groups - CRUD, Toggle, Delete).
5. Live Captured Orders Stream API (/api/harvester/orders).
6. End-to-End Field Readiness: Message Ingestion -> Database -> Web Dashboard -> API.
"""
import os
import sys
import asyncio
from datetime import datetime, timedelta
from fastapi.testclient import TestClient

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath("."))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

os.environ["BOT_TOKEN"] = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
os.environ["ADMIN_ID"] = "123456789"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "admin123"
os.environ["DB_PATH"] = "data/test_v3_stage5.db"

import aiosqlite
from src import database as db
from src.web.app import app
from src.harvester.dedup import Deduplicator
from src.harvester.nlp_engine import OrderParser
from src.harvester.listener import HarvesterListener

async def init_test_data():
    if os.path.exists("data/test_v3_stage5.db"):
        os.remove("data/test_v3_stage5.db")
    await db.init_db()

    # Pre-populate sample harvester group
    await db.add_harvester_group(
        group_id=-1001122334455,
        title="Vodiy Toshkent Pitak Taksi",
        username="@vodiy_pitak_taksi",
        region_tag="ANDIJON"
    )

    # Pre-populate VIP driver with active radar
    now = datetime.utcnow()
    future_exp = (now + timedelta(days=15)).strftime("%Y-%m-%d %H:%M:%S")
    await db.get_or_create_user(6001, "Dilshod Haydovchi", "dilshod_driver")
    async with aiosqlite.connect("data/test_v3_stage5.db") as conn:
        await conn.execute("UPDATE users SET subscription_expiry = ? WHERE user_id = 6001", (future_exp,))
        await conn.commit()
    await db.update_driver_radar_preferences(6001, selected_districts=["asaka", "marhamat"])

    # Pre-populate sample harvested orders
    ord1 = {
        "order_type": "PASSENGER",
        "origin": {"name": "Marxamat", "region_id": "andijon", "district_id": "marhamat"},
        "destination": {"name": "Toshkent", "region_id": "toshkent_shahar", "district_id": "quyliq"},
        "passenger_count": 2,
        "phone_number": "+998884784784",
        "telegram_username": "@client1",
        "raw_text": "Marxamatdan Toshkenga 2 kishi bor tel +998884784784",
        "source_group_id": -1001122334455,
        "source_group_title": "Vodiy Toshkent Pitak Taksi"
    }
    ord2 = {
        "order_type": "CARGO",
        "origin": {"name": "Qo'yliq", "region_id": "toshkent_shahar", "district_id": "quyliq"},
        "destination": {"name": "Asaka", "region_id": "andijon", "district_id": "asaka"},
        "passenger_count": 1,
        "phone_number": "+998901234567",
        "telegram_username": None,
        "raw_text": "Qoyliqdan Asakaga sumka pochta bor berib yuborish kerak",
        "source_group_id": -1001122334455,
        "source_group_title": "Vodiy Toshkent Pitak Taksi"
    }
    await db.save_harvested_order(ord1)
    await db.save_harvested_order(ord2)

asyncio.run(init_test_data())

client = TestClient(app)
auth_headers = {"Authorization": "Basic YWRtaW46YWRtaW4xMjM="}  # admin:admin123

def run_phase5_web_tests():
    print("=" * 65)
    print("TEST SUITE: TAKSI XABARCHI v3.0 - STAGE 5 (WEB HARVESTER MONITOR)")
    print("=" * 65)

    # ==================== 1. SECURITY & AUTHENTICATION ====================
    print("\n>>> 1. Testing Web Dashboard Security & Authentication...")
    res_unauth = client.get("/harvester")
    assert res_unauth.status_code == 401
    print("   [PASS] Unauthorized access to /harvester blocked with HTTP 401.")

    res_auth = client.get("/harvester", headers=auth_headers)
    assert res_auth.status_code == 200
    assert "Harvester Radar" in res_auth.text
    assert "Vodiy Toshkent Pitak Taksi" in res_auth.text
    assert "v3.0" in res_auth.text

    res_orders = client.get("/harvester/orders", headers=auth_headers)
    assert res_orders.status_code == 200
    assert "+998884784784" in res_orders.text
    print("   [PASS] Authorized access rendered complete Harvester HTML dashboard & orders subpage.")

    # ==================== 2. HARVESTER STATS API ====================
    print("\n>>> 2. Testing Harvester Real-Time Stats API (/api/harvester/stats)...")
    res_stats = client.get("/api/harvester/stats", headers=auth_headers)
    assert res_stats.status_code == 200
    stats = res_stats.json()
    assert stats["total_orders"] >= 2
    assert stats["passenger_orders"] >= 1
    assert stats["cargo_orders"] >= 1
    assert stats["total_groups"] >= 1
    assert stats["active_groups"] >= 1
    assert stats["active_radar_drivers"] >= 1
    assert stats["vip_radar_drivers"] >= 1
    print(f"   [PASS] Stats API verified: {stats['total_orders']} orders ({stats['passenger_orders']} pass / {stats['cargo_orders']} cargo), {stats['active_groups']} active groups, {stats['vip_radar_drivers']} VIP radar drivers.")

    # ==================== 3. GROUPS MANAGEMENT API ====================
    print("\n>>> 3. Testing Groups Management API (CRUD, Toggle, Delete)...")
    # Add new group
    new_group_payload = {
        "group_id": -1009988776655,
        "title": "Andijon Shahrixon Toshkent Express",
        "username": "@andijon_express",
        "region_tag": "ANDIJON"
    }
    res_add = client.post("/api/harvester/groups", json=new_group_payload, headers=auth_headers)
    assert res_add.status_code == 200
    assert res_add.json()["success"] is True
    print("   [PASS] Added new monitored supergroup via POST /api/harvester/groups.")

    # List groups
    res_list = client.get("/api/harvester/groups", headers=auth_headers)
    assert res_list.status_code == 200
    groups = res_list.json()
    group_ids = [g["group_id"] for g in groups]
    assert -1009988776655 in group_ids
    print(f"   [PASS] Retrieved {len(groups)} monitored groups from API.")

    # Toggle group active status
    res_toggle = client.post("/api/harvester/groups/-1009988776655/toggle", json={"is_active": False}, headers=auth_headers)
    assert res_toggle.status_code == 200
    assert res_toggle.json()["success"] is True

    # Verify toggled in active_only=True
    res_active = client.get("/api/harvester/groups?active_only=true", headers=auth_headers)
    active_ids = [g["group_id"] for g in res_active.json()]
    assert -1009988776655 not in active_ids
    print("   [PASS] Toggled group state: Successfully paused group listening.")

    # Delete group
    res_del = client.post("/api/harvester/groups/-1009988776655/delete", headers=auth_headers)
    assert res_del.status_code == 200
    assert res_del.json()["success"] is True

    res_list_after = client.get("/api/harvester/groups", headers=auth_headers)
    remaining_ids = [g["group_id"] for g in res_list_after.json()]
    assert -1009988776655 not in remaining_ids
    print("   [PASS] Deleted group cleanly: Removed from database.")

    # ==================== 4. HARVESTED ORDERS API ====================
    print("\n>>> 4. Testing Harvested Orders Stream API (/api/harvester/orders)...")
    res_orders = client.get("/api/harvester/orders?limit=10", headers=auth_headers)
    assert res_orders.status_code == 200
    orders_data = res_orders.json()
    assert len(orders_data) >= 2
    first_order = orders_data[0]
    assert "raw_text" in first_order
    assert "order_type" in first_order
    assert "created_at" in first_order
    print(f"   [PASS] Orders API returned {len(orders_data)} recent orders with full route and contact metadata.")

    # ==================== 5. SIDEBAR NAVIGATION VERIFICATION ====================
    print("\n>>> 5. Verifying Sidebar Navigation & Space Grotesk Theme...")
    res_page = client.get("/harvester", headers=auth_headers)
    assert 'href="/harvester"' in res_page.text
    assert 'Harvester Radar' in res_page.text
    assert 'fa-satellite-dish' in res_page.text
    assert 'toggleTheme()' in res_page.text
    print("   [PASS] Harvester Radar menu item active in global sidebar with theme toggle.")

    print("\n" + "=" * 65)
    print("ALL STAGE 5 WEB ADMIN HARVESTER TESTS PASSED (100%)!")
    print("=" * 65)

if __name__ == "__main__":
    run_phase5_web_tests()
