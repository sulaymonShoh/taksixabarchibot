"""
Automated Test Suite for Taksi Xabarchi v3.0 - Group Context Tagging & Fallback Routing
Tests:
1. Automatic Geographic Tagging Engine (Titles, Usernames, Cyrillic transliteration).
2. Group Tag Parsing and Display Formatting (Latin & Cyrillic).
3. Database Tag Persistence & Group Updating.
4. Auto-tagging during group addition in HarvesterService.
5. End-to-End Fallback Routing:
   - "toshkentga ketishim kerak. 902219944" from Andijon/Asaka group -> infers origin, alerts driver.
   - General Andijon group -> regional alert to Andijon drivers.
   - Cross-region isolation: Samarqand group message does NOT route to Andijon drivers.
   - Missing destination fallback ("Toshkentdan 2 kishi bor 901234567").
"""
import os
import sys
import asyncio

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath("."))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

os.environ["DB_PATH"] = "data/test_v3_context_tagging.db"

import aiosqlite
from src import database as db
from src.harvester.geo_tagger import detect_group_region, parse_tag_string, format_tag_display
from src.harvester.listener import HarvesterListener
from src.harvester.dedup import Deduplicator
from src.harvester.nlp_engine import OrderParser
from src.harvester.matcher import CorridorMatcher
from src.harvester.service import HarvesterService

async def init_test_db():
    if os.path.exists("data/test_v3_context_tagging.db"):
        os.remove("data/test_v3_context_tagging.db")
    await db.init_db()

async def run_context_tagging_tests():
    print("=" * 70)
    print("TEST SUITE: GROUP CONTEXT TAGGING & SMART FALLBACK ROUTING")
    print("=" * 70)

    await init_test_db()

    # ==================== 1. GEO TAGGER ENGINE TESTS ====================
    print("\n>>> 1. Testing Geographic Detection from Group Names & Usernames...")
    
    # Asaka detection
    r, d = detect_group_region("Asaka Toshkent Vodiy Pitak", "@asaka_taksi")
    assert r == "andijon" and d == "asaka", f"Expected andijon:asaka, got {r}:{d}"
    print("   [PASS] 'Asaka Toshkent Vodiy Pitak' -> andijon:asaka")

    # Cyrillic Asaka detection
    r, d = detect_group_region("Асака Тошкент Питак")
    assert r == "andijon" and d == "asaka", f"Expected andijon:asaka, got {r}:{d}"
    print("   [PASS] 'Асака Тошкент Питак' (Cyrillic) -> andijon:asaka")

    # Shahrixon detection
    r, d = detect_group_region("Shahrixon Express Yo'lovchi Tashish")
    assert r == "andijon" and d == "shahrixon", f"Expected andijon:shahrixon, got {r}:{d}"
    print("   [PASS] 'Shahrixon Express' -> andijon:shahrixon")

    # Bo'ston / Bo'z detection
    r, d = detect_group_region("Bo'z Toshkent Taksi Guruh")
    assert r == "andijon" and d == "boston", f"Expected andijon:boston, got {r}:{d}"
    print("   [PASS] 'Bo'z Toshkent Taksi Guruh' -> andijon:boston")

    # Marhamat detection
    r, d = detect_group_region("Marhamat Vodiy Pitak 24/7")
    assert r == "andijon" and d == "marhamat", f"Expected andijon:marhamat, got {r}:{d}"
    print("   [PASS] 'Marhamat Vodiy Pitak 24/7' -> andijon:marhamat")

    # Samarqand detection (province level)
    r, d = detect_group_region("Samarqand Toshkent Express", "@samarkand_taxi")
    assert r == "samarqand" and d is None, f"Expected samarqand:None, got {r}:{d}"
    print("   [PASS] 'Samarqand Toshkent Express' -> samarqand")

    # Ambiguous title -> defaults to andijon
    r, d = detect_group_region("Vodiy Mashina Bozor 24/7")
    assert r == "andijon", f"Expected andijon, got {r}"
    print("   [PASS] 'Vodiy Mashina Bozor 24/7' (Ambiguous) -> andijon")

    # ==================== 2. TAG PARSING & DISPLAY ====================
    print("\n>>> 2. Testing Tag Parsing and Display Formatting...")
    
    p_reg, p_dist = parse_tag_string("andijon:asaka")
    assert p_reg == "andijon" and p_dist == "asaka"
    disp = format_tag_display(p_reg, p_dist, script="lat")
    assert "Andijon" in disp and "Asaka" in disp
    disp_cyr = format_tag_display(p_reg, p_dist, script="cyr")
    assert "Андижон" in disp_cyr and "Асака" in disp_cyr
    print(f"   [PASS] andijon:asaka -> '{disp}' / '{disp_cyr}'")

    p_reg, p_dist = parse_tag_string("andijon")
    assert p_reg == "andijon" and p_dist is None
    disp_reg = format_tag_display(p_reg, p_dist, script="lat")
    assert "Andijon" in disp_reg
    print(f"   [PASS] andijon -> '{disp_reg}'")

    # ==================== 3. DATABASE CRUD FOR TAGS ====================
    print("\n>>> 3. Testing Database Group Tag CRUD Operations...")
    
    gid_asaka = -100999001
    await db.add_harvester_group(gid_asaka, "Asaka Pitak", "@asakapitak", region_tag="andijon:asaka")
    g = await db.get_harvester_group(gid_asaka)
    assert g["region_tag"] == "andijon:asaka"
    print("   [PASS] Group inserted with tag 'andijon:asaka'.")

    # Update tag to shahrixon
    await db.update_harvester_group_tag(gid_asaka, "andijon:shahrixon")
    g = await db.get_harvester_group(gid_asaka)
    assert g["region_tag"] == "andijon:shahrixon"
    print("   [PASS] Group tag successfully updated to 'andijon:shahrixon'.")

    # Restore to asaka
    await db.update_harvester_group_tag(gid_asaka, "andijon:asaka")

    # ==================== 4. SERVICE AUTO-TAGGING ====================
    print("\n>>> 4. Testing HarvesterService Auto-Tagging on Group Add...")
    service = HarvesterService(session_name="test_session")
    
    # Adding via numeric ID without explicit tag (auto)
    res = await service.resolve_and_join_group(
        target="-100999002",
        region_tag="auto",
        fallback_title="Shahrixon Toshkent Pitak"
    )
    assert res["success"] is True
    assert res["region_tag"] == "andijon:shahrixon"
    print(f"   [PASS] Auto-tagged new group: {res['title']} -> {res['region_tag']}")

    # ==================== 5. USER SCENARIO VERIFICATION ====================
    print("\n>>> 5. Testing The User's Exact Bug Scenario:")
    print("   Incoming text: 'toshkentga ketishim kerak. 902219944'")
    
    # Setup 3 groups:
    # Group 1: Asaka group (-100999001) -> tag: andijon:asaka
    # Group 2: General Andijon group (-100999003) -> tag: andijon
    # Group 3: Samarqand group (-100999004) -> tag: samarqand
    gid_general = -100999003
    gid_samarqand = -100999004
    await db.add_harvester_group(gid_general, "Andijon Toshkent Taksi", None, region_tag="andijon")
    await db.add_harvester_group(gid_samarqand, "Samarqand Express", None, region_tag="samarqand")

    # Setup Driver: Ali, VIP, active radar, direction="both", selected_districts=["asaka"]
    driver_ali = 777001
    await db.get_or_create_user(driver_ali, "Ali Haydovchi", "ali_driver")
    # Grant VIP
    async with aiosqlite.connect(os.environ["DB_PATH"]) as conn:
        await conn.execute("UPDATE users SET subscription_expiry = '2099-01-01 00:00:00' WHERE user_id = ?", (driver_ali,))
        await conn.commit()
    await db.update_driver_radar_preferences(
        driver_ali,
        is_radar_active=1,
        direction="both",
        selected_districts=["asaka"],
        allow_passenger=1,
        allow_cargo=1
    )

    # Setup Driver: Bobur, VIP, active radar, selected_districts=[] (accepts all of Andijon)
    driver_bobur = 777002
    await db.get_or_create_user(driver_bobur, "Bobur Haydovchi", "bobur_driver")
    async with aiosqlite.connect(os.environ["DB_PATH"]) as conn:
        await conn.execute("UPDATE users SET subscription_expiry = '2099-01-01 00:00:00' WHERE user_id = ?", (driver_bobur,))
        await conn.commit()
    await db.update_driver_radar_preferences(
        driver_bobur,
        is_radar_active=1,
        direction="both",
        selected_districts=[],
        allow_passenger=1,
        allow_cargo=1
    )

    dispatched_orders = []
    async def mock_on_order(order):
        matcher = CorridorMatcher()
        matches = await matcher.match_order_to_drivers(order)
        dispatched_orders.append((order, matches))

    listener = HarvesterListener(
        parser=OrderParser(),
        deduplicator=Deduplicator(),
        on_order_callback=mock_on_order
    )
    await listener.reload_monitored_groups()

    # TEST A: Message from Asaka group
    user_msg = "toshkentga ketishim kerak. 902219944"
    dispatched_orders.clear()
    order_a = await listener.process_raw_message(
        chat_id=gid_asaka,
        chat_title="Asaka Pitak",
        text=user_msg,
        sender_username="@yo_lovchi_asaka"
    )

    assert order_a is not None, "Order parser should capture the message"
    assert order_a["phone_number"] == "+998902219944"
    assert order_a["origin"]["id"] == "asaka"
    assert order_a["origin"]["region_id"] == "andijon"
    assert "Asaka" in order_a["origin"]["name"]
    assert order_a["raw_text"] == user_msg, "Raw text MUST remain 100% authentic/verbatim"

    # Verify matching for Driver Ali (selected_districts: ['asaka'])
    assert len(dispatched_orders) == 1
    captured_order, matches = dispatched_orders[0]
    matched_driver_ids = [m["driver_id"] for m in matches]
    assert driver_ali in matched_driver_ids, "Driver Ali (Asaka) MUST receive the order!"
    assert driver_bobur in matched_driver_ids, "Driver Bobur (All Andijon) MUST receive the order!"
    print("   [PASS] Case A (Asaka Group): Inferred origin as Asaka, matched Driver Ali (EXACT) & Bobur (ALL)!")

    # TEST B: Message from General Andijon group
    dispatched_orders.clear()
    order_b = await listener.process_raw_message(
        chat_id=gid_general,
        chat_title="Andijon Toshkent Taksi",
        text="Toshkentga 1 kishi kerak shoshilinch tel 931234567",
        sender_username="@anjan_user"
    )
    assert order_b is not None
    assert order_b["origin"]["region_id"] == "andijon"
    assert order_b["origin"]["district_id"] is None
    
    assert len(dispatched_orders) == 1
    _, matches_b = dispatched_orders[0]
    matched_b_ids = [m["driver_id"] for m in matches_b]
    # Ali has selected_districts=['asaka'], order is general Andijon regional
    # Bobur has selected_districts=[] -> accepts all
    # CorridorMatcher matches REGIONAL for drivers when district is unspecified
    assert driver_bobur in matched_b_ids, "Driver Bobur MUST match general Andijon order!"
    assert driver_ali in matched_b_ids, "Driver Ali MUST match regional Andijon order fallback!"
    print("   [PASS] Case B (General Andijon Group): Inferred origin as Andijon, matched drivers via REGIONAL mode!")

    # TEST C: Cross-region isolation (Samarqand group)
    dispatched_orders.clear()
    order_c = await listener.process_raw_message(
        chat_id=gid_samarqand,
        chat_title="Samarqand Express",
        text="Toshkentga ketadiganlar bormi 1 kishi tel 971234567",
        sender_username="@samarkand_user"
    )
    assert order_c is not None
    assert order_c["origin"]["region_id"] == "samarqand"
    
    assert len(dispatched_orders) == 1
    _, matches_c = dispatched_orders[0]
    matched_c_ids = [m["driver_id"] for m in matches_c]
    assert driver_ali not in matched_c_ids, "Driver Ali MUST NOT receive Samarqand leads!"
    assert driver_bobur not in matched_c_ids, "Driver Bobur MUST NOT receive Samarqand leads!"
    print("   [PASS] Case C (Cross-Region Isolation): Samarqand lead strictly blocked from Andijon drivers!")

    # TEST D: Missing Destination Inferred from Group Tag
    dispatched_orders.clear()
    order_d = await listener.process_raw_message(
        chat_id=gid_asaka,
        chat_title="Asaka Pitak",
        text="Toshkentdan qaytishga 2 kishi bor tel 911234567",
        sender_username="@toshkentdan_asaka"
    )
    assert order_d is not None
    assert order_d["destination"]["id"] == "asaka"
    assert order_d["destination"]["region_id"] == "andijon"
    assert len(dispatched_orders) == 1
    _, matches_d = dispatched_orders[0]
    matched_d_ids = [m["driver_id"] for m in matches_d]
    assert driver_ali in matched_d_ids
    print("   [PASS] Case D (Missing Destination): Inferred destination as Asaka, matched Tashkent->Asaka route!")

    print("\n" + "=" * 70)
    print("ALL GROUP CONTEXT TAGGING & FALLBACK ROUTING TESTS PASSED (100%)!")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(run_context_tagging_tests())
