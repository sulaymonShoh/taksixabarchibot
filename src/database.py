import aiosqlite
import json
from typing import Dict, Any, List, Optional
from src.config import DB_PATH
from src.logger import setup_logger

logger = setup_logger("database")

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS target_groups (
                chat_id INTEGER PRIMARY KEY,
                title TEXT,
                username TEXT,
                is_active BOOLEAN DEFAULT 1,
                status TEXT DEFAULT 'Healthy',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS message_history (
                chat_id INTEGER PRIMARY KEY,
                message_id INTEGER,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.commit()
        logger.info("Database initialized successfully.")

async def get_setting(key: str, default: Any = None) -> Any:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT value FROM settings WHERE key = ?', (key,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return json.loads(row[0])
            return default

async def set_setting(key: str, value: Any):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            'INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)',
            (key, json.dumps(value))
        )
        await db.commit()

async def get_all_settings() -> Dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT key, value FROM settings') as cursor:
            rows = await cursor.fetchall()
            return {row[0]: json.loads(row[1]) for row in rows}

async def add_or_update_group(chat_id: int, title: str, username: Optional[str] = None, is_active: bool = True):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            '''
            INSERT INTO target_groups (chat_id, title, username, is_active, status) 
            VALUES (?, ?, ?, ?, 'Healthy')
            ON CONFLICT(chat_id) DO UPDATE SET 
                title=excluded.title,
                username=excluded.username
            ''',
            (chat_id, title, username, is_active)
        )
        await db.commit()

async def set_all_groups_active(is_active: bool):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('UPDATE target_groups SET is_active = ?', (1 if is_active else 0,))
        await db.commit()

async def get_all_groups() -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('SELECT * FROM target_groups') as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def get_active_groups() -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('SELECT * FROM target_groups WHERE is_active = 1') as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def update_group_status(chat_id: int, status: str, is_active: bool = None):
    async with aiosqlite.connect(DB_PATH) as db:
        if is_active is not None:
            await db.execute('UPDATE target_groups SET status = ?, is_active = ? WHERE chat_id = ?', (status, is_active, chat_id))
        else:
            await db.execute('UPDATE target_groups SET status = ? WHERE chat_id = ?', (status, chat_id))
        await db.commit()

async def set_message_history(chat_id: int, message_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            'INSERT OR REPLACE INTO message_history (chat_id, message_id, sent_at) VALUES (?, ?, CURRENT_TIMESTAMP)',
            (chat_id, message_id)
        )
        await db.commit()

async def get_message_history(chat_id: int) -> Optional[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT message_id FROM message_history WHERE chat_id = ?', (chat_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return row[0]
            return None

async def clear_message_history(chat_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('DELETE FROM message_history WHERE chat_id = ?', (chat_id,))
        await db.commit()

async def delete_group(chat_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('DELETE FROM target_groups WHERE chat_id = ?', (chat_id,))
        await db.execute('DELETE FROM message_history WHERE chat_id = ?', (chat_id,))
        await db.commit()

