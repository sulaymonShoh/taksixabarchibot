import aiosqlite
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from src.config import DB_PATH, DEFAULT_TRIAL_DAYS
from src.logger import setup_logger

logger = setup_logger("database")

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # Users table (Identity, Subscription, Trial)
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                full_name TEXT,
                username TEXT,
                phone_number TEXT,
                subscription_expiry TIMESTAMP,
                is_lifetime_discount BOOLEAN DEFAULT 1,
                is_banned BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # User settings table
        await db.execute('''
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                is_running BOOLEAN DEFAULT 0,
                source_chat_id INTEGER,
                source_chat_title TEXT,
                drop_author BOOLEAN DEFAULT 0,
                cycle_min INTEGER DEFAULT 60,
                cycle_max INTEGER DEFAULT 90,
                jitter_min REAL DEFAULT 1.5,
                jitter_max REAL DEFAULT 2.0,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        
        # User target groups
        await db.execute('''
            CREATE TABLE IF NOT EXISTS user_target_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                chat_id INTEGER,
                title TEXT,
                username TEXT,
                is_active BOOLEAN DEFAULT 1,
                status TEXT DEFAULT 'Healthy',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, chat_id)
            )
        ''')
        
        # Payment requests (1-Tap Cheque Approval)
        await db.execute('''
            CREATE TABLE IF NOT EXISTS payment_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                plan_months INTEGER,
                amount_uzs INTEGER,
                receipt_file_id TEXT,
                status TEXT DEFAULT 'PENDING',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Global platform settings
        await db.execute('''
            CREATE TABLE IF NOT EXISTS global_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        
        await db.commit()
        logger.info("Multi-tenant database initialized successfully.")

# ==================== USER MANAGEMENT ====================
async def get_or_create_user(user_id: int, full_name: str, username: Optional[str] = None) -> Tuple[Dict[str, Any], bool]:
    """Gets existing user or creates a new one with a 3-day free VIP trial."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('SELECT * FROM users WHERE user_id = ?', (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                # Update latest name/username if changed
                await db.execute(
                    'UPDATE users SET full_name = ?, username = ? WHERE user_id = ?',
                    (full_name, username, user_id)
                )
                await db.commit()
                return dict(row), False
                
        # Brand new user -> Grant 3-day free trial!
        expiry = datetime.utcnow() + timedelta(days=DEFAULT_TRIAL_DAYS)
        expiry_str = expiry.strftime('%Y-%m-%d %H:%M:%S')
        
        await db.execute(
            '''
            INSERT INTO users (user_id, full_name, username, subscription_expiry, is_lifetime_discount)
            VALUES (?, ?, ?, ?, 1)
            ''',
            (user_id, full_name, username, expiry_str)
        )
        
        # Initialize default user settings
        await db.execute(
            '''
            INSERT OR IGNORE INTO user_settings (user_id, is_running, cycle_min, cycle_max, jitter_min, jitter_max)
            VALUES (?, 0, 60, 90, 1.5, 2.0)
            ''',
            (user_id,)
        )
        await db.commit()
        
        async with db.execute('SELECT * FROM users WHERE user_id = ?', (user_id,)) as cursor:
            new_row = await cursor.fetchone()
            return dict(new_row), True

async def get_user(user_id: int) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('SELECT * FROM users WHERE user_id = ?', (user_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def get_all_users() -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('SELECT * FROM users ORDER BY created_at DESC') as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def update_user_phone(user_id: int, phone_number: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('UPDATE users SET phone_number = ? WHERE user_id = ?', (phone_number, user_id))
        await db.commit()

async def update_user_subscription(user_id: int, days_to_add: int) -> str:
    """Adds days to subscription. If currently active, extends from current expiry; otherwise from now."""
    user = await get_user(user_id)
    if not user:
        return ""
        
    now = datetime.utcnow()
    current_expiry_str = user.get('subscription_expiry')
    
    start_date = now
    if current_expiry_str:
        try:
            current_expiry = datetime.strptime(current_expiry_str, '%Y-%m-%d %H:%M:%S')
            if current_expiry > now:
                start_date = current_expiry
        except Exception:
            start_date = now
            
    new_expiry = start_date + timedelta(days=days_to_add)
    new_expiry_str = new_expiry.strftime('%Y-%m-%d %H:%M:%S')
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('UPDATE users SET subscription_expiry = ? WHERE user_id = ?', (new_expiry_str, user_id))
        await db.commit()
        
    return new_expiry_str

async def ban_user(user_id: int, is_banned: bool):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('UPDATE users SET is_banned = ? WHERE user_id = ?', (1 if is_banned else 0, user_id))
        await db.commit()

# ==================== USER SETTINGS ====================
async def get_user_settings(user_id: int) -> Dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('SELECT * FROM user_settings WHERE user_id = ?', (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
                
    # Return default settings if not exists
    return {
        "user_id": user_id,
        "is_running": False,
        "source_chat_id": None,
        "source_chat_title": "O'rnatilmagan",
        "drop_author": False,
        "cycle_min": 60,
        "cycle_max": 90,
        "jitter_min": 1.5,
        "jitter_max": 2.0
    }

async def set_user_setting(user_id: int, key: str, value: Any):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f'UPDATE user_settings SET {key} = ? WHERE user_id = ?', (value, user_id))
        await db.commit()

# ==================== USER TARGET GROUPS ====================
async def add_or_update_user_group(user_id: int, chat_id: int, title: str, username: Optional[str] = None, is_active: bool = True):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            '''
            INSERT INTO user_target_groups (user_id, chat_id, title, username, is_active, status)
            VALUES (?, ?, ?, ?, ?, 'Healthy')
            ON CONFLICT(user_id, chat_id) DO UPDATE SET
                title = excluded.title,
                username = excluded.username
            ''',
            (user_id, chat_id, title, username, is_active)
        )
        await db.commit()

async def get_user_groups(user_id: int) -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('SELECT * FROM user_target_groups WHERE user_id = ?', (user_id,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def get_user_active_groups(user_id: int) -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('SELECT * FROM user_target_groups WHERE user_id = ? AND is_active = 1', (user_id,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def set_all_user_groups_active(user_id: int, is_active: bool):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('UPDATE user_target_groups SET is_active = ? WHERE user_id = ?', (1 if is_active else 0, user_id))
        await db.commit()

async def update_user_group_status(user_id: int, chat_id: int, status: str, is_active: bool = None):
    async with aiosqlite.connect(DB_PATH) as db:
        if is_active is not None:
            await db.execute(
                'UPDATE user_target_groups SET status = ?, is_active = ? WHERE user_id = ? AND chat_id = ?',
                (status, is_active, user_id, chat_id)
            )
        else:
            await db.execute(
                'UPDATE user_target_groups SET status = ? WHERE user_id = ? AND chat_id = ?',
                (status, user_id, chat_id)
            )
        await db.commit()

async def delete_user_group(user_id: int, chat_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('DELETE FROM user_target_groups WHERE user_id = ? AND chat_id = ?', (user_id, chat_id))
        await db.commit()

# ==================== PAYMENT REQUESTS (1-TAP CHEQUE APPROVAL) ====================
async def create_payment_request(user_id: int, plan_months: int, amount_uzs: int, receipt_file_id: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            '''
            INSERT INTO payment_requests (user_id, plan_months, amount_uzs, receipt_file_id, status)
            VALUES (?, ?, ?, ?, 'PENDING')
            ''',
            (user_id, plan_months, amount_uzs, receipt_file_id)
        )
        await db.commit()
        return cursor.lastrowid

async def get_payment_request(request_id: int) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('SELECT * FROM payment_requests WHERE id = ?', (request_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def get_pending_payment_requests() -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('SELECT * FROM payment_requests WHERE status = "PENDING" ORDER BY created_at ASC') as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def update_payment_request_status(request_id: int, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('UPDATE payment_requests SET status = ? WHERE id = ?', (status, request_id))
        await db.commit()

# ==================== GLOBAL SETTINGS ====================
async def get_global_setting(key: str, default: Any = None) -> Any:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT value FROM global_settings WHERE key = ?', (key,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return json.loads(row[0])
            return default

async def set_global_setting(key: str, value: Any):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            'INSERT OR REPLACE INTO global_settings (key, value) VALUES (?, ?)',
            (key, json.dumps(value))
        )
        await db.commit()
