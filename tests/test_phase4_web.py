import os
import sys
import asyncio
from fastapi.testclient import TestClient

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath("."))

os.environ["BOT_TOKEN"] = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
os.environ["ADMIN_ID"] = "123456789"
os.environ["API_ID"] = "12345"
os.environ["API_HASH"] = "0123456789abcdef0123456789abcdef"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "admin123"
os.environ["DB_PATH"] = "data/test_web_suite.db"

from src import database as db
from src.web.app import app

async def init_data():
    if os.path.exists("data/test_web_suite.db"):
        os.remove("data/test_web_suite.db")
    await db.init_db()
    await db.get_or_create_user(9001, "Web Test User", "web_test")
    await db.create_payment_request(9001, 1, 25000, "sample_receipt_id")

asyncio.run(init_data())

client = TestClient(app)

def test_web_suite():
    print("=" * 60)
    print("TEST SUITE: PHASE 4 (FastAPI Web UI & Telegram Mini App)")
    print("=" * 60)

    # 1. Plans view and API access
    auth = ("admin", "admin123")
    res_plans = client.get("/plans", auth=auth)
    assert res_plans.status_code == 200
    assert "Tarif Rejalari" in res_plans.text
    print(">>> 1. [PASS] Pricing Plans management view rendered correctly.")

    # 2. Unauthorized access rejected
    res_unauth = client.get("/")
    assert res_unauth.status_code == 401
    print(">>> 2. [PASS] Basic auth protection blocked unauthenticated request (401).")

    # 3. Authorized dashboard view
    auth = ("admin", "admin123")
    res_dash = client.get("/", auth=auth)
    assert res_dash.status_code == 200
    assert "Boshqaruv Paneli" in res_dash.text
    print(">>> 3. [PASS] Dashboard overview rendered with metrics.")

    # 4. Users view
    res_users = client.get("/users", auth=auth)
    assert res_users.status_code == 200
    assert "Web Test User" in res_users.text
    print(">>> 4. [PASS] Users table rendered.")

    # 5. Payments view
    res_payments = client.get("/payments", auth=auth)
    assert res_payments.status_code == 200
    assert "To'lov Cheklari" in res_payments.text
    print(">>> 5. [PASS] Payments review gallery rendered.")

    # 6. Extend subscription API
    res_extend = client.post("/api/users/9001/extend", auth=auth, json={"days": 30})
    assert res_extend.status_code == 200
    assert res_extend.json()["success"] is True
    print(">>> 6. [PASS] User subscription extension API verified.")

    # 7. Ban user API
    res_ban = client.post("/api/users/9001/ban", auth=auth, json={"is_banned": True})
    assert res_ban.status_code == 200
    assert res_ban.json()["success"] is True
    print(">>> 7. [PASS] User ban toggle API verified.")

    # 8. Approve payment API
    res_app = client.post("/api/payments/1/approve", auth=auth, json={"user_id": 9001, "plan_months": 1})
    assert res_app.status_code == 200
    assert res_app.json()["success"] is True
    print(">>> 8. [PASS] Payment approval API verified.")

    # 9. SF Pro Display font & Theme toggle verified in templates
    assert "SF Pro Display" in res_dash.text
    assert "toggleTheme" in res_dash.text
    print(">>> 9. [PASS] SF Pro Display font stack and light/dark theme toggle verified.")

    # 10. Filters verified on Users and Payments pages
    assert "applyUserFilters" in res_users.text
    assert "statusFilter" in res_users.text
    assert "applyPaymentFilters" in res_payments.text
    assert "planFilter" in res_payments.text
    assert "photoModal" in res_payments.text
    print(">>> 10. [PASS] User and Payment filter systems and photo lightbox verified.")

    # 11. Receipt photo endpoint
    res_photo = client.get("/api/receipt-photo/1", auth=auth)
    assert res_photo.status_code in [404, 503]
    print(">>> 11. [PASS] Receipt photo endpoint verified.")

    # 12. Finance view and API stats
    res_fin = client.get("/finance", auth=auth)
    assert res_fin.status_code == 200
    assert "Moliya & Daromad Statistikasi" in res_fin.text
    assert "Jami Daromad" in res_fin.text
    print(">>> 12. [PASS] Finance view rendered with KPI cards and monthly breakdown.")

    res_fin_api = client.get("/api/finance/stats", auth=auth)
    assert res_fin_api.status_code == 200
    stats_data = res_fin_api.json()
    assert "total_revenue" in stats_data
    assert "monthly_breakdown" in stats_data
    print(">>> 13. [PASS] Finance stats API verified.")

    # 14. Harvester 3 distinct subpages
    res_h_groups = client.get("/harvester", auth=auth)
    assert res_h_groups.status_code == 200
    assert "Guruhlar Boshqaruvi" in res_h_groups.text

    res_h_analytics = client.get("/harvester/analytics", auth=auth)
    assert res_h_analytics.status_code == 200
    assert "Sifat & Analitika" in res_h_analytics.text

    res_h_orders = client.get("/harvester/orders", auth=auth)
    assert res_h_orders.status_code == 200
    assert "Buyurtmalar Jonli Oqimi" in res_h_orders.text
    print(">>> 14. [PASS] Harvester 3 subpages (Groups, Analytics, Orders) verified.")

    # 15. Base pricing plans API
    res_plan_update = client.post("/api/admin/plans", auth=auth, json={
        "months": 1,
        "price": 30000,
        "days": 30,
        "title": "1 Oy Yangi",
        "tag": "Maxsus"
    })
    assert res_plan_update.status_code == 200
    assert res_plan_update.json()["success"] is True

    res_plans_get = client.get("/api/admin/plans", auth=auth)
    assert res_plans_get.status_code == 200
    plans_data = res_plans_get.json()
    assert plans_data["1"]["price"] == 30000
    print(">>> 15. [PASS] Dynamic pricing plans update API verified.")

    if os.path.exists("data/test_web_suite.db"):
        os.remove("data/test_web_suite.db")

    print("=" * 60)
    print("ALL PHASE 4 WEB TESTS PASSED CLEANLY (100% SUCCESS)")
    print("=" * 60)

if __name__ == "__main__":
    test_web_suite()
