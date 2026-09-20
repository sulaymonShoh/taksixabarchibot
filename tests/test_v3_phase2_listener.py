"""
Automated Test Suite for Taksi Xabarchi v3.0 - Phase 2
Tests:
1. Harvester Groups & Orders Database CRUD Operations.
2. In-Memory Deduplication Engine (Fuzzy text hashes & phone deduplication).
3. End-to-End Ingestion Pipeline (Deduplication -> Fast NLP -> DB Archive).
4. Rejection of driver ads and duplicate posts during live stream.
5. Verification of dispatch callbacks and statistics counters.
"""
import os
import sys
import asyncio
import time

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath("."))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

os.environ["DB_PATH"] = "data/test_v3_harvester.db"

from src import database as db
from src.harvester.dedup import Deduplicator
from src.harvester.nlp_engine import OrderParser
from src.harvester.listener import HarvesterListener

async def init_test_db():
    if os.path.exists("data/test_v3_harvester.db"):
        os.remove("data/test_v3_harvester.db")
    await db.init_db()

async def run_phase2_async_tests():
    print("=" * 65)
    print("TEST SUITE: TAKSI XABARCHI v3.0 - STAGE 2 (HARVESTER LISTENER & DEDUP)")
    print("=" * 65)

    await init_test_db()

    # ==================== 1. DATABASE OPERATIONS ====================
    print("\n>>> 1. Testing Harvester Groups Database CRUD...")
    g1_id = await db.add_harvester_group(-1001111111111, "Vodiy Pitak Taksi", "@vodiypitak", "VODIY")
    g2_id = await db.add_harvester_group(-1002222222222, "Andijon Toshkent Guruh", "@andijontaksi", "ANDIJON")
    g3_id = await db.add_harvester_group(-1003333333333, "Samarqand Taksi 24/7", None, "SAMARQAND")
    assert g1_id > 0 and g2_id > 0 and g3_id > 0
    print("   [PASS] Added 3 harvester groups to database.")

    all_groups = await db.get_harvester_groups()
    assert len(all_groups) == 3
    print("   [PASS] Retrieved all 3 groups.")

    # Toggle group 3 inactive
    await db.toggle_harvester_group(-1003333333333, False)
    active_groups = await db.get_harvester_groups(active_only=True)
    assert len(active_groups) == 2
    assert -1003333333333 not in [g["group_id"] for g in active_groups]
    print("   [PASS] Toggled group active status verified.")

    # Single group retrieval
    g1 = await db.get_harvester_group(-1001111111111)
    assert g1 is not None
    assert g1["title"] == "Vodiy Pitak Taksi"
    print("   [PASS] Single group lookup verified.")

    # ==================== 2. DEDUPLICATION ENGINE ====================
    print("\n>>> 2. Testing In-Memory Deduplication Engine...")
    dedup = Deduplicator(default_ttl_seconds=2) # 2-second TTL for fast test

    sample_text = "Toshkentdan Asakaga 2 kishi bor, tel: 90 123 45 67"
    sample_phone = "+998901234567"

    # First seen -> Not duplicate
    assert dedup.is_duplicate(sample_text, sample_phone) is False
    h = dedup.record(sample_text, sample_phone)
    assert len(h) == 32
    print("   [PASS] New message hash generated and recorded.")

    # Second check -> Duplicate!
    assert dedup.is_duplicate(sample_text, sample_phone) is True
    print("   [PASS] Exact duplicate message correctly identified.")

    # Same phone, slightly different text (e.g. extra emojis or spaces) -> Duplicate!
    alt_text = "Toshkentdan Asakaga 2 kishi bor 🔥🔥🔥 tel: 90 123 45 67"
    assert dedup.is_duplicate(alt_text, sample_phone) is True
    print("   [PASS] Phone-based repeat post correctly blocked.")

    # Wait for TTL to expire
    time.sleep(2.1)
    assert dedup.is_duplicate(sample_text, sample_phone) is False
    print("   [PASS] TTL expiration cleaned cache cleanly.")

    # ==================== 3. END-TO-END INGESTION PIPELINE ====================
    print("\n>>> 3. Testing Real-Time Message Ingestion Pipeline...")
    dispatched_orders = []

    async def mock_dispatch(order):
        dispatched_orders.append(order)

    listener = HarvesterListener(
        parser=OrderParser(),
        deduplicator=Deduplicator(default_ttl_seconds=900),
        on_order_callback=mock_dispatch
    )

    # Test 1: Real passenger message
    msg_pass = "Toshkentdan Asakaga 2 kishi bor, tel: 90 123 45 67"
    res_pass = await listener.process_raw_message(
        chat_id=-1001111111111,
        chat_title="Vodiy Pitak Taksi",
        text=msg_pass,
        sender_username="@alijon"
    )
    assert res_pass is not None
    assert res_pass["order_type"] == "PASSENGER"
    assert res_pass["id"] > 0
    assert len(dispatched_orders) == 1
    print("   [PASS] Passenger message processed, dispatched, and saved to DB.")

    # Test 2: Repeat of exact same passenger message -> Must be dropped by dedup
    res_dup = await listener.process_raw_message(
        chat_id=-1001111111111,
        chat_title="Vodiy Pitak Taksi",
        text=msg_pass
    )
    assert res_dup is None
    assert len(dispatched_orders) == 1 # No second dispatch!
    print("   [PASS] Duplicate message dropped cleanly without DB write.")

    # Test 3: Driver ad -> Must be dropped by NLP engine
    msg_ad = "Cobalt bor, konditsioner bor, Toshkent ➡️ Andijon, tel: 90 123 45 67"
    res_ad = await listener.process_raw_message(
        chat_id=-1001111111111,
        chat_title="Vodiy Pitak Taksi",
        text=msg_ad
    )
    assert res_ad is None
    print("   [PASS] Driver ad rejected by NLP engine during ingestion.")

    # Test 4: Real cargo message
    msg_cargo = "Qo'yliqdan Bo'stonga pochta bor, tel: 90 777 66 55"
    res_cargo = await listener.process_raw_message(
        chat_id=-1002222222222,
        chat_title="Andijon Toshkent Guruh",
        text=msg_cargo
    )
    assert res_cargo is not None
    assert res_cargo["order_type"] == "CARGO"
    assert len(dispatched_orders) == 2
    print("   [PASS] Cargo / Pochta message processed and archived.")

    # Test 5: Colloquial passenger message
    msg_colloquial = "Marxamatdan toshkenga kechasiga 1 ta odam bor +998884784784"
    res_colloquial = await listener.process_raw_message(
        chat_id=-1002222222222,
        chat_title="Andijon Toshkent Guruh",
        text=msg_colloquial
    )
    assert res_colloquial is not None
    assert res_colloquial["destination"]["id"] == "toshkent_shahar_all"
    assert len(dispatched_orders) == 3
    print("   [PASS] Colloquial passenger message processed and archived.")

    # Verify orders in database
    total_orders = await db.get_harvested_orders_count()
    assert total_orders == 3
    recent_orders = await db.get_recent_harvested_orders(limit=10)
    assert len(recent_orders) == 3
    print("   [PASS] Database stores exactly 3 verified orders.")

    # Verify harvester group stats updated
    g1_updated = await db.get_harvester_group(-1001111111111)
    assert g1_updated["total_harvested"] == 1
    g2_updated = await db.get_harvester_group(-1002222222222)
    assert g2_updated["total_harvested"] == 2
    print("   [PASS] Harvester group total_harvested metrics incremented accurately.")

    # Clean up test database
    if os.path.exists("data/test_v3_harvester.db"):
        os.remove("data/test_v3_harvester.db")

    print("\n" + "=" * 65)
    print("ALL STAGE 2 HARVESTER LISTENER & DEDUP TESTS PASSED (100% SUCCESS)")
    print("=" * 65)

def run_tests():
    asyncio.run(run_phase2_async_tests())

if __name__ == "__main__":
    run_tests()
