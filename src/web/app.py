import os
import asyncio
import secrets
import contextlib
from datetime import datetime
from typing import Optional, Dict, Any

from fastapi import FastAPI, Depends, HTTPException, status, Request, Body
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from src import database as db
from src.config import ADMIN_USERNAME, ADMIN_PASSWORD, MEDIA_DIR
from src.logger import setup_logger

logger = setup_logger("web_app")

app = FastAPI(title="Taksi Xabarchi Admin Panel", docs_url=None, redoc_url=None)
security = HTTPBasic()
templates = Jinja2Templates(directory="src/web/templates")

def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    is_user_ok = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    is_pass_ok = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    if not (is_user_ok and is_pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Noto'g'ri login yoki parol",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# ==================== DATA MODELS ====================
class ExtendSubRequest(BaseModel):
    days: int

class BanUserRequest(BaseModel):
    is_banned: bool

class ApprovePaymentRequest(BaseModel):
    user_id: int
    plan_months: int

class BroadcastRequest(BaseModel):
    text: str

# ==================== HELPER FUNCTIONS ====================
def enrich_user_data(u: Dict[str, Any]) -> Dict[str, Any]:
    u_dict = dict(u)
    exp = u_dict.get('subscription_expiry')
    is_active = False
    if exp:
        try:
            if datetime.strptime(exp, '%Y-%m-%d %H:%M:%S') > datetime.utcnow():
                is_active = True
        except Exception:
            pass
    u_dict['is_active_sub'] = is_active
    return u_dict

# ==================== WEB UI ROUTES ====================
@app.get("/", response_class=HTMLResponse)
async def dashboard_view(request: Request, username: str = Depends(verify_credentials)):
    users = await db.get_all_users()
    pending = await db.get_pending_payment_requests()
    
    active_subs = 0
    now = datetime.utcnow()
    for u in users:
        exp = u.get('subscription_expiry')
        if exp:
            try:
                if datetime.strptime(exp, '%Y-%m-%d %H:%M:%S') > now:
                    active_subs += 1
            except Exception:
                pass
                
    worker_mgr = getattr(request.app.state, 'worker_manager', None)
    running_workers = len(worker_mgr.active_workers) if worker_mgr else 0
    earnings = await db.get_earnings_stats()

    stats = {
        "total_users": len(users),
        "active_subscribers": active_subs,
        "running_workers": running_workers,
        "pending_payments": len(pending),
        "total_revenue": earnings.get("total_revenue", 0),
        "this_month_revenue": earnings.get("this_month", 0)
    }
    
    enriched_users = [enrich_user_data(u) for u in users[:10]]

    return templates.TemplateResponse(request=request, name="dashboard.html", context={
        "active_page": "dashboard",
        "stats": stats,
        "earnings": earnings,
        "recent_users": enriched_users,
        "recent_payments": pending[:5],
        "pending_count": len(pending)
    })

@app.get("/users", response_class=HTMLResponse)
async def users_view(request: Request, username: str = Depends(verify_credentials)):
    users = await db.get_all_users()
    pending = await db.get_pending_payment_requests()
    enriched_users = [enrich_user_data(u) for u in users]
    
    return templates.TemplateResponse(request=request, name="users.html", context={
        "active_page": "users",
        "users": enriched_users,
        "pending_count": len(pending)
    })

@app.get("/payments", response_class=HTMLResponse)
async def payments_view(request: Request, username: str = Depends(verify_credentials)):
    all_payments = await db.get_all_payment_requests()
    pending = [p for p in all_payments if p.get('status') == 'PENDING']
    
    return templates.TemplateResponse(request=request, name="payments.html", context={
        "active_page": "payments",
        "payments": all_payments,
        "pending_payments": pending,
        "pending_count": len(pending)
    })

@app.get("/api/receipt-photo/{request_id}")
async def get_receipt_photo(request_id: int, request: Request, username: str = Depends(verify_credentials)):
    req = await db.get_payment_request(request_id)
    if not req or not req.get("receipt_file_id"):
        raise HTTPException(status_code=404, detail="Chek rasmi topilmadi")
        
    file_id = req["receipt_file_id"]
    receipts_dir = os.path.join(MEDIA_DIR, "receipts")
    os.makedirs(receipts_dir, exist_ok=True)
    local_path = os.path.join(receipts_dir, f"receipt_{request_id}_{file_id[:16]}.jpg")
    
    if os.path.exists(local_path):
        return FileResponse(local_path, media_type="image/jpeg")
        
    bot = getattr(request.app.state, 'bot', None)
    if not bot:
        raise HTTPException(status_code=503, detail="Telegram Bot faol emas")
        
    try:
        tg_file = await bot.get_file(file_id)
        if tg_file and tg_file.file_path:
            await bot.download_file(tg_file.file_path, destination=local_path)
            return FileResponse(local_path, media_type="image/jpeg")
    except Exception as e:
        logger.error(f"Error downloading receipt photo for request #{request_id}: {e}")
        
    raise HTTPException(status_code=404, detail="Rasmni yuklab bo'lmadi")

@app.get("/broadcast", response_class=HTMLResponse)
async def broadcast_view(request: Request, username: str = Depends(verify_credentials)):
    pending = await db.get_pending_payment_requests()
    return templates.TemplateResponse(request=request, name="broadcast.html", context={
        "active_page": "broadcast",
        "pending_count": len(pending)
    })

@app.get("/finance", response_class=HTMLResponse)
async def finance_view(request: Request, username: str = Depends(verify_credentials)):
    earnings = await db.get_earnings_stats()
    history = await db.get_payment_history(limit=250)
    pending = await db.get_pending_payment_requests()
    
    # Max month amount for visual bar scaling
    max_month_amount = max([m['total_amount'] for m in earnings['monthly_breakdown']] or [1])
    if max_month_amount <= 0:
        max_month_amount = 1
        
    return templates.TemplateResponse(request=request, name="finance.html", context={
        "active_page": "finance",
        "earnings": earnings,
        "history": history,
        "max_month_amount": max_month_amount,
        "pending_count": len(pending)
    })

@app.get("/api/finance/stats")
async def api_finance_stats(username: str = Depends(verify_credentials)):
    return JSONResponse(await db.get_earnings_stats())

@app.get("/miniapp", response_class=HTMLResponse)
async def miniapp_view(request: Request):
    """Public Mini App endpoint accessible inside Telegram Web App."""
    return templates.TemplateResponse(request=request, name="miniapp.html", context={})

# ==================== ADMIN ACTION APIS ====================
@app.post("/api/users/{user_id}/extend")
async def api_extend_sub(user_id: int, req: ExtendSubRequest, username: str = Depends(verify_credentials)):
    new_expiry = await db.update_user_subscription(user_id, req.days)
    if not new_expiry:
        return JSONResponse({"success": False, "error": "Foydalanuvchi topilmadi"})
        
    bot = getattr(app.state, 'bot', None)
    if bot:
        with contextlib.suppress(Exception):
            await bot.send_message(
                chat_id=user_id,
                text=f"⭐️ **Obunangiz uzaytirildi!**\n\nAdministrator hisobingizga +{req.days} kun qo'shdi.\n📅 Yangi muddat: `{new_expiry}` gacha.",
                parse_mode="Markdown"
            )
            
    return JSONResponse({"success": True, "new_expiry": new_expiry})

@app.post("/api/users/{user_id}/ban")
async def api_ban_user(user_id: int, req: BanUserRequest, username: str = Depends(verify_credentials)):
    await db.ban_user(user_id, req.is_banned)
    worker_mgr = getattr(app.state, 'worker_manager', None)
    if req.is_banned and worker_mgr:
        await worker_mgr.stop_user_worker(user_id)
        
    return JSONResponse({"success": True})

@app.post("/api/payments/{request_id}/approve")
async def api_approve_payment(request_id: int, req: ApprovePaymentRequest, username: str = Depends(verify_credentials)):
    plan_days = req.plan_months * 30
    if req.plan_months == 12:
        plan_days = 390
        
    await db.update_payment_request_status(request_id, "APPROVED")
    new_expiry = await db.update_user_subscription(req.user_id, plan_days)
    
    bot = getattr(app.state, 'bot', None)
    if bot:
        with contextlib.suppress(Exception):
            await bot.send_message(
                chat_id=req.user_id,
                text=f"🎉 **Tabriklaymiz! To'lovingiz tasdiqlandi!**\n\n📦 Tarif: {req.plan_months} Oy\n📅 Yangi amal qilish muddati: `{new_expiry}` gacha.",
                parse_mode="Markdown"
            )
            
    return JSONResponse({"success": True, "new_expiry": new_expiry})

@app.post("/api/payments/{request_id}/reject")
async def api_reject_payment(request_id: int, username: str = Depends(verify_credentials)):
    req_data = await db.get_payment_request(request_id)
    await db.update_payment_request_status(request_id, "REJECTED")
    
    if req_data:
        bot = getattr(app.state, 'bot', None)
        if bot:
            with contextlib.suppress(Exception):
                await bot.send_message(
                    chat_id=req_data['user_id'],
                    text="❌ **Yuborilgan to'lov chekingiz tasdiqlanmadi.** Iltimos, ma'lumotlarni tekshirib qaytadan yuboring yoki admin bilan bog'laning.",
                    parse_mode="Markdown"
                )
                
    return JSONResponse({"success": True})

@app.post("/api/broadcast")
async def api_broadcast(req: BroadcastRequest, username: str = Depends(verify_credentials)):
    users = await db.get_all_users()
    bot = getattr(app.state, 'bot', None)
    if not bot:
        return JSONResponse({"success": False, "error": "Bot faol emas"})
        
    async def run_broadcast():
        for u in users:
            try:
                await bot.send_message(chat_id=u['user_id'], text=req.text, parse_mode="Markdown")
                await asyncio.sleep(0.05)
            except Exception as e:
                logger.error(f"Failed broadcast to {u['user_id']}: {e}")
                
    asyncio.create_task(run_broadcast())
    return JSONResponse({"success": True, "total_recipients": len(users)})
