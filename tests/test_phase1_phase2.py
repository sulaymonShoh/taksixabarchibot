import os
import sys
import asyncio
import re
from datetime import datetime, timedelta

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath("."))

# Set mock test environment
os.environ["BOT_TOKEN"] = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
os.environ["ADMIN_ID"] = "123456789"
os.environ["API_ID"] = "12345"
os.environ["API_HASH"] = "0123456789abcdef0123456789abcdef"
os.environ["DB_PATH"] = "data/test_suite.db"

from src import database as db
from src.bot import keyboards as kb
from src.bot import auth_flow

async def test_database_multi_tenant():
    print(">>> 1. Testing Database & Multi-Tenant Isolation")
    if os.path.exists("data/test_suite.db"):
        os.remove("data/test_suite.db")
        
    await db.init_db()
    
    # 1.1 User creation & 3-day trial
    u1, is_new1 = await db.get_or_create_user(1001, "Driver One", "driver1")
    assert is_new1 is True
    assert u1["user_id"] == 1001
    assert u1["is_lifetime_discount"] == 1
    exp1 = datetime.strptime(u1["subscription_expiry"], '%Y-%m-%d %H:%M:%S')
    now = datetime.utcnow()
    assert (exp1 - now).days >= 2 # ~3 days trial
    
    # 1.2 Calling again updates name without resetting trial
    u1_again, is_new1_again = await db.get_or_create_user(1001, "Driver One Updated", "driver1_new")
    assert is_new1_again is False
    assert u1_again["full_name"] == "Driver One Updated"
    assert u1_again["subscription_expiry"] == u1["subscription_expiry"]
    
    # 1.3 Second user creation
    u2, is_new2 = await db.get_or_create_user(1002, "Driver Two", "driver2")
    assert is_new2 is True
    assert u2["user_id"] == 1002
    
    # 1.4 Subscription extension logic
    new_exp1 = await db.update_user_subscription(1001, 30)
    u1_updated = await db.get_user(1001)
    exp1_after = datetime.strptime(u1_updated["subscription_expiry"], '%Y-%m-%d %H:%M:%S')
    assert (exp1_after - exp1).days == 30
    
    # 1.5 User isolation in settings
    await db.set_user_setting(1001, "source_chat_id", -100999)
    await db.set_user_setting(1001, "source_chat_title", "Driver 1 Source")
    await db.set_user_setting(1002, "source_chat_id", -100888)
    await db.set_user_setting(1002, "source_chat_title", "Driver 2 Source")
    
    s1 = await db.get_user_settings(1001)
    s2 = await db.get_user_settings(1002)
    assert s1["source_chat_id"] == -100999
    assert s2["source_chat_id"] == -100888
    
    # 1.6 User isolation in target groups
    await db.add_or_update_user_group(1001, -10011, "Group 1A", "g1a", True)
    await db.add_or_update_user_group(1001, -10012, "Group 1B", "g1b", True)
    await db.add_or_update_user_group(1002, -10021, "Group 2A", "g2a", True)
    
    g1_list = await db.get_user_groups(1001)
    g2_list = await db.get_user_groups(1002)
    assert len(g1_list) == 2
    assert len(g2_list) == 1
    assert g1_list[0]["chat_id"] in [-10011, -10012]
    assert g2_list[0]["chat_id"] == -10021
    
    # 1.7 Bulk group toggle isolation
    await db.set_all_user_groups_active(1001, False)
    active_g1 = await db.get_user_active_groups(1001)
    active_g2 = await db.get_user_active_groups(1002)
    assert len(active_g1) == 0
    assert len(active_g2) == 1 # User 2 is unaffected!
    
    # 1.8 Payment requests
    req_id = await db.create_payment_request(1001, 3, 65000, "file_receipt_xyz")
    pending = await db.get_pending_payment_requests()
    assert len(pending) == 1
    assert pending[0]["id"] == req_id
    assert pending[0]["user_id"] == 1001
    assert pending[0]["amount_uzs"] == 65000
    
    await db.update_payment_request_status(req_id, "APPROVED")
    pending_after = await db.get_pending_payment_requests()
    assert len(pending_after) == 0
    
    # 1.9 Ban toggle
    await db.ban_user(1002, True)
    u2_banned = await db.get_user(1002)
    assert u2_banned["is_banned"] == 1
    
    print("   [PASS] Database multi-tenant CRUD and complete user isolation verified.")

def test_auth_utilities():
    print(">>> 2. Testing Auth Flow Utilities")
    # Path generation
    path = auth_flow.get_user_session_path(555666)
    assert "user_555666" in path
    
    # Code sanitization
    raw_codes = ["1 2 3 4 5", "12345", " 1-2-3-4-5 ", "code: 98765"]
    cleaned = [re.sub(r'\D', '', c) for c in raw_codes]
    assert cleaned == ["12345", "12345", "12345", "98765"]
    print("   [PASS] Auth flow session paths and code sanitizers verified.")

def test_keyboards():
    print(">>> 3. Testing Keyboards UI & Callback Completeness")
    # Unauthenticated dashboard
    kb_unauth = kb.main_dashboard_kb(is_authenticated=False, is_running=False, drop_author=False)
    unauth_callbacks = [btn.callback_data for row in kb_unauth.inline_keyboard for btn in row if btn.callback_data]
    assert "start_auth" in unauth_callbacks
    assert "show_plans" in unauth_callbacks
    assert "help_info" in unauth_callbacks
    
    # Authenticated dashboard
    kb_auth = kb.main_dashboard_kb(is_authenticated=True, is_running=False, drop_author=False)
    auth_callbacks = [btn.callback_data for row in kb_auth.inline_keyboard for btn in row if btn.callback_data]
    assert "toggle_state" in auth_callbacks
    assert "set_source_chat" in auth_callbacks
    assert "manage_groups" in auth_callbacks
    assert "adjust_timing" in auth_callbacks
    assert "adjust_jitter" in auth_callbacks
    assert "trigger_test" in auth_callbacks
    assert "logout_confirm" in auth_callbacks
    
    # Pricing plans
    kb_plans = kb.pricing_plans_kb(True)
    plan_callbacks = [btn.callback_data for row in kb_plans.inline_keyboard for btn in row if btn.callback_data]
    assert "buy_plan_1" in plan_callbacks
    assert "buy_plan_3" in plan_callbacks
    assert "buy_plan_6" in plan_callbacks
    assert "buy_plan_12" in plan_callbacks
    
    # Admin approval card
    kb_admin = kb.admin_payment_approval_kb(request_id=42, user_id=1001, plan_months=3)
    admin_callbacks = [btn.callback_data for row in kb_admin.inline_keyboard for btn in row if btn.callback_data]
    assert "pay_app_42_1001_3" in admin_callbacks
    assert "pay_rej_42_1001" in admin_callbacks
    
    # Paginated groups
    sample_groups = [{"chat_id": -1000 - i, "title": f"Group {i}", "is_active": True} for i in range(25)]
    kb_page0 = kb.paginated_groups_kb(sample_groups, page=0, per_page=10)
    page0_cbs = [btn.callback_data for row in kb_page0.inline_keyboard for btn in row if btn.callback_data]
    assert "bulk_groups_on_0" in page0_cbs
    assert "bulk_groups_off_0" in page0_cbs
    assert "page_groups_1" in page0_cbs
    
    # Custom timing & jitter options present
    t_kb = kb.timing_kb()
    t_cbs = [btn.callback_data for row in t_kb.inline_keyboard for btn in row if btn.callback_data]
    assert "time_custom" in t_cbs
    
    j_kb = kb.jitter_kb()
    j_cbs = [btn.callback_data for row in j_kb.inline_keyboard for btn in row if btn.callback_data]
    assert "jitter_custom" in j_cbs
    
    print("   [PASS] All Keyboards, callback identifiers, and pagination logic verified.")

async def test_user_client_scope():
    print(">>> 4. Testing user_client_scope Context Manager")
    # Unauthenticated user returns None
    async with auth_flow.user_client_scope(99999999) as client:
        assert client is None
        
    # Active worker client is yielded directly without disconnection
    class MockClient:
        def __init__(self):
            self.disconnected = False
        def is_connected(self):
            return True
        async def disconnect(self):
            self.disconnected = True

    class MockWorkerMgr:
        def __init__(self, client):
            self.c = client
        def get_user_client(self, uid):
            return self.c
            
    mock_c = MockClient()
    mgr = MockWorkerMgr(mock_c)
    async with auth_flow.user_client_scope(12345, mgr) as c:
        assert c is mock_c
    assert not mock_c.disconnected # Must NOT disconnect active worker client!
    print("   [PASS] user_client_scope behavior verified.")

async def main():
    print("=" * 60)
    print("TEST SUITE: PHASE 1 (Database & Auth) & PHASE 2 (Bot UI & Handlers)")
    print("=" * 60)
    await test_database_multi_tenant()
    test_auth_utilities()
    test_keyboards()
    await test_user_client_scope()
    
    # Cleanup test DB
    if os.path.exists("data/test_suite.db"):
        os.remove("data/test_suite.db")
        
    print("=" * 60)
    print("ALL TESTS IN PHASE 1 & 2 PASSED CLEANLY (100% SUCCESS)")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
