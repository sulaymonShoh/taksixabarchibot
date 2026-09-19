import os
import sys
import asyncio
from datetime import datetime, timedelta
from fastapi.testclient import TestClient

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath("."))

os.environ["BOT_TOKEN"] = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
os.environ["ADMIN_ID"] = "123456789"
os.environ["API_ID"] = "12345"
os.environ["API_HASH"] = "0123456789abcdef0123456789abcdef"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "admin123"
os.environ["DB_PATH"] = "data/test_discounts_suite.db"

from src import database as db
from src.bot.handlers import calculate_effective_plan_prices
from src.web.app import app

client = TestClient(app)
auth = ("admin", "admin123")

async def init_test_db():
    if os.path.exists("data/test_discounts_suite.db"):
        os.remove("data/test_discounts_suite.db")
    await db.init_db()
    # Create test users
    await db.get_or_create_user(501, "Test User 1", "user1")
    await db.get_or_create_user(502, "Test User 2", "user2")
    await db.get_or_create_user(503, "Test User 3", "user3")

def run_tests():
    print("=" * 65)
    print("TEST SUITE: CAMPAIGN DISCOUNTS & PROMOCODES ENGINE")
    print("=" * 65)

    asyncio.run(init_test_db())

    # ==================== 1. CAMPAIGN DISCOUNTS ====================
    print(">>> 1. Testing Tiered Per-Plan Campaign Discount Creation & Calculation...")
    plan_rates = {"1": 0, "3": 12, "6": 15, "12": 20}
    camp_id = asyncio.run(db.set_campaign_discount("Bahorgi Chegirma", plan_rates, duration_days=3))
    assert camp_id > 0

    camp = asyncio.run(db.get_active_campaign_discount())
    assert camp is not None
    assert camp["title"] == "Bahorgi Chegirma"
    assert camp["plan_discounts"]["3"] == 12
    assert camp["plan_discounts"]["12"] == 20
    assert camp["remaining_days"] <= 3

    # Price calculations
    prices = calculate_effective_plan_prices(camp)
    assert prices[1]["price"] == 25000
    assert prices[1]["is_discounted"] is False
    assert prices[3]["price"] == 57200  # 65000 * 0.88 = 57200
    assert prices[3]["is_discounted"] is True
    assert prices[6]["price"] == 102000 # 120000 * 0.85 = 102000
    assert prices[12]["price"] == 180000 # 225000 * 0.80 = 180000
    print("   [PASS] Per-plan tiered prices calculated accurately.")

    # Stop campaign test
    asyncio.run(db.stop_campaign_discount())
    stopped_camp = asyncio.run(db.get_active_campaign_discount())
    assert stopped_camp is None
    reverted_prices = calculate_effective_plan_prices(stopped_camp)
    assert reverted_prices[3]["price"] == 65000
    assert reverted_prices[12]["price"] == 225000
    print("   [PASS] Campaign termination cleanly reverted prices to base rates.")

    # ==================== 2. PROMOCODES: DAYS (FREE VIP) ====================
    print(">>> 2. Testing Free VIP Days Promocode Lifecycle & Usage Limits...")
    promo_id = asyncio.run(db.create_promocode(
        code="FREE7VIP",
        discount_type="DAYS",
        discount_value=7,
        duration_days=5,
        max_uses=2
    ))
    assert promo_id > 0

    # User 501 first redemption -> Success (+7 days)
    u1_before = asyncio.run(db.get_user(501))
    success, msg, p_data = asyncio.run(db.redeem_promocode(501, "free7vip"))
    assert success is True
    assert "+7 kun" in msg
    u1_after = asyncio.run(db.get_user(501))
    d1 = datetime.strptime(u1_before["subscription_expiry"], "%Y-%m-%d %H:%M:%S")
    d2 = datetime.strptime(u1_after["subscription_expiry"], "%Y-%m-%d %H:%M:%S")
    assert (d2 - d1).days == 7

    # User 501 second redemption -> Rejected (already used)
    success_dup, msg_dup, _ = asyncio.run(db.redeem_promocode(501, "FREE7VIP"))
    assert success_dup is False
    assert "avval foydalangansiz" in msg_dup

    # User 502 redemption -> Success (used_count reaches 2)
    success_u2, _, _ = asyncio.run(db.redeem_promocode(502, "FREE7VIP"))
    assert success_u2 is True

    # User 503 redemption -> Rejected (max_uses reached 2/2)
    success_u3, msg_u3, _ = asyncio.run(db.redeem_promocode(503, "FREE7VIP"))
    assert success_u3 is False
    assert "limiti tugagan" in msg_u3
    print("   [PASS] Free VIP days granted, 1-use-per-user enforced, and max_uses cap verified.")

    # ==================== 3. PROMOCODES: PERCENT & PLAN TARGETING ====================
    print(">>> 3. Testing Plan-Targeted Percentage Promocode...")
    promo_pct_id = asyncio.run(db.create_promocode(
        code="BIG20",
        discount_type="PERCENT",
        discount_value=20,
        duration_days=7,
        max_uses=50,
        applicable_plans="6,12"
    ))
    assert promo_pct_id > 0

    # Target plan 1 month (Not eligible)
    succ_p1, msg_p1, _ = asyncio.run(db.redeem_promocode(501, "BIG20", target_plan=1))
    assert succ_p1 is False
    assert "faqat 6,12 oylik" in msg_p1

    # Target plan 6 months (Eligible)
    succ_p6, _, promo_obj = asyncio.run(db.redeem_promocode(501, "BIG20", target_plan=6))
    assert succ_p6 is True
    prices_with_promo = calculate_effective_plan_prices(promo=promo_obj)
    assert prices_with_promo[1]["price"] == 25000  # Untouched
    assert prices_with_promo[6]["price"] == 96000  # 120000 * 0.80 = 96000
    assert prices_with_promo[12]["price"] == 180000 # 225000 * 0.80 = 180000
    print("   [PASS] Plan-targeted promocode discount calculated correctly.")

    # ==================== 4. PROMOCODES: EXPIRATION CHECK ====================
    print(">>> 4. Testing Expired Promocode Rejection...")
    expired_id = asyncio.run(db.create_promocode(
        code="OLDEXPIRED",
        discount_type="DAYS",
        discount_value=3,
        duration_days=-1, # Expired in the past
        max_uses=10
    ))
    succ_exp, msg_exp, _ = asyncio.run(db.redeem_promocode(501, "OLDEXPIRED"))
    assert succ_exp is False
    assert "muddati tugagan" in msg_exp
    print("   [PASS] Expired promocodes safely rejected.")

    # ==================== 5. FASTAPI WEB ENDPOINTS ====================
    print(">>> 5. Testing Web UI & REST Endpoints...")
    res_page = client.get("/discounts", auth=auth)
    assert res_page.status_code == 200
    assert "Chegirmalar & Promokodlar" in res_page.text

    # Set campaign via API
    res_api_camp = client.post("/api/discounts/campaign", auth=auth, json={
        "title": "API Test Campaign",
        "duration_days": 5,
        "plan_discounts": {"1": 5, "3": 10, "6": 15, "12": 25}
    })
    assert res_api_camp.status_code == 200
    assert res_api_camp.json()["success"] is True

    # Create promo via API
    res_api_promo = client.post("/api/promocodes", auth=auth, json={
        "code": "WEBPROMO",
        "discount_type": "PERCENT",
        "discount_value": 15,
        "duration_days": 10,
        "max_uses": 25,
        "applicable_plans": "ALL"
    })
    assert res_api_promo.status_code == 200
    p_created_id = res_api_promo.json()["promocode_id"]

    # Toggle promo via API
    res_toggle = client.post(f"/api/promocodes/{p_created_id}/toggle", auth=auth, json={"is_active": False})
    assert res_toggle.status_code == 200

    # Delete promo via API
    res_del = client.delete(f"/api/promocodes/{p_created_id}", auth=auth)
    assert res_del.status_code == 200

    # Stop campaign via API
    res_stop = client.post("/api/discounts/campaign/stop", auth=auth)
    assert res_stop.status_code == 200
    print("   [PASS] Web dashboard and REST APIs all verified.")

    # Clean up test db
    if os.path.exists("data/test_discounts_suite.db"):
        os.remove("data/test_discounts_suite.db")

    print("=" * 65)
    print("ALL DISCOUNTS & PROMOCODES TESTS PASSED CLEANLY (100% SUCCESS)")
    print("=" * 65)

if __name__ == "__main__":
    run_tests()
