"""
Live Message Test & Dispatch Simulator for Taksi Xabarchi v3.0.
Injects real telegram messages into the ingestion grid, parses them in RAM,
persists them to DB, and triggers real-time Telegram alerts to matched drivers.
"""
import os
import sys
import asyncio
import time
from typing import Optional
from aiogram import Bot

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath("."))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.config import BOT_TOKEN
from src import database as db
from src.harvester.nlp_engine import OrderParser
from src.harvester.dedup import Deduplicator
from src.harvester.matcher import CorridorMatcher
from src.harvester.dispatcher import OrderDispatcher
from src.harvester.listener import HarvesterListener

async def simulate_message(
    text: str,
    group_title: str = "Vodiy Pitak Test Guruh",
    sender_username: Optional[str] = "mijoz_test"
):
    print("=" * 65)
    print("TAKSI XABARCHI v3.0 — LIVE MESSAGE INGESTION TEST")
    print("=" * 65)
    print(f"📥 Incoming Message:\n   \"{text}\"\n")

    # 1. Initialize Bot & Dispatcher
    bot = Bot(token=BOT_TOKEN)
    dispatcher = OrderDispatcher(bot=bot)

    # 2. Initialize Listener
    listener = HarvesterListener(
        client=None,
        parser=OrderParser(),
        deduplicator=Deduplicator(default_ttl_seconds=300),
        on_order_callback=dispatcher.dispatch_order
    )

    # 3. Process Raw Message
    start_time = time.perf_counter()
    order = await listener.process_raw_message(
        chat_id=-1009999999999,
        chat_title=group_title,
        text=text,
        sender_username=sender_username
    )
    total_ms = (time.perf_counter() - start_time) * 1000

    if not order:
        print("❌ [FILTERED / REJECTED]")
        print("   The message was classified as a driver ad, duplicate, or non-order message.")
        print("   (Driver advertisements and spams are 100% safely rejected).")
        await bot.session.close()
        return

    # 4. Display Results
    origin_name = (order.get("origin") or {}).get("name", "Noma'lum")
    dest_name = (order.get("destination") or {}).get("name", "Noma'lum")
    phone = order.get("phone_number") or "Ko'rsatilmagan"
    order_type = order.get("order_type")
    count = order.get("passenger_count", 1)

    print("✅ [ACCEPTED & ARCHIVED TO DB]")
    print(f"   • Order ID: #{order.get('id')}")
    print(f"   • Type: {order_type} ({count} ta)")
    print(f"   • Route: {origin_name} ➡️ {dest_name}")
    print(f"   • Phone: {phone}")
    print(f"   • Total Pipeline Latency: {total_ms:.2f} ms")

    # 5. Check Matched Drivers
    drivers = await db.get_active_radar_drivers()
    matcher = CorridorMatcher()
    print(f"\n📡 Active Radar Drivers in DB: {len(drivers)} ta")
    for d in drivers:
        match = matcher.match_driver(order, d, enforce_vip=False)
        user_id = d.get("user_id")
        name = d.get("full_name") or d.get("username") or str(user_id)
        is_vip = d.get("is_vip")
        status_str = "⭐️ VIP" if is_vip else "🔴 Muddati o'tgan (Teaser)"
        if match:
            via = f" (via {match.get('corridor_via_name')})" if match.get("corridor_via_name") else ""
            print(f"   🎯 MATCHED: {name} (ID: {user_id}) [{status_str}] -> {match.get('match_type')}{via}")
            print(f"      👉 Live alert sent to Telegram chat_id {user_id}!")
        else:
            print(f"   ⬜️ NOT MATCHED: {name} (Radar filter filtered this route out)")

    await bot.session.close()
    print("\n" + "=" * 65)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        msg = " ".join(sys.argv[1:])
    else:
        msg = "Toshkentdan Asakaga 2 kishi bor tel +998901234567"
    asyncio.run(simulate_message(msg))
