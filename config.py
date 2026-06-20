import json
import os

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}


_config = load_config()

_telegram = _config.get("telegram", {})
_payment = _config.get("payment", {})
_gemini = _config.get("gemini", {})
_server = _config.get("server", {})
_database = _config.get("database", {})

BOT_TOKEN = _telegram.get("bot_token", "")
API_ID = int(_telegram.get("api_id", 0))
API_HASH = _telegram.get("api_hash", "")
ADMIN_ID = int(_telegram.get("admin_id", 0))
BANK_CARD_NUMBER = _payment.get("bank_card_number", "")

DB_USER = _database.get("user", "maxvpn")
DB_PASS = _database.get("password", "maxvpn_pass")
DB_NAME = _database.get("name", "maxvpn_db")
REDIS_URL = _database.get("redis_url", "redis://redis:6379/0")

GEMINI_API_KEY = _gemini.get("api_key", "")
GEMINI_MODEL = _gemini.get("model", "gemini-1.5-pro-latest")

SERVER_HOST = _server.get("host", "localhost")
USE_VALID_SSL = _server.get("use_valid_ssl", False)

PYROGRAM_SESSION_STRING = _config.get("pyrogram_session_string", "")

DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASS}@postgres:5432/{DB_NAME}"
DATABASE_URL_SYNC = f"postgresql://{DB_USER}:{DB_PASS}@postgres:5432/{DB_NAME}"

PLANS = [
    {"id": 1, "name": "10 GB", "data_gb": 10, "price": 100_000, "duration_days": 30},
    {"id": 2, "name": "25 GB", "data_gb": 25, "price": 250_000, "duration_days": 30},
    {"id": 3, "name": "50 GB", "data_gb": 50, "price": 500_000, "duration_days": 30},
    {"id": 4, "name": "100 GB", "data_gb": 100, "price": 1_000_000, "duration_days": 30},
]

PLAN_MAP = {p["id"]: p for p in PLANS}

SOURCE_BOT = "MMDLeecherNimBot"
