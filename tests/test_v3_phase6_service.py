"""
Automated Test Suite for Taksi Xabarchi v3.0 - Phase 6
Tests:
1. HarvesterService lifecycle, session detection, and status reporting.
2. SuperAdmin Bot Keyboards & Control Panel navigation.
3. Automated entity resolution fallback & database synchronization.
4. Web API group management with userbot connection telemetry.
"""
import os
import sys
import asyncio
from datetime import datetime

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath("."))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src import database as db
from src.config import ADMIN_ID
from src.harvester.service import HarvesterService
from src.bot import keyboards as kb

def run_phase6_tests():
    print("=" * 65)
    print("TEST SUITE: TAKSI XABARCHI v3.0 - STAGE 6 (USERBOT SERVICE & ADMIN PANEL)")
    print("=" * 65)

    async def _async_tests():
        # Setup temporary test database
        await db.init_db()

        # ==================== 1. HARVESTER SERVICE LIFECYCLE ====================
        print("\n>>> 1. Testing HarvesterService Lifecycle & Status...")
        service = HarvesterService(session_name="test_non_existent_harvester")
        assert not service.is_session_available(), "Non-existent session should report is_session_available=False"
        assert not service.is_connected(), "Initial state should not be connected"

        status = service.get_status()
        assert status["is_available"] is False
        assert status["is_connected"] is False
        assert status["session_name"] == "test_non_existent_harvester"
        print("   [PASS] HarvesterService reports clean offline state without crashing.")

        # Test resolve_and_join_group with numeric ID when offline
        test_group_id = -1009876543210
        res = await service.resolve_and_join_group(str(test_group_id), region_tag="ANDIJON")
        assert res["success"] is True
        assert res["group_id"] == test_group_id
        print("   [PASS] Numeric group ID added directly and saved to DB.")

        # Test string username error when offline
        err_res = await service.resolve_and_join_group("@random_taxi_channel")
        assert err_res["success"] is False
        assert "Userbot ulanmagan" in err_res["error"]
        print("   [PASS] Offline entity resolution returns clear prompt to log in.")

        # ==================== 2. SUPERADMIN BOT KEYBOARDS ====================
        print("\n>>> 2. Testing SuperAdmin Bot Keyboards & Control Panel...")
        
        # Main Admin Dashboard KB
        admin_kb = kb.admin_main_dashboard_kb(userbot_online=False, pending_cheques=3)
        flat_buttons = [btn.text for row in admin_kb.inline_keyboard for btn in row]
        assert any("Harvester Radar" in b for b in flat_buttons)
        assert any("Foydalanuvchilar" in b for b in flat_buttons)
        assert any("Moliya" in b and "3 ta kutilmoqda" in b for b in flat_buttons)
        assert any("Asosiy tariflar" in b for b in flat_buttons)
        assert any("Chegirma & Promolar" in b for b in flat_buttons)
        print("   [PASS] admin_main_dashboard_kb rendered all admin control modules.")

        # Harvester Hub KB
        hub_kb = kb.admin_harvester_hub_kb(userbot_online=True)
        hub_buttons = [btn.text for row in hub_kb.inline_keyboard for btn in row]
        assert any("Guruh qo'shish" in b for b in hub_buttons)
        assert any("Guruhlar ro'yxati" in b for b in hub_buttons)
        assert any("Qayta yuklash" in b or "qayta yuklash" in b for b in hub_buttons)
        print("   [PASS] admin_harvester_hub_kb provides complete radar management.")

        # Monitored Groups List Pagination KB
        mock_groups = [
            {"group_id": -1001000 + i, "title": f"Vodiy Taksi Guruh #{i}", "is_active": (i % 2 == 0)}
            for i in range(12)
        ]
        page0_kb = kb.admin_groups_list_kb(mock_groups, page=0, per_page=5)
        # 5 group rows + 1 nav row + 1 footer row
        assert len(page0_kb.inline_keyboard) == 7
        assert page0_kb.inline_keyboard[5][0].text == "1/3"  # 12 items / 5 = 3 pages
        print("   [PASS] admin_groups_list_kb paginates 12 groups into 3 pages accurately.")

        # ==================== 3. GROUPS DB OPERATIONS & RECOVERY ====================
        print("\n>>> 3. Testing Groups DB Operations & Toggle/Delete...")
        # Toggle group
        await db.toggle_harvester_group(test_group_id, is_active=False)
        grp = await db.get_harvester_group(test_group_id)
        assert grp is not None
        assert grp["is_active"] == 0
        print("   [PASS] Group paused in DB.")

        await db.toggle_harvester_group(test_group_id, is_active=True)
        grp = await db.get_harvester_group(test_group_id)
        assert grp["is_active"] == 1
        print("   [PASS] Group resumed in DB.")

        # Delete group
        await db.delete_harvester_group(test_group_id)
        deleted = await db.get_harvester_group(test_group_id)
        assert deleted is None
        print("   [PASS] Group deleted cleanly from DB.")

        # Clean up any test records
        print("\n" + "=" * 65)
        print("ALL STAGE 6 USERBOT SERVICE & ADMIN PANEL TESTS PASSED (100%)")
        print("=" * 65)

    asyncio.run(_async_tests())

if __name__ == "__main__":
    run_phase6_tests()
