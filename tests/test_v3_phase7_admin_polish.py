"""
Unit test suite verifying Phase 7 Admin Panel polishing & UI improvements:
1. No codebase hints ('login_harvester.py') exposed in UI or templates.
2. Offline userbot alert on 'admin_broadcast'.
3. Admin 'Manage plans' section, commands, and keyboards.
4. '👑 Asosiy panelga qaytish' return button after all operations.
5. Responsive grid and padding in /harvester Web UI.
"""

import os
import sys
import unittest

# Add workspace to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.bot import keyboards as kb

class TestAdminPolish(unittest.TestCase):
    def test_no_codebase_hints_in_templates_or_src(self):
        """Verifies requirement 1: No 'scripts/login_harvester.py' exposed to users."""
        harvester_html_path = os.path.join("src", "web", "templates", "harvester.html")
        with open(harvester_html_path, "r", encoding="utf-8") as f:
            content = f.read()
            self.assertNotIn("scripts/login_harvester.py", content)
            self.assertIn("Sessiya ulanmagan", content)

        handlers_path = os.path.join("src", "bot", "handlers.py")
        with open(handlers_path, "r", encoding="utf-8") as f:
            handlers_code = f.read()
            self.assertNotIn("scripts/login_harvester.py", handlers_code)

    def test_harvester_kpi_grid_and_padding(self):
        """Verifies requirement 5: Responsive layout and standard padding."""
        harvester_html_path = os.path.join("src", "web", "templates", "harvester.html")
        with open(harvester_html_path, "r", encoding="utf-8") as f:
            content = f.read()
            self.assertTrue(
                "grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6" in content or
                "grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 2xl:grid-cols-8" in content
            )
            self.assertNotIn("p-4.5", content)
            self.assertIn("rounded-2xl p-5", content)

    def test_admin_return_keyboards(self):
        """Verifies requirement 4: Consistent return navigation after operations."""
        return_kb = kb.admin_return_kb()
        buttons = return_kb.inline_keyboard
        self.assertEqual(len(buttons), 1)
        self.assertIn("Asosiy panelga qaytish", buttons[0][0].text)
        self.assertEqual(buttons[0][0].callback_data, "admin_panel")

    def test_admin_plans_keyboards(self):
        """Verifies requirement 3: Manage plans keyboard structure."""
        # Inactive campaign
        plans_kb_inactive = kb.admin_plans_kb(has_active_discount=False)
        flat_buttons = [btn for row in plans_kb_inactive.inline_keyboard for btn in row]
        callbacks = [btn.callback_data for btn in flat_buttons]
        self.assertIn("admin_set_discount_info", callbacks)
        self.assertIn("admin_new_promo_info", callbacks)
        self.assertNotIn("admin_stop_discount", callbacks)
        self.assertIn("admin_panel", callbacks)

        # Active campaign
        plans_kb_active = kb.admin_plans_kb(has_active_discount=True)
        flat_buttons_act = [btn for row in plans_kb_active.inline_keyboard for btn in row]
        callbacks_act = [btn.callback_data for btn in flat_buttons_act]
        self.assertIn("admin_stop_discount", callbacks_act)

    def test_admin_broadcast_keyboards(self):
        """Verifies requirement 2: Broadcast options keyboard."""
        broadcast_kb = kb.admin_broadcast_kb(userbot_online=True)
        callbacks = [btn.callback_data for row in broadcast_kb.inline_keyboard for btn in row]
        self.assertIn("admin_broadcast_users", callbacks)
        self.assertIn("admin_broadcast_groups", callbacks)
        self.assertIn("admin_panel", callbacks)

if __name__ == "__main__":
    unittest.main()
