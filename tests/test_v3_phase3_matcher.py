"""
Automated Test Suite for Taksi Xabarchi v3.0 - Stage 3
Tests:
1. Driver Radar Preferences Database CRUD & Default Generation.
2. Active Radar Drivers Querying & VIP Expiration Evaluation.
3. Bidirectional Route Direction Detection (Toshkent ⇄ Andijon).
4. Exact District Matching vs Transit Corridor Neighbor Matching.
5. Filter Rules (Direction, Passenger vs Cargo, Radar ON/OFF).
6. VIP Enforcement (Expired drivers blocked from leads).
7. Interactive Telegram Keyboards & Notification Card Formatter.
8. High-Speed Latency Benchmark (100,000 evaluations < 1.0s).
"""
import os
import sys
import asyncio
import time
from datetime import datetime, timedelta

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath("."))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

os.environ["DB_PATH"] = "data/test_v3_matcher.db"

import aiosqlite
from src import database as db
from src.harvester.geo_data import is_in_corridor, get_corridor_districts, DISTRICTS
from src.harvester.matcher import CorridorMatcher, default_matcher
from src.bot import keyboards as kb

async def init_test_db():
    if os.path.exists("data/test_v3_matcher.db"):
        os.remove("data/test_v3_matcher.db")
    await db.init_db()

async def run_phase3_async_tests():
    print("=" * 65)
    print("TEST SUITE: TAKSI XABARCHI v3.0 - STAGE 3 (DRIVER RADAR & CORRIDORS)")
    print("=" * 65)

    await init_test_db()

    # ==================== 1. DATABASE PREFERENCES & CRUD ====================
    print("\n>>> 1. Testing Driver Radar Preferences CRUD & Default Generation...")
    driver_ali = 888001
    await db.get_or_create_user(driver_ali, "Ali Haydovchi", "ali_driver")

    # Fetch default preferences
    prefs = await db.get_driver_radar_preferences(driver_ali)
    assert prefs["user_id"] == driver_ali
    assert prefs["is_radar_active"] == 1
    assert prefs["direction"] == "both"
    assert "asaka" in prefs["selected_districts"]
    assert "shahrixon" in prefs["selected_districts"]
    assert "boston" in prefs["selected_districts"]
    assert "andijon_shahar" in prefs["selected_districts"]
    print("   [PASS] Default radar preferences initialized correctly with 4 core districts.")

    # Update preferences
    updated = await db.update_driver_radar_preferences(
        driver_ali,
        direction="toshkent_to_andijon",
        allow_cargo=0,
        sound_alerts=0
    )
    assert updated["direction"] == "toshkent_to_andijon"
    assert updated["allow_cargo"] == 0
    assert updated["sound_alerts"] == 0
    print("   [PASS] Preferences updated (direction=toshkent_to_andijon, cargo=OFF, sound=OFF).")

    # Toggle district (Add Marhamat, remove Bo'ston)
    toggled1 = await db.toggle_driver_district(driver_ali, "marhamat")
    assert "marhamat" in toggled1
    toggled2 = await db.toggle_driver_district(driver_ali, "boston")
    assert "boston" not in toggled2
    print("   [PASS] District toggling verified (Marhamat added, Bo'ston removed).")

    # ==================== 2. ACTIVE RADAR DRIVERS & VIP CHECK ====================
    print("\n>>> 2. Testing Active Radar Drivers & VIP Expiration Evaluation...")
    active_vip = 888002
    expired_vip = 888003
    disabled_radar = 888004

    now = datetime.utcnow()
    future_exp = (now + timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")
    past_exp = (now - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")

    # Driver 2: Active VIP
    await db.get_or_create_user(active_vip, "Vali Haydovchi")
    async with aiosqlite.connect("data/test_v3_matcher.db") as conn:
        await conn.execute("UPDATE users SET subscription_expiry = ? WHERE user_id = ?", (future_exp, active_vip))
        await conn.commit()
    await db.get_driver_radar_preferences(active_vip)

    # Driver 3: Expired VIP
    await db.get_or_create_user(expired_vip, "Gani Haydovchi")
    async with aiosqlite.connect("data/test_v3_matcher.db") as conn:
        await conn.execute("UPDATE users SET subscription_expiry = ? WHERE user_id = ?", (past_exp, expired_vip))
        await conn.commit()
    await db.get_driver_radar_preferences(expired_vip)

    # Driver 4: Disabled Radar
    await db.get_or_create_user(disabled_radar, "Soli Haydovchi")
    async with aiosqlite.connect("data/test_v3_matcher.db") as conn:
        await conn.execute("UPDATE users SET subscription_expiry = ? WHERE user_id = ?", (future_exp, disabled_radar))
        await conn.commit()
    await db.update_driver_radar_preferences(disabled_radar, is_radar_active=0)

    # Fetch active radar drivers
    drivers = await db.get_active_radar_drivers()
    driver_map = {d["user_id"]: d for d in drivers}

    assert active_vip in driver_map
    assert driver_map[active_vip]["is_vip"] is True
    print(f"   [PASS] Active VIP driver #{active_vip} identified as is_vip=True.")

    assert expired_vip in driver_map
    assert driver_map[expired_vip]["is_vip"] is False
    print(f"   [PASS] Expired driver #{expired_vip} identified as is_vip=False.")

    assert disabled_radar not in driver_map
    print(f"   [PASS] Disabled radar driver #{disabled_radar} excluded from active list.")

    # ==================== 3. ROUTE DIRECTION DETECTION ====================
    print("\n>>> 3. Testing Route Direction Detection (Toshkent ⇄ Andijon)...")
    matcher = CorridorMatcher()

    # Toshkent -> Asaka
    d1 = matcher.determine_direction({
        "origin": {"region_id": "toshkent_shahar", "district_id": None},
        "destination": {"region_id": "andijon", "district_id": "asaka"}
    })
    assert d1 == "toshkent_to_andijon"

    # Qo'yliq pitak -> Shahrixon
    d2 = matcher.determine_direction({
        "origin": {"region_id": "toshkent_shahar", "district_id": "quyliq"},
        "destination": {"region_id": "andijon", "district_id": "shahrixon"}
    })
    assert d2 == "toshkent_to_andijon"

    # Marhamat -> Toshkent
    d3 = matcher.determine_direction({
        "origin": {"region_id": "andijon", "district_id": "marhamat"},
        "destination": {"region_id": "toshkent_shahar", "district_id": None}
    })
    assert d3 == "andijon_to_toshkent"

    # Lone destination (Bo'stonga)
    d4 = matcher.determine_direction({
        "origin": None,
        "destination": {"region_id": "andijon", "district_id": "boston"}
    })
    assert d4 == "toshkent_to_andijon"
    print("   [PASS] All 4 route direction patterns accurately classified.")

    # ==================== 4. EXACT & HIGHWAY CORRIDOR MATCHING ====================
    print("\n>>> 4. Testing Exact vs Highway Corridor Transit Matchmaking...")
    driver_asaka_shahrixon = {
        "user_id": 101,
        "is_radar_active": True,
        "is_vip": True,
        "direction": "both",
        "allow_passenger": True,
        "allow_cargo": True,
        "selected_districts": ["asaka", "shahrixon"]
    }

    # Case A: Exact District Match (Destination = Asaka)
    ord_exact = {
        "order_type": "PASSENGER",
        "origin": {"region_id": "toshkent_shahar", "district_id": "quyliq"},
        "destination": {"region_id": "andijon", "district_id": "asaka"},
        "passenger_count": 2
    }
    match_a = matcher.match_driver(ord_exact, driver_asaka_shahrixon)
    assert match_a is not None
    assert match_a["match_type"] == "EXACT"
    assert match_a["matched_district"] == "asaka"
    print("   [PASS] Exact Match: Order for Asaka matched to Asaka driver.")

    # Case B: Corridor Neighbor Match (Destination = Marhamat, via Asaka)
    ord_corridor = {
        "order_type": "PASSENGER",
        "origin": {"region_id": "toshkent_shahar", "district_id": "quyliq"},
        "destination": {"region_id": "andijon", "district_id": "marhamat"},
        "passenger_count": 1
    }
    match_b = matcher.match_driver(ord_corridor, driver_asaka_shahrixon)
    assert match_b is not None
    assert match_b["match_type"] == "CORRIDOR"
    assert match_b["matched_district"] == "marhamat"
    assert match_b["corridor_via"] == "asaka"
    print("   [PASS] Corridor Match: Marhamat order matched via Asaka transit corridor.")

    # Case C: Corridor Pickup Match (Pickup in Marhamat -> Heading to Toshkent)
    ord_pickup = {
        "order_type": "PASSENGER",
        "origin": {"region_id": "andijon", "district_id": "marhamat"},
        "destination": {"region_id": "toshkent_shahar", "district_id": "quyliq"},
        "passenger_count": 3
    }
    match_c = matcher.match_driver(ord_pickup, driver_asaka_shahrixon)
    assert match_c is not None
    assert match_c["match_type"] == "CORRIDOR"
    assert match_c["matched_district"] == "marhamat"
    print("   [PASS] Corridor Pickup: Passenger in Marhamat matched to Asaka driver.")

    # Case D: Far District Mismatch (Destination = Xonobod, far east)
    ord_far = {
        "order_type": "PASSENGER",
        "origin": {"region_id": "toshkent_shahar", "district_id": "quyliq"},
        "destination": {"region_id": "andijon", "district_id": "xonobod"},
        "passenger_count": 1
    }
    match_d = matcher.match_driver(ord_far, driver_asaka_shahrixon)
    assert match_d is None
    print("   [PASS] Mismatch: Xonobod order rejected (outside driver corridor).")

    # ==================== 5. FILTER RULES ====================
    print("\n>>> 5. Testing Direction, Type, and VIP Filtering Rules...")
    driver_strict = {
        "user_id": 202,
        "is_radar_active": True,
        "is_vip": True,
        "direction": "toshkent_to_andijon",
        "allow_passenger": True,
        "allow_cargo": False,
        "selected_districts": ["asaka"]
    }

    # Wrong direction (Andijon -> Toshkent)
    ord_wrong_dir = {
        "order_type": "PASSENGER",
        "origin": {"region_id": "andijon", "district_id": "asaka"},
        "destination": {"region_id": "toshkent_shahar", "district_id": "quyliq"}
    }
    assert matcher.match_driver(ord_wrong_dir, driver_strict) is None
    print("   [PASS] Direction filter: Rejected reverse direction order.")

    # Wrong type (Cargo order when allow_cargo=False)
    ord_cargo = {
        "order_type": "CARGO",
        "origin": {"region_id": "toshkent_shahar", "district_id": "quyliq"},
        "destination": {"region_id": "andijon", "district_id": "asaka"}
    }
    assert matcher.match_driver(ord_cargo, driver_strict) is None
    print("   [PASS] Type filter: Rejected cargo order for passenger-only driver.")

    # Expired VIP driver (enforce_vip=True)
    driver_expired = {
        "user_id": 303,
        "is_radar_active": True,
        "is_vip": False,
        "direction": "both",
        "allow_passenger": True,
        "allow_cargo": True,
        "selected_districts": ["asaka"]
    }
    assert matcher.match_driver(ord_exact, driver_expired, enforce_vip=True) is None
    print("   [PASS] VIP filter: Blocked lead dispatch to expired driver.")

    # Disabled radar (is_radar_active=False)
    driver_disabled = {
        "user_id": 404,
        "is_radar_active": False,
        "is_vip": True,
        "direction": "both",
        "allow_passenger": True,
        "allow_cargo": True,
        "selected_districts": ["asaka"]
    }
    assert matcher.match_driver(ord_exact, driver_disabled) is None
    print("   [PASS] Radar state filter: Blocked lead dispatch to paused radar.")

    # ==================== 6. KEYBOARDS & NOTIFICATION CARDS ====================
    print("\n>>> 6. Testing Keyboards & Driver Alert Notification Card...")
    sample_prefs = {
        "is_radar_active": 1,
        "direction": "both",
        "allow_passenger": 1,
        "allow_cargo": 1,
        "sound_alerts": 1,
        "selected_districts": ["asaka", "shahrixon"]
    }

    # Radar Menu Keyboard
    menu_kb = kb.radar_menu_kb(sample_prefs, is_vip=True)
    assert any("🟢 Radar: YONIQ" in b.text for row in menu_kb.inline_keyboard for b in row)
    assert any("Toshkent ⇄ Andijon" in b.text for row in menu_kb.inline_keyboard for b in row)
    assert any("Tumanlar filtri (2 ta" in b.text for row in menu_kb.inline_keyboard for b in row)
    print("   [PASS] Radar menu keyboard generated with live preference toggles.")

    # District Selection Keyboard
    dist_kb = kb.radar_districts_kb(["asaka", "shahrixon"])
    buttons = [b.text for row in dist_kb.inline_keyboard for b in row]
    assert "✅ Asaka" in buttons
    assert "✅ Shahrixon" in buttons
    assert "⬜️ Marhamat" in buttons
    assert "✅ Barchasini tanlash" in buttons
    assert "⬜️ Tozalash" in buttons
    print("   [PASS] District selector keyboard generated with multi-district checkboxes.")

    # Formatted Alert Card
    test_order = {
        "order_type": "PASSENGER",
        "origin": {"name": "Marxamat"},
        "destination": {"name": "Toshkent"},
        "passenger_count": 2,
        "phone_number": "+998884784784",
        "telegram_username": "@vodiy_taxi",
        "raw_text": "Marxamatdan toshkenga kechasiga 2 ta odam bor +998884784784",
        "message_link": "https://t.me/c/1234567/89"
    }
    card_text = matcher.format_notification(test_order, match_b)
    assert "Yo'lovchi" in card_text
    assert "Marxamatdan toshkenga kechasiga 2 ta odam bor" in card_text
    assert "+998884784784" in card_text
    assert "@vodiy_taxi" in card_text
    assert "Asl xabarni" in card_text
    assert "https://t.me/c/1234567/89" in card_text
    print("   [PASS] Minimal alert card formatted correctly with direct contact and message links.")

    # ==================== 7. LATENCY BENCHMARK ====================
    print("\n>>> 7. Running Latency Benchmark (100,000 evaluations in memory)...")
    mock_drivers = []
    districts_cycle = ["asaka", "shahrixon", "boston", "marhamat", "andijon_shahar"]
    for i in range(100):
        mock_drivers.append({
            "user_id": 1000 + i,
            "is_radar_active": True,
            "is_vip": True,
            "direction": "both" if i % 2 == 0 else "toshkent_to_andijon",
            "allow_passenger": True,
            "allow_cargo": (i % 3 == 0),
            "selected_districts": [districts_cycle[i % len(districts_cycle)]]
        })

    benchmark_orders = [ord_exact, ord_corridor, ord_pickup, ord_cargo]

    start_bench = time.perf_counter()
    eval_count = 0
    for i in range(1000):
        o = benchmark_orders[i % len(benchmark_orders)]
        for drv in mock_drivers:
            matcher.match_driver(o, drv, enforce_vip=True)
            eval_count += 1
    bench_duration = time.perf_counter() - start_bench

    avg_latency_ms = (bench_duration / eval_count) * 1000
    print(f"   [BENCHMARK] Evaluated {eval_count:,} orders in {bench_duration*1000:.2f} ms")
    print(f"   [BENCHMARK] Average evaluation latency: {avg_latency_ms:.5f} ms (~{int(1000/avg_latency_ms):,} matches/sec)")
    assert bench_duration < 1.0, f"Benchmark too slow: {bench_duration}s"
    print("   [PASS] Performance verified: Zero latency overhead, sub-millisecond execution.")

    print("\n" + "=" * 65)
    print("ALL STAGE 3 TESTS PASSED PERFECTLY (100% SUCCESS)!")
    print("=" * 65)

if __name__ == "__main__":
    asyncio.run(run_phase3_async_tests())
