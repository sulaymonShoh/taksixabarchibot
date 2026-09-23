"""
Automated Test Suite for Taksi Xabarchi v3.0 - On-Demand 24-Hour VIP Trial
Tests:
1. New user registration starts with NO active subscription (clock does not tick automatically).
2. Eligibility check (can_user_claim_trial) returns True for new users.
3. Keyboards (Main Dashboard, Radar Menu, Pricing Plans, Teaser Alert) display 'Bepul sinab ko'rish' button.
4. Language support: Latin and Cyrillic button and message rendering.
5. On-demand trial activation sets subscription_expiry to exactly 24 hours and marks has_used_trial=1.
6. Repeated trial claims are strictly rejected (anti-abuse / idempotent).
7. Active trial grants full VIP driver privileges in Radar matching and alert delivery.
"""
import os
import sys
import asyncio
from datetime import datetime, timedelta

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath("."))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

os.environ["DB_PATH"] = "data/test_v3_vip_trial.db"

import aiosqlite
from src import database as db
from src.bot import keyboards as kb
from src.bot.handlers import check_subscription
from src.harvester.matcher import CorridorMatcher
from src.harvester.dispatcher import build_order_action_keyboard

async def init_test_db():
    if os.path.exists("data/test_v3_vip_trial.db"):
        os.remove("data/test_v3_vip_trial.db")
    await db.init_db()

async def run_vip_trial_tests():
    print("=" * 70)
    print("TEST SUITE: ON-DEMAND 24-HOUR VIP TRIAL SYSTEM")
    print("=" * 70)

    await init_test_db()

    # ==================== 1. USER REGISTRATION (NO AUTO-TICK) ====================
    print("\n>>> 1. Testing Registration Without Auto-Trial...")
    test_user_id = 999101
    user, is_new = await db.get_or_create_user(test_user_id, "Bekzod Haydovchi", "bekzod_driver")
    assert is_new is True
    assert user["subscription_expiry"] is None, "New user MUST NOT have active subscription automatically!"
    assert user.get("has_used_trial", 0) == 0, "New user has_used_trial MUST be 0!"
    print("   [PASS] User created with subscription_expiry = None and has_used_trial = 0.")

    # Check eligibility
    can_claim = await db.can_user_claim_trial(test_user_id)
    assert can_claim is True, "Eligible user should be allowed to claim trial"
    print("   [PASS] can_user_claim_trial returns True for brand new user.")

    # Subscription check
    sub_text, is_active = check_subscription(user["subscription_expiry"], script="lat")
    assert is_active is False
    print(f"   [PASS] Subscription status: {sub_text} (is_active=False).")

    # ==================== 2. KEYBOARD BUTTONS CHECK ====================
    print("\n>>> 2. Testing Keyboards UI for Trial Button...")
    
    # Main Dashboard Keyboard (Latin)
    main_kb = kb.main_dashboard_kb(is_authenticated=True, script="lat", can_claim_trial=True)
    all_callbacks = [btn.callback_data for row in main_kb.inline_keyboard for btn in row]
    assert "claim_trial" in all_callbacks, "claim_trial button MUST be in main_dashboard_kb"
    print("   [PASS] main_dashboard_kb has 'claim_trial' button (Latin).")

    # Main Dashboard Keyboard (Cyrillic)
    main_kb_cyr = kb.main_dashboard_kb(is_authenticated=True, script="cyr", can_claim_trial=True)
    cyr_texts = [btn.text for row in main_kb_cyr.inline_keyboard for btn in row]
    assert any("бепул синаб кўриш" in t.lower() for t in cyr_texts)
    print("   [PASS] main_dashboard_kb has 'бепул синаб кўриш' button (Cyrillic).")

    # Radar Menu Keyboard
    radar_kb = kb.radar_menu_kb({}, is_vip=False, script="lat", can_claim_trial=True)
    radar_callbacks = [btn.callback_data for row in radar_kb.inline_keyboard for btn in row]
    assert "claim_trial" in radar_callbacks, "claim_trial button MUST be in radar_menu_kb"
    print("   [PASS] radar_menu_kb has 'claim_trial' button.")

    # Pricing Plans Keyboard
    pricing_kb = kb.pricing_plans_kb(None, script="lat", can_claim_trial=True)
    pricing_callbacks = [btn.callback_data for row in pricing_kb.inline_keyboard for btn in row]
    assert "claim_trial" in pricing_callbacks, "claim_trial button MUST be in pricing_plans_kb"
    print("   [PASS] pricing_plans_kb has 'claim_trial' button.")

    # Paywall Teaser Alert Keyboard
    teaser_kb = build_order_action_keyboard(123, None, is_vip=False, script="lat", can_claim_trial=True)
    teaser_callbacks = [btn.callback_data for row in teaser_kb.inline_keyboard for btn in row]
    assert "claim_trial" in teaser_callbacks, "claim_trial button MUST be in teaser alert keyboard"
    print("   [PASS] Teaser alert has 1-tap 'claim_trial' conversion button.")

    # ==================== 3. ON-DEMAND TRIAL ACTIVATION ====================
    print("\n>>> 3. Testing On-Demand Trial Activation...")
    success, expiry_str = await db.activate_user_trial(test_user_id, hours=24)
    assert success is True, "Trial activation should succeed"
    print(f"   [PASS] activate_user_trial succeeded! Expiry: {expiry_str}")

    # Verify user record updated in database
    user_updated = await db.get_user(test_user_id)
    assert user_updated["has_used_trial"] == 1
    exp_dt = datetime.strptime(user_updated["subscription_expiry"], '%Y-%m-%d %H:%M:%S')
    now = datetime.utcnow()
    diff = exp_dt - now
    # Should be ~24 hours (between 23 and 24 hours)
    assert 23 <= (diff.total_seconds() / 3600.0) <= 24.1
    print(f"   [PASS] VIP active for ~{diff.total_seconds() / 3600.0:.2f} hours.")

    # Subscription check
    sub_badge, is_active_now = check_subscription(user_updated["subscription_expiry"], script="lat")
    assert is_active_now is True
    print(f"   [PASS] Subscription status now: {sub_badge} (is_active=True).")

    # ==================== 4. ANTI-ABUSE: SECOND CLAIM BLOCKED ====================
    print("\n>>> 4. Testing Anti-Abuse (Repeated Claim Blocked)...")
    can_claim_again = await db.can_user_claim_trial(test_user_id)
    assert can_claim_again is False, "User who claimed trial MUST NOT be eligible again"
    print("   [PASS] can_user_claim_trial returns False after claim.")

    success2, err_msg = await db.activate_user_trial(test_user_id, hours=24)
    assert success2 is False
    assert "allaqachon" in err_msg.lower()
    print("   [PASS] Second claim attempt safely rejected with clear error message.")

    # Keyboards for VIP user no longer show claim_trial button
    main_kb_after = kb.main_dashboard_kb(is_authenticated=True, script="lat", can_claim_trial=False)
    assert "claim_trial" not in [btn.callback_data for row in main_kb_after.inline_keyboard for btn in row]
    print("   [PASS] Trial button cleanly disappeared from main dashboard.")

    # ==================== 5. DRIVER VIP RADAR PRIVILEGES ====================
    print("\n>>> 5. Testing VIP Privileges During Trial...")
    # Initialize driver radar preferences
    await db.update_driver_radar_preferences(test_user_id, is_radar_active=1, direction="both", selected_districts=["asaka"])
    prefs = await db.get_driver_radar_preferences(test_user_id)
    
    # Evaluate with CorridorMatcher
    matcher = CorridorMatcher()
    sample_order = {
        "id": 55,
        "order_type": "PASSENGER",
        "origin": {"id": "asaka", "name": "Asaka", "region_id": "andijon", "district_id": "asaka"},
        "destination": {"id": "toshkent_shahar", "name": "Toshkent", "region_id": "toshkent_shahar"},
        "phone_number": "+998901112233",
        "raw_text": "Toshkentga 1 kishi kerak Asakadan 901112233"
    }
    
    match = matcher.match_driver(sample_order, {**prefs, "is_vip": is_active_now}, enforce_vip=True)
    assert match is not None, "Driver with active trial MUST match VIP orders!"
    assert match["driver_id"] == test_user_id
    assert match["match_type"] == "EXACT"
    print("   [PASS] Driver with active 24h trial received VIP radar lead successfully!")

    print("\n" + "=" * 70)
    print("ALL 24-HOUR VIP TRIAL TESTS PASSED CLEANLY (100% SUCCESS)!")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(run_vip_trial_tests())
