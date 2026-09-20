"""
Interactive CLI Login Tool for Taksi Xabarchi Harvester Userbot.
Authorizes the dedicated Telegram account for supergroup listening
and creates 'sessions/harvester.session'.
"""
import os
import sys
import asyncio

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath("."))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from src.config import API_ID, API_HASH, SESSIONS_DIR, HARVESTER_SESSION_NAME

async def main():
    print("=" * 65)
    print("🚗 TAKSI XABARCHI v3.0 — HARVESTER USERBOT LOGIN UTILITY")
    print("=" * 65)
    print("This utility will connect your dedicated Telegram listener account")
    print("to listen to real taxi order supergroups 24/7 in background.\n")

    os.makedirs(SESSIONS_DIR, exist_ok=True)
    session_path = os.path.join(SESSIONS_DIR, HARVESTER_SESSION_NAME)
    
    client = TelegramClient(session_path, API_ID, API_HASH)
    await client.connect()

    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"✅ Akkaunt allaqachon ulangan:")
        print(f"   • Ism: {me.first_name} {me.last_name or ''}")
        print(f"   • Username: @{me.username or 'yo\'q'}")
        print(f"   • Telefon: {me.phone or 'yo\'q'}")
        print(f"   • Sessiya: {session_path}.session\n")
        reauth = input("Qaytadan boshqa akkaunt bilan ulamoqchimisiz? (ha/yo'q): ").strip().lower()
        if reauth not in ("ha", "yes", "y"):
            print("Bekor qilindi. Harvester tayyor!")
            await client.disconnect()
            return
        await client.log_out()
        await client.connect()

    print("📞 Telegram akkauntingiz telefon raqamini kiriting:")
    print("   Misol: +998901234567")
    phone = input("Telefon: ").strip()

    if not phone:
        print("❌ Telefon raqami kiritilmadi. Bekor qilindi.")
        await client.disconnect()
        return

    print(f"\n📨 {phone} raqamiga Telegram orqali tasdiqlash kodi yuborilmoqda...")
    send_code = await client.send_code_request(phone)

    code = input("🔢 Telegramga kelgan 5 xonali kodni kiriting: ").strip()
    # Remove any accidental spaces or dashes
    code = code.replace(" ", "").replace("-", "")

    try:
        await client.sign_in(phone=phone, code=code, phone_code_hash=send_code.phone_code_hash)
    except SessionPasswordNeededError:
        print("\n🔐 Ushbu akkauntda 2FA (Ikki bosqichli parol) o'rnatilgan.")
        password = input("2FA Parolingizni kiriting: ").strip()
        await client.sign_in(password=password)

    me = await client.get_me()
    print("\n" + "=" * 65)
    print("🎉 TABRIKLAYMIZ! HARVESTER USERBOT MUVAFFAQIYATLI ULANGI!")
    print("=" * 65)
    print(f"   • Ism: {me.first_name} {me.last_name or ''}")
    print(f"   • Username: @{me.username or 'yo\'q'}")
    print(f"   • Telefon: +{me.phone}")
    print(f"   • Sessiya fayli: {session_path}.session")
    print("\n👉 Endi botni ishga tushirsangiz ('python -m src.main'), Harvester")
    print("   avtomatik ravishda ushbu akkaunt orqali guruhlarni tinglay boshlaydi!")
    print("=" * 65)

    await client.disconnect()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nJarayon foydalanuvchi tomonidan bekor qilindi.")
