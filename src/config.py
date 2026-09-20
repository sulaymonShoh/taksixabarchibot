import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Telegram API Credentials
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")

# Channel for 1-Tap Payment Approvals (can be admin private chat ID or channel ID)
ADMIN_CHANNEL_ID = int(os.getenv("ADMIN_CHANNEL_ID", os.getenv("ADMIN_ID", "0")))

# Payment Card Settings
PAYMENT_CARD_NUMBER = os.getenv("PAYMENT_CARD_NUMBER", "8600 0000 0000 0000")
PAYMENT_CARD_HOLDER = os.getenv("PAYMENT_CARD_HOLDER", "ISMI FAMILIYASI")

# Web UI Credentials
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.getenv("WEB_PORT", "8000"))

# Paths
DB_PATH = os.getenv("DB_PATH", "data/broadcast.db")
SESSIONS_DIR = "sessions"
MEDIA_DIR = "media"
LOG_DIR = "logs"
HARVESTER_SESSION_NAME = os.getenv("HARVESTER_SESSION_NAME", "harvester")

# Ensure directories exist
os.makedirs(SESSIONS_DIR, exist_ok=True)
os.makedirs(MEDIA_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)

# Default Settings
DEFAULT_TRIAL_DAYS = 3
DEFAULT_CYCLE_MIN = 60
DEFAULT_CYCLE_MAX = 90
DEFAULT_JITTER_MIN = 1.5
DEFAULT_JITTER_MAX = 2.0

def validate_config():
    missing = []
    if not BOT_TOKEN: missing.append("BOT_TOKEN")
    if not ADMIN_ID: missing.append("ADMIN_ID")
    if not API_ID: missing.append("API_ID")
    if not API_HASH: missing.append("API_HASH")
    
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
