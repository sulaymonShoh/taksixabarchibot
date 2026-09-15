import asyncio
from telethon import TelegramClient
from src.config import API_ID, API_HASH, SESSION_NAME

async def main():
    print("=====================================")
    print("   Telegram MTProto Authentication   ")
    print("=====================================")
    
    if not API_ID or not API_HASH:
        print("Error: API_ID and API_HASH must be set in .env file.")
        return
        
    print(f"Initializing session: {SESSION_NAME}.session")
    
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    
    # .start() will prompt for phone number, code, and 2FA via console
    await client.start()
    
    print("\n✅ Authentication successful!")
    print(f"✅ Session file '{SESSION_NAME}.session' generated and saved.")
    print("You can now start the main application using: python -m src.main")
    
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
