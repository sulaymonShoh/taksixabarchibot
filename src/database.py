import aiosqlite
import json
import contextlib
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple, Union
from src.config import DB_PATH, DEFAULT_TRIAL_DAYS
from src.logger import setup_logger

logger = setup_logger("database")

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # Enable Write-Ahead Logging (WAL) for non-blocking concurrent reads and writes
        await db.execute('PRAGMA journal_mode = WAL;')
        await db.execute('PRAGMA busy_timeout = 5000;')
        await db.execute('PRAGMA synchronous = NORMAL;')

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
                script TEXT DEFAULT 'lat',
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
                base_amount_uzs INTEGER,
                discount_details TEXT,
                promocode TEXT,
                receipt_file_id TEXT,
                status TEXT DEFAULT 'PENDING',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Automatic column migration for existing databases
        async with db.execute("PRAGMA table_info(payment_requests)") as cursor:
            cols = [r[1] for r in await cursor.fetchall()]
            if 'base_amount_uzs' not in cols:
                await db.execute('ALTER TABLE payment_requests ADD COLUMN base_amount_uzs INTEGER')
            if 'discount_details' not in cols:
                await db.execute('ALTER TABLE payment_requests ADD COLUMN discount_details TEXT')
            if 'promocode' not in cols:
                await db.execute('ALTER TABLE payment_requests ADD COLUMN promocode TEXT')

        async with db.execute("PRAGMA table_info(users)") as cursor:
            user_cols = [r[1] for r in await cursor.fetchall()]
            if 'script' not in user_cols:
                await db.execute("ALTER TABLE users ADD COLUMN script TEXT DEFAULT 'lat'")
        
        # Global platform settings
        await db.execute('''
            CREATE TABLE IF NOT EXISTS global_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')

        # Campaign discounts (Timed with duration in days and per-plan rates)
        await db.execute('''
            CREATE TABLE IF NOT EXISTS campaign_discounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                plan_discounts TEXT NOT NULL,
                max_discount_percent INTEGER DEFAULT 0,
                start_time TIMESTAMP NOT NULL,
                end_time TIMESTAMP NOT NULL,
                duration_days INTEGER NOT NULL,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Promocodes (Expiry date, usage limits, plan targeting)
        await db.execute('''
            CREATE TABLE IF NOT EXISTS promocodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                discount_type TEXT NOT NULL,
                discount_value REAL NOT NULL,
                plan_discounts TEXT,
                applicable_plans TEXT DEFAULT 'ALL',
                max_uses INTEGER DEFAULT 1,
                used_count INTEGER DEFAULT 0,
                expires_at TIMESTAMP NOT NULL,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Promocode usages (Ensures 1 use per user)
        await db.execute('''
            CREATE TABLE IF NOT EXISTS promocode_usages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                promocode_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                discount_type TEXT NOT NULL,
                discount_value REAL NOT NULL,
                plan_months INTEGER,
                used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (promocode_id) REFERENCES promocodes(id),
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                UNIQUE(promocode_id, user_id)
            )
        ''')

        # Harvester supergroups monitored by the system
        await db.execute('''
            CREATE TABLE IF NOT EXISTS harvester_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id BIGINT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                username TEXT,
                region_tag TEXT DEFAULT 'ALL',
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_message_at TIMESTAMP,
                total_harvested INTEGER DEFAULT 0
            )
        ''')

        # Harvested orders archive
        await db.execute('''
            CREATE TABLE IF NOT EXISTS harvested_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_group_id BIGINT,
                source_group_title TEXT,
                raw_text TEXT NOT NULL,
                order_type TEXT NOT NULL,
                origin_region TEXT,
                origin_district TEXT,
                dest_region TEXT,
                dest_district TEXT,
                passenger_count INTEGER DEFAULT 1,
                phone_number TEXT,
                telegram_username TEXT,
                message_hash TEXT UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Driver radar preferences (Stage 3)
        await db.execute('''
            CREATE TABLE IF NOT EXISTS driver_radar_preferences (
                user_id BIGINT PRIMARY KEY,
                is_radar_active BOOLEAN DEFAULT 1,
                direction TEXT DEFAULT 'both',
                origin_region TEXT DEFAULT 'andijon',
                dest_region TEXT DEFAULT 'toshkent_shahar',
                selected_districts TEXT DEFAULT '["asaka", "shahrixon", "boston", "andijon_shahar"]',
                allow_passenger BOOLEAN DEFAULT 1,
                allow_cargo BOOLEAN DEFAULT 1,
                sound_alerts BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
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
                await db.execute(
                    'UPDATE users SET full_name = ?, username = ? WHERE user_id = ?',
                    (full_name, username, user_id)
                )
                await db.commit()
                user_dict = dict(row)
                user_dict['full_name'] = full_name
                user_dict['username'] = username
                return user_dict, False
                
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

async def get_user_script(user_id: int) -> str:
    """Returns preferred script ('lat' or 'cyr') for the user."""
    user = await get_user(user_id)
    if user and user.get("script"):
        return user["script"]
    return "lat"

async def set_user_script(user_id: int, script: str) -> bool:
    """Updates preferred script ('lat' or 'cyr') for the user."""
    clean_script = "cyr" if script == "cyr" else "lat"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('UPDATE users SET script = ? WHERE user_id = ?', (clean_script, user_id))
        await db.commit()
    return True

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
def _enrich_payment_row(row_dict: Dict[str, Any]) -> Dict[str, Any]:
    disc_details = row_dict.get('discount_details')
    if disc_details and isinstance(disc_details, str):
        try:
            row_dict['discount_info'] = json.loads(disc_details)
        except Exception:
            row_dict['discount_info'] = None
    elif isinstance(disc_details, dict):
        row_dict['discount_info'] = disc_details
    else:
        row_dict['discount_info'] = None
    return row_dict

async def create_payment_request(
    user_id: int,
    plan_months: int,
    amount_uzs: int,
    receipt_file_id: str,
    base_amount_uzs: Optional[int] = None,
    discount_details: Optional[Union[str, Dict[str, Any]]] = None,
    promocode: Optional[str] = None
) -> int:
    disc_str = json.dumps(discount_details) if isinstance(discount_details, dict) else discount_details
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            '''
            INSERT INTO payment_requests (user_id, plan_months, amount_uzs, base_amount_uzs, discount_details, promocode, receipt_file_id, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING')
            ''',
            (user_id, plan_months, amount_uzs, base_amount_uzs, disc_str, promocode, receipt_file_id)
        )
        await db.commit()
        return cursor.lastrowid

async def get_payment_request(request_id: int) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('SELECT * FROM payment_requests WHERE id = ?', (request_id,)) as cursor:
            row = await cursor.fetchone()
            return _enrich_payment_row(dict(row)) if row else None

async def get_pending_payment_requests() -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('SELECT * FROM payment_requests WHERE status = "PENDING" ORDER BY created_at ASC') as cursor:
            rows = await cursor.fetchall()
            return [_enrich_payment_row(dict(row)) for row in rows]

async def get_all_payment_requests(status: Optional[str] = None) -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if status:
            async with db.execute('SELECT * FROM payment_requests WHERE status = ? ORDER BY created_at DESC', (status,)) as cursor:
                rows = await cursor.fetchall()
        else:
            async with db.execute('SELECT * FROM payment_requests ORDER BY created_at DESC') as cursor:
                rows = await cursor.fetchall()
        return [_enrich_payment_row(dict(row)) for row in rows]

async def update_payment_request_status(request_id: int, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('UPDATE payment_requests SET status = ? WHERE id = ?', (status, request_id))
        await db.commit()

async def get_earnings_stats() -> Dict[str, Any]:
    """Returns aggregated earnings metrics: total, this month, last month, and monthly breakdown."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        # Total lifetime approved revenue & count
        async with db.execute(
            "SELECT COALESCE(SUM(amount_uzs), 0) as total_revenue, COUNT(*) as approved_count FROM payment_requests WHERE status = 'APPROVED'"
        ) as cursor:
            row = await cursor.fetchone()
            total_revenue = row['total_revenue'] if row else 0
            approved_count = row['approved_count'] if row else 0

        # Current month revenue
        async with db.execute(
            """
            SELECT COALESCE(SUM(amount_uzs), 0) as this_month
            FROM payment_requests 
            WHERE status = 'APPROVED' AND strftime('%Y-%m', created_at) = strftime('%Y-%m', 'now')
            """
        ) as cursor:
            row = await cursor.fetchone()
            this_month = row['this_month'] if row else 0

        # Previous month revenue
        async with db.execute(
            """
            SELECT COALESCE(SUM(amount_uzs), 0) as last_month
            FROM payment_requests 
            WHERE status = 'APPROVED' AND strftime('%Y-%m', created_at) = strftime('%Y-%m', 'now', '-1 month')
            """
        ) as cursor:
            row = await cursor.fetchone()
            last_month = row['last_month'] if row else 0

        # Monthly breakdown for past 12 months
        async with db.execute(
            """
            SELECT 
                strftime('%Y-%m', created_at) as month,
                COALESCE(SUM(amount_uzs), 0) as total_amount,
                COUNT(*) as count
            FROM payment_requests
            WHERE status = 'APPROVED'
            GROUP BY strftime('%Y-%m', created_at)
            ORDER BY month DESC
            LIMIT 12
            """
        ) as cursor:
            rows = await cursor.fetchall()
            monthly_breakdown = [dict(r) for r in rows]

        return {
            "total_revenue": total_revenue,
            "approved_count": approved_count,
            "this_month": this_month,
            "last_month": last_month,
            "monthly_breakdown": monthly_breakdown
        }

async def get_payment_history(limit: int = 200) -> List[Dict[str, Any]]:
    """Returns payment history joined with user details."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        query = """
            SELECT 
                p.id,
                p.user_id,
                p.plan_months,
                p.amount_uzs,
                p.base_amount_uzs,
                p.discount_details,
                p.promocode,
                p.receipt_file_id,
                p.status,
                p.created_at,
                COALESCE(u.full_name, 'Noma''lum') as full_name,
                u.username,
                u.phone_number
            FROM payment_requests p
            LEFT JOIN users u ON p.user_id = u.user_id
            ORDER BY p.created_at DESC
            LIMIT ?
        """
        async with db.execute(query, (limit,)) as cursor:
            rows = await cursor.fetchall()
            return [_enrich_payment_row(dict(r)) for r in rows]

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

# ==================== CAMPAIGN DISCOUNTS ====================
async def get_active_campaign_discount() -> Optional[Dict[str, Any]]:
    """Returns currently active campaign discount if within duration and active."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        now_str = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        async with db.execute(
            """
            SELECT * FROM campaign_discounts 
            WHERE is_active = 1 AND ? BETWEEN start_time AND end_time
            ORDER BY id DESC LIMIT 1
            """,
            (now_str,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            data = dict(row)
            try:
                data['plan_discounts'] = json.loads(data['plan_discounts'])
            except Exception:
                data['plan_discounts'] = {}
                
            try:
                end_dt = datetime.strptime(data['end_time'], '%Y-%m-%d %H:%M:%S')
                now_dt = datetime.utcnow()
                remaining_sec = max(0, int((end_dt - now_dt).total_seconds()))
                data['remaining_seconds'] = remaining_sec
                data['remaining_days'] = remaining_sec // 86400
                data['remaining_hours'] = (remaining_sec % 86400) // 3600
                data['remaining_minutes'] = (remaining_sec % 3600) // 60
            except Exception:
                data['remaining_seconds'] = 0
                data['remaining_days'] = 0
                data['remaining_hours'] = 0
                data['remaining_minutes'] = 0
                
            return data

async def set_campaign_discount(title: str, plan_discounts: Dict[Any, int], duration_days: int) -> int:
    """Deactivates previous campaigns and creates a new one with given duration in days."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('UPDATE campaign_discounts SET is_active = 0')
        now = datetime.utcnow()
        end = now + timedelta(days=duration_days)
        start_str = now.strftime('%Y-%m-%d %H:%M:%S')
        end_str = end.strftime('%Y-%m-%d %H:%M:%S')
        norm_discounts = {str(k): int(v) for k, v in plan_discounts.items()}
        max_pct = max(norm_discounts.values()) if norm_discounts else 0
        
        cursor = await db.execute(
            """
            INSERT INTO campaign_discounts (title, plan_discounts, max_discount_percent, start_time, end_time, duration_days, is_active)
            VALUES (?, ?, ?, ?, ?, ?, 1)
            """,
            (title, json.dumps(norm_discounts), max_pct, start_str, end_str, duration_days)
        )
        await db.commit()
        return cursor.lastrowid

async def stop_campaign_discount():
    """Immediately stops any running campaign discount."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('UPDATE campaign_discounts SET is_active = 0')
        await db.commit()

# ==================== PROMOCODES ====================
async def create_promocode(
    code: str,
    discount_type: str,
    discount_value: float,
    duration_days: int,
    max_uses: int = 1,
    applicable_plans: str = 'ALL',
    plan_discounts: Optional[Dict[Any, int]] = None
) -> int:
    """Creates a new promocode with uppercase code, expiry timestamp, and usage limit."""
    clean_code = code.strip().upper()
    now = datetime.utcnow()
    end = now + timedelta(days=duration_days)
    end_str = end.strftime('%Y-%m-%d %H:%M:%S')
    p_disc_str = json.dumps({str(k): int(v) for k, v in plan_discounts.items()}) if plan_discounts else None
    
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO promocodes (code, discount_type, discount_value, plan_discounts, applicable_plans, max_uses, expires_at, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (clean_code, discount_type.upper(), discount_value, p_disc_str, applicable_plans, max_uses, end_str)
        )
        await db.commit()
        return cursor.lastrowid

async def get_promocodes() -> List[Dict[str, Any]]:
    """Returns all promocodes with status badges and usage progress."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('SELECT * FROM promocodes ORDER BY created_at DESC') as cursor:
            rows = await cursor.fetchall()
            result = []
            now = datetime.utcnow()
            for r in rows:
                item = dict(r)
                if item.get('plan_discounts'):
                    with contextlib.suppress(Exception):
                        item['plan_discounts'] = json.loads(item['plan_discounts'])
                        
                try:
                    exp_dt = datetime.strptime(item['expires_at'], '%Y-%m-%d %H:%M:%S')
                    is_expired = now > exp_dt
                    rem_sec = max(0, int((exp_dt - now).total_seconds()))
                    item['remaining_days'] = rem_sec // 86400
                    item['remaining_hours'] = (rem_sec % 86400) // 3600
                except Exception:
                    is_expired = False
                    item['remaining_days'] = 0
                    item['remaining_hours'] = 0
                
                is_limit_reached = (item['max_uses'] > 0 and item['used_count'] >= item['max_uses'])
                item['is_expired'] = is_expired
                item['is_limit_reached'] = is_limit_reached
                
                if not item['is_active']:
                    item['status_badge'] = "PAUSED"
                elif is_expired:
                    item['status_badge'] = "EXPIRED"
                elif is_limit_reached:
                    item['status_badge'] = "LIMIT_REACHED"
                else:
                    item['status_badge'] = "ACTIVE"
                    
                result.append(item)
            return result

async def get_promocode_by_code(code: str) -> Optional[Dict[str, Any]]:
    """Fetches a promocode by case-insensitive code."""
    clean_code = code.strip().upper()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('SELECT * FROM promocodes WHERE UPPER(code) = ?', (clean_code,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            item = dict(row)
            if item.get('plan_discounts'):
                with contextlib.suppress(Exception):
                    item['plan_discounts'] = json.loads(item['plan_discounts'])
            return item

async def toggle_promocode_status(promo_id: int, is_active: bool):
    """Enables or pauses a promocode."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('UPDATE promocodes SET is_active = ? WHERE id = ?', (1 if is_active else 0, promo_id))
        await db.commit()

async def delete_promocode(promo_id: int):
    """Deletes a promocode and its usage records."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('DELETE FROM promocode_usages WHERE promocode_id = ?', (promo_id,))
        await db.execute('DELETE FROM promocodes WHERE id = ?', (promo_id,))
        await db.commit()

async def redeem_promocode(user_id: int, code: str, target_plan: Optional[int] = None) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Validates and redeems a promocode for a user.
    If DAYS type: grants free VIP days immediately and records usage.
    If PERCENT / FIXED type: validates eligibility and returns promo for checkout calculation.
    """
    clean_code = code.strip().upper()
    promo = await get_promocode_by_code(clean_code)
    if not promo:
        return False, "❌ Bunday promokod topilmadi. Kodni tekshirib qaytadan kiriting.", None
        
    if not promo['is_active']:
        return False, "⚠️ Ushbu promokod hozirda to'xtatilgan yoki faol emas.", None
        
    # Expiry verification
    try:
        exp_dt = datetime.strptime(promo['expires_at'], '%Y-%m-%d %H:%M:%S')
        if datetime.utcnow() > exp_dt:
            return False, "❌ Ushbu promokodning amal qilish muddati tugagan.", None
    except Exception:
        pass
        
    # Usage limit verification
    if promo['max_uses'] > 0 and promo['used_count'] >= promo['max_uses']:
        return False, "❌ Ushbu promokoddan foydalanish limiti tugagan (barcha limitlar ishlatib bo'lingan).", None
        
    # Anti-abuse: verify user has not redeemed this promo already
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT id FROM promocode_usages WHERE promocode_id = ? AND user_id = ?',
            (promo['id'], user_id)
        ) as cursor:
            if await cursor.fetchone():
                return False, "⚠️ Siz bu promokoddan avval foydalangansiz!", None
                
    # Plan targeting verification
    applicable = promo.get('applicable_plans', 'ALL')
    if target_plan and applicable != 'ALL':
        allowed = [p.strip() for p in applicable.split(',')]
        if str(target_plan) not in allowed:
            return False, f"⚠️ Ushbu promokod faqat {applicable} oylik tariflar uchun amal qiladi.", None

    # If promo gives direct VIP Days
    if promo['discount_type'] == 'DAYS':
        days = int(promo['discount_value'])
        new_expiry = await update_user_subscription(user_id, days)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                INSERT INTO promocode_usages (promocode_id, user_id, discount_type, discount_value, used_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (promo['id'], user_id, promo['discount_type'], promo['discount_value'])
            )
            await db.execute('UPDATE promocodes SET used_count = used_count + 1 WHERE id = ?', (promo['id'],))
            await db.commit()
            
        return True, f"🎉 Tabriklaymiz! `{clean_code}` promokodi faollashtirildi!\nSizga **+{days} kun bepul VIP obuna** taqdim etildi.\n📅 Yangi amal qilish muddati: `{new_expiry}` gacha.", promo
        
    return True, f"🎟 `{clean_code}` promokodi muvaffaqiyatli qabul qilindi!", promo

async def record_promocode_usage(promocode_id: int, user_id: int, plan_months: int):
    """Records that a user finalized a payment using a PERCENT or FIXED promocode."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT id FROM promocode_usages WHERE promocode_id = ? AND user_id = ?',
            (promocode_id, user_id)
        ) as cursor:
            if await cursor.fetchone():
                return
                
        async with db.execute('SELECT discount_type, discount_value FROM promocodes WHERE id = ?', (promocode_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return
            d_type, d_val = row[0], row[1]
            
        await db.execute(
            """
            INSERT INTO promocode_usages (promocode_id, user_id, discount_type, discount_value, plan_months, used_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (promocode_id, user_id, d_type, d_val, plan_months)
        )
        await db.execute('UPDATE promocodes SET used_count = used_count + 1 WHERE id = ?', (promocode_id,))
        await db.commit()

# ==================== HARVESTER GROUPS & ORDERS DATABASE OPERATIONS ====================

async def add_harvester_group(group_id: int, title: str, username: Optional[str] = None, region_tag: str = 'ALL') -> int:
    """Adds or updates a monitored Telegram group in the harvester registry."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO harvester_groups (group_id, title, username, region_tag, is_active)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(group_id) DO UPDATE SET
                title = excluded.title,
                username = excluded.username,
                region_tag = excluded.region_tag,
                is_active = 1
            """,
            (group_id, title, username, region_tag)
        )
        await db.commit()
        async with db.execute('SELECT id FROM harvester_groups WHERE group_id = ?', (group_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

async def get_harvester_groups(active_only: bool = False) -> List[Dict[str, Any]]:
    """Retrieves list of all monitored harvester groups."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        sql = 'SELECT * FROM harvester_groups'
        if active_only:
            sql += ' WHERE is_active = 1'
        sql += ' ORDER BY id DESC'
        async with db.execute(sql) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def get_harvester_group(group_id: int) -> Optional[Dict[str, Any]]:
    """Retrieves a single harvester group by its Telegram chat/group ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('SELECT * FROM harvester_groups WHERE group_id = ?', (group_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def toggle_harvester_group(group_id: int, is_active: bool) -> bool:
    """Enables or disables listening for a specific harvester group."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('UPDATE harvester_groups SET is_active = ? WHERE group_id = ?', (int(is_active), group_id))
        await db.commit()
        return True

async def update_harvester_group_tag(group_id: int, region_tag: str) -> bool:
    """Updates the region_tag of a monitored harvester group."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('UPDATE harvester_groups SET region_tag = ? WHERE group_id = ?', (region_tag, group_id))
        await db.commit()
        return True

async def delete_harvester_group(group_id: int) -> bool:
    """Removes a harvester group from monitoring."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('DELETE FROM harvester_groups WHERE group_id = ?', (group_id,))
        await db.commit()
        return True

async def save_harvested_order(order_data: Dict[str, Any]) -> Optional[int]:
    """
    Persists a verified passenger/cargo order into the harvested_orders archive.
    Returns the newly inserted order ID, or None if the message hash already exists (duplicate).
    """
    msg_hash = order_data.get("message_hash")
    raw_text = order_data.get("raw_text") or ""
    order_type = order_data.get("order_type") or "PASSENGER"
    origin = order_data.get("origin") or {}
    dest = order_data.get("destination") or {}
    source_group_id = order_data.get("source_group_id")
    source_group_title = order_data.get("source_group_title")

    async with aiosqlite.connect(DB_PATH) as db:
        try:
            cursor = await db.execute(
                """
                INSERT INTO harvested_orders (
                    source_group_id, source_group_title, raw_text, order_type,
                    origin_region, origin_district, dest_region, dest_district,
                    passenger_count, phone_number, telegram_username, message_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_group_id,
                    source_group_title,
                    raw_text,
                    order_type,
                    origin.get("region_id"),
                    origin.get("district_id") or origin.get("id"),
                    dest.get("region_id"),
                    dest.get("district_id") or dest.get("id"),
                    order_data.get("passenger_count", 1),
                    order_data.get("phone_number"),
                    order_data.get("telegram_username"),
                    msg_hash
                )
            )
            order_id = cursor.lastrowid
            
            # Update group stats if group_id is provided
            if source_group_id:
                await db.execute(
                    """
                    UPDATE harvester_groups
                    SET total_harvested = total_harvested + 1,
                        last_message_at = CURRENT_TIMESTAMP
                    WHERE group_id = ?
                    """,
                    (source_group_id,)
                )
            
            await db.commit()
            return order_id
        except aiosqlite.IntegrityError:
            # Duplicate message hash, ignore safely
            return None

async def get_recent_harvested_orders(limit: int = 50, region: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieves recent harvested orders for display in admin dashboard and radar stream."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        sql = 'SELECT * FROM harvested_orders'
        params = []
        if region:
            sql += ' WHERE origin_region = ? OR dest_region = ?'
            params.extend([region, region])
        sql += ' ORDER BY id DESC LIMIT ?'
        params.append(limit)

        async with db.execute(sql, tuple(params)) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def get_harvested_orders_count() -> int:
    """Returns total number of harvested orders stored in DB."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT COUNT(*) FROM harvested_orders') as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

async def get_harvester_stats() -> Dict[str, Any]:
    """Aggregates real-time KPIs for Harvester Web Dashboard."""
    async with aiosqlite.connect(DB_PATH) as db:
        # 1. Total orders
        async with db.execute('SELECT COUNT(*) FROM harvested_orders') as cursor:
            total_orders = (await cursor.fetchone())[0]

        # 2. Today orders
        async with db.execute(
            "SELECT COUNT(*) FROM harvested_orders WHERE created_at >= date('now', 'start of day')"
        ) as cursor:
            today_orders = (await cursor.fetchone())[0]

        # 3. Passenger vs Cargo
        async with db.execute(
            "SELECT COUNT(*) FROM harvested_orders WHERE order_type = 'PASSENGER'"
        ) as cursor:
            passenger_orders = (await cursor.fetchone())[0]

        async with db.execute(
            "SELECT COUNT(*) FROM harvested_orders WHERE order_type = 'CARGO'"
        ) as cursor:
            cargo_orders = (await cursor.fetchone())[0]

        # 4. Total groups & active groups
        async with db.execute('SELECT COUNT(*) FROM harvester_groups') as cursor:
            total_groups = (await cursor.fetchone())[0]

        async with db.execute('SELECT COUNT(*) FROM harvester_groups WHERE is_active = 1') as cursor:
            active_groups = (await cursor.fetchone())[0]

    active_drivers = await get_active_radar_drivers()
    vip_drivers_count = sum(1 for d in active_drivers if d.get("is_vip"))

    return {
        "total_orders": total_orders,
        "today_orders": today_orders,
        "passenger_orders": passenger_orders,
        "cargo_orders": cargo_orders,
        "total_groups": total_groups,
        "active_groups": active_groups,
        "active_radar_drivers": len(active_drivers),
        "vip_radar_drivers": vip_drivers_count
    }

# ==================== DRIVER RADAR PREFERENCES (STAGE 3) ====================

DEFAULT_RADAR_DISTRICTS = ["asaka", "shahrixon", "boston", "andijon_shahar"]

async def get_driver_radar_preferences(user_id: int) -> Dict[str, Any]:
    """
    Gets driver radar preferences. If none exist, initializes default preferences
    (Radar ON, Both directions, Asaka/Shahrixon/Bo'ston/Andijon shahar selected).
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            'SELECT * FROM driver_radar_preferences WHERE user_id = ?', (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                res = dict(row)
                if isinstance(res.get("selected_districts"), str):
                    try:
                        res["selected_districts"] = json.loads(res["selected_districts"])
                    except Exception:
                        res["selected_districts"] = list(DEFAULT_RADAR_DISTRICTS)
                return res

        # Insert defaults
        districts_json = json.dumps(DEFAULT_RADAR_DISTRICTS)
        await db.execute(
            '''
            INSERT OR IGNORE INTO driver_radar_preferences (
                user_id, is_radar_active, direction, origin_region, dest_region,
                selected_districts, allow_passenger, allow_cargo, sound_alerts
            ) VALUES (?, 1, 'both', 'andijon', 'toshkent_shahar', ?, 1, 1, 1)
            ''',
            (user_id, districts_json)
        )
        await db.commit()

        async with db.execute(
            'SELECT * FROM driver_radar_preferences WHERE user_id = ?', (user_id,)
        ) as cursor:
            new_row = await cursor.fetchone()
            if new_row:
                res = dict(new_row)
                res["selected_districts"] = list(DEFAULT_RADAR_DISTRICTS)
                return res
            # Fallback if insert or ignore didn't create
            return {
                "user_id": user_id,
                "is_radar_active": 1,
                "direction": "both",
                "origin_region": "andijon",
                "dest_region": "toshkent_shahar",
                "selected_districts": list(DEFAULT_RADAR_DISTRICTS),
                "allow_passenger": 1,
                "allow_cargo": 1,
                "sound_alerts": 1
            }

async def update_driver_radar_preferences(user_id: int, **kwargs) -> Dict[str, Any]:
    """Updates driver radar preferences and returns the updated dict."""
    # Ensure record exists first
    await get_driver_radar_preferences(user_id)

    if not kwargs:
        return await get_driver_radar_preferences(user_id)

    fields = []
    values = []
    for key, val in kwargs.items():
        if key == "selected_districts" and isinstance(val, (list, set)):
            val = json.dumps(list(val))
        fields.append(f"{key} = ?")
        values.append(val)

    fields.append("updated_at = CURRENT_TIMESTAMP")
    values.append(user_id)

    sql = f"UPDATE driver_radar_preferences SET {', '.join(fields)} WHERE user_id = ?"

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(sql, tuple(values))
        await db.commit()

    return await get_driver_radar_preferences(user_id)

async def toggle_driver_district(user_id: int, district_id: str) -> List[str]:
    """Toggles a district ID in the driver's selected_districts list."""
    prefs = await get_driver_radar_preferences(user_id)
    districts = prefs.get("selected_districts", [])
    if not isinstance(districts, list):
        districts = list(DEFAULT_RADAR_DISTRICTS)

    if district_id in districts:
        districts.remove(district_id)
    else:
        districts.append(district_id)

    await update_driver_radar_preferences(user_id, selected_districts=districts)
    return districts

async def get_active_radar_drivers() -> List[Dict[str, Any]]:
    """
    Returns all active radar drivers joined with their user profile and VIP expiration.
    Evaluates is_vip (True if subscription_expiry > now UTC).
    """
    now = datetime.utcnow()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        sql = '''
            SELECT p.*, u.full_name, u.username, u.phone_number, u.subscription_expiry, u.is_banned, u.script
            FROM driver_radar_preferences p
            JOIN users u ON p.user_id = u.user_id
            WHERE p.is_radar_active = 1 AND (u.is_banned IS NULL OR u.is_banned = 0)
        '''
        async with db.execute(sql) as cursor:
            rows = await cursor.fetchall()
            drivers = []
            for r in rows:
                d = dict(r)
                if isinstance(d.get("selected_districts"), str):
                    try:
                        d["selected_districts"] = json.loads(d["selected_districts"])
                    except Exception:
                        d["selected_districts"] = list(DEFAULT_RADAR_DISTRICTS)

                # Evaluate VIP
                expiry_str = d.get("subscription_expiry")
                is_vip = False
                if expiry_str:
                    try:
                        exp = datetime.strptime(expiry_str, '%Y-%m-%d %H:%M:%S')
                        is_vip = (exp > now)
                    except Exception:
                        is_vip = False
                d["is_vip"] = is_vip
                drivers.append(d)
            return drivers



