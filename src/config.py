import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Telegram API Credentials
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
SESSION_NAME = os.getenv("SESSION_NAME", "worker_account")

# Paths
DB_PATH = os.getenv("DB_PATH", "data/broadcast.db")
MEDIA_DIR = "media"
LOG_DIR = "logs"

# Ensure directories exist
os.makedirs(MEDIA_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)

# Default Settings
DEFAULT_CYCLE_MIN = 180
DEFAULT_CYCLE_MAX = 300
DEFAULT_JITTER_MIN = 6
DEFAULT_JITTER_MAX = 12

def validate_config():
    missing = []
    if not BOT_TOKEN: missing.append("BOT_TOKEN")
    if not ADMIN_ID: missing.append("ADMIN_ID")
    if not API_ID: missing.append("API_ID")
    if not API_HASH: missing.append("API_HASH")
    
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
