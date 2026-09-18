import os
import asyncio
import contextlib
from datetime import datetime
from typing import Dict, Optional, List
from telethon import TelegramClient
from aiogram import Bot

from src import database as db
from src.bot.auth_flow import get_user_session_path, is_user_authenticated
from src.config import API_ID, API_HASH
from src.worker.worker import UserBroadcastWorker
from src.logger import setup_logger

logger = setup_logger("worker_manager")

class WorkerManager:
    """Manages concurrent, isolated UserBroadcastWorker instances for all active SaaS users."""
    def __init__(self, bot: Bot):
        self.bot = bot
        self.active_workers: Dict[int, UserBroadcastWorker] = {}
        self.active_clients: Dict[int, TelegramClient] = {}
        self.user_tasks: Dict[int, asyncio.Task] = {}
        self.test_events: Dict[int, asyncio.Event] = {}
        self._sync_task: Optional[asyncio.Task] = None
        self._is_running = True

    def get_user_client(self, user_id: int) -> Optional[TelegramClient]:
        """Returns the connected Telethon client for a given user if active."""
        return self.active_clients.get(user_id)

    async def start_user_worker(self, user_id: int) -> bool:
        """Initializes and starts a UserBroadcastWorker for a single user."""
        if not is_user_authenticated(user_id):
            logger.warning(f"Cannot start worker: User {user_id} session does not exist.")
            return False

        # If already running and healthy, keep it
        if user_id in self.user_tasks and not self.user_tasks[user_id].done():
            return True

        # Clean up any lingering resources
        await self.stop_user_worker(user_id)

        session_path = get_user_session_path(user_id)
        try:
            client = TelegramClient(session_path, API_ID, API_HASH)
            await client.connect()
            
            if not await client.is_user_authorized():
                logger.warning(f"User {user_id} session is not authorized.")
                await client.disconnect()
                return False

            test_event = asyncio.Event()
            worker = UserBroadcastWorker(user_id, client, self.bot, test_event)
            task = asyncio.create_task(worker.run_loop())

            self.active_workers[user_id] = worker
            self.active_clients[user_id] = client
            self.user_tasks[user_id] = task
            self.test_events[user_id] = test_event

            logger.info(f"Successfully spawned isolated worker task for User {user_id}.")
            return True
        except Exception as e:
            logger.error(f"Failed to start worker for User {user_id}: {e}")
            return False

    async def stop_user_worker(self, user_id: int):
        """Stops and cleans up the worker and Telethon client for a user."""
        worker = self.active_workers.pop(user_id, None)
        if worker:
            worker.stop()

        task = self.user_tasks.pop(user_id, None)
        if task and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        client = self.active_clients.pop(user_id, None)
        if client:
            with contextlib.suppress(Exception):
                await client.disconnect()

        self.test_events.pop(user_id, None)
        logger.info(f"Stopped worker for User {user_id}.")

    async def trigger_test_round(self, user_id: int) -> bool:
        """Triggers an immediate test round for a user."""
        if user_id in self.test_events:
            self.test_events[user_id].set()
            return True

        # If worker is not currently running, attempt to start it
        if is_user_authenticated(user_id):
            started = await self.start_user_worker(user_id)
            if started and user_id in self.test_events:
                self.test_events[user_id].set()
                return True
        return False

    async def _sync_loop(self):
        """Background synchronization loop ensuring only valid active subscribers run."""
        logger.info("WorkerManager background sync loop started.")
        while self._is_running:
            try:
                users = await db.get_all_users()
                now = datetime.utcnow()

                for user in users:
                    user_id = user['user_id']
                    is_banned = user.get('is_banned', 0)
                    expiry_str = user.get('subscription_expiry')

                    is_valid_sub = False
                    if expiry_str and not is_banned:
                        try:
                            expiry = datetime.strptime(expiry_str, '%Y-%m-%d %H:%M:%S')
                            if expiry > now:
                                is_valid_sub = True
                        except Exception:
                            pass

                    settings = await db.get_user_settings(user_id)
                    is_running = settings.get('is_running', False)

                    # Should be running?
                    if is_valid_sub and is_running and is_user_authenticated(user_id):
                        if user_id not in self.user_tasks or self.user_tasks[user_id].done():
                            await self.start_user_worker(user_id)
                    else:
                        # Should NOT be running?
                        if user_id in self.active_workers:
                            await self.stop_user_worker(user_id)

                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in WorkerManager sync loop: {e}")
                await asyncio.sleep(30)

    def start_sync_loop(self):
        """Starts the periodic background sync task."""
        if not self._sync_task or self._sync_task.done():
            self._sync_task = asyncio.create_task(self._sync_loop())

    async def stop_all(self):
        """Gracefully stops all workers and disconnects all clients."""
        logger.info("Stopping all user workers...")
        self._is_running = False
        if self._sync_task and not self._sync_task.done():
            self._sync_task.cancel()

        user_ids = list(self.active_workers.keys())
        for u_id in user_ids:
            await self.stop_user_worker(u_id)
        logger.info("All user workers stopped cleanly.")
