import os
import re
import asyncio
import contextlib
from typing import Dict, Any, Optional
from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    PasswordHashInvalidError,
    PhoneNumberInvalidError,
    FloodWaitError
)
from src.config import API_ID, API_HASH, SESSIONS_DIR
from src import database as db
from src.logger import setup_logger

logger = setup_logger("auth_flow")

# In-memory store for active login attempts: user_id -> dict
active_auth_sessions: Dict[int, Dict[str, Any]] = {}

def get_user_session_path(user_id: int) -> str:
    return os.path.join(SESSIONS_DIR, f"user_{user_id}")

def is_user_authenticated(user_id: int) -> bool:
    session_file = f"{get_user_session_path(user_id)}.session"
    return os.path.exists(session_file)

@contextlib.asynccontextmanager
async def user_client_scope(user_id: int, worker_mgr=None):
    """Context manager yielding an active or temporary Telethon TelegramClient for user_id."""
    active_client = worker_mgr.get_user_client(user_id) if worker_mgr else None
    if active_client and active_client.is_connected():
        yield active_client
        return

    if not is_user_authenticated(user_id):
        yield None
        return

    session_path = get_user_session_path(user_id)
    temp_client = TelegramClient(session_path, API_ID, API_HASH)
    try:
        await temp_client.connect()
        if await temp_client.is_user_authorized():
            yield temp_client
        else:
            yield None
    except Exception as e:
        logger.error(f"Error opening temporary client for user {user_id}: {e}")
        yield None
    finally:
        with contextlib.suppress(Exception):
            await temp_client.disconnect()

async def start_phone_login(user_id: int, phone: str) -> Dict[str, Any]:
    """Initiates login with phone number and sends verification code."""
    # Clean phone number
    clean_phone = re.sub(r'[^\d+]', '', phone.strip())
    if not clean_phone.startswith('+'):
        clean_phone = f"+{clean_phone}"
        
    session_path = get_user_session_path(user_id)
    
    # Close any lingering client for this user
    if user_id in active_auth_sessions:
        old_client = active_auth_sessions[user_id].get("client")
        if old_client:
            with contextlib.suppress(Exception):
                await old_client.disconnect()
                
    client = TelegramClient(session_path, API_ID, API_HASH)
    await client.connect()
    
    try:
        sent_code = await client.send_code_request(clean_phone)
        active_auth_sessions[user_id] = {
            "client": client,
            "phone": clean_phone,
            "phone_code_hash": sent_code.phone_code_hash
        }
        logger.info(f"Sent auth code to {clean_phone} for user {user_id}")
        return {"success": True, "message": "Code sent"}
    except PhoneNumberInvalidError:
        await client.disconnect()
        return {"success": False, "error": "Telefon raqami noto'g'ri kiritildi."}
    except FloodWaitError as e:
        await client.disconnect()
        return {"success": False, "error": f"Telegram cheklovi: {e.seconds} soniya kuting."}
    except Exception as e:
        logger.error(f"Error sending auth code for user {user_id}: {e}")
        await client.disconnect()
        return {"success": False, "error": f"Xatolik: {str(e)}"}

async def submit_auth_code(user_id: int, raw_code: str) -> Dict[str, Any]:
    """Submits the verification code."""
    session_data = active_auth_sessions.get(user_id)
    if not session_data:
        return {"success": False, "error": "Sessiya eskirgan. Iltimos, raqamni qaytadan yuboring."}
        
    client: TelegramClient = session_data["client"]
    phone: str = session_data["phone"]
    phone_code_hash: str = session_data["phone_code_hash"]
    
    # Extract only digits from code (e.g. '1 2 3 4 5' -> '12345')
    clean_code = re.sub(r'\D', '', raw_code)
    
    try:
        await client.sign_in(phone=phone, code=clean_code, phone_code_hash=phone_code_hash)
        # Login succeeded without 2FA!
        await db.update_user_phone(user_id, phone)
        await client.disconnect()
        active_auth_sessions.pop(user_id, None)
        logger.info(f"User {user_id} successfully authenticated via phone code.")
        return {"success": True, "needs_2fa": False}
        
    except SessionPasswordNeededError:
        logger.info(f"User {user_id} requires 2FA password.")
        return {"success": True, "needs_2fa": True}
    except PhoneCodeInvalidError:
        return {"success": False, "error": "Kiritilgan kod noto'g'ri. Qaytadan tekshirib kiriting."}
    except PhoneCodeExpiredError:
        return {"success": False, "error": "Kod muddati tugagan. Qaytadan raqam yuboring."}
    except Exception as e:
        logger.error(f"Error verifying code for user {user_id}: {e}")
        return {"success": False, "error": f"Xatolik: {str(e)}"}

async def submit_2fa_password(user_id: int, password: str) -> Dict[str, Any]:
    """Submits the 2FA password."""
    session_data = active_auth_sessions.get(user_id)
    if not session_data:
        return {"success": False, "error": "Sessiya eskirgan. Iltimos, qaytadan boshlang."}
        
    client: TelegramClient = session_data["client"]
    phone: str = session_data["phone"]
    
    try:
        await client.sign_in(password=password)
        await db.update_user_phone(user_id, phone)
        await client.disconnect()
        active_auth_sessions.pop(user_id, None)
        logger.info(f"User {user_id} successfully authenticated via 2FA password.")
        return {"success": True}
    except PasswordHashInvalidError:
        return {"success": False, "error": "2-bosqichli parol noto'g'ri kiritildi."}
    except Exception as e:
        logger.error(f"Error verifying 2FA for user {user_id}: {e}")
        return {"success": False, "error": f"Xatolik: {str(e)}"}

async def cancel_auth_session(user_id: int):
    """Cancels and cleans up any in-progress auth session."""
    session_data = active_auth_sessions.pop(user_id, None)
    if session_data and session_data.get("client"):
        try:
            await session_data["client"].disconnect()
        except Exception:
            pass
