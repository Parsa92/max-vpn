import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
ADMIN_ID = int(os.environ["ADMIN_ID"])
BANK_CARD_NUMBER = os.environ.get("BANK_CARD_NUMBER", "")

DB_USER = os.environ.get("DB_USER", "maxvpn")
DB_PASS = os.environ.get("DB_PASS", "maxvpn_pass")
DB_NAME = os.environ.get("DB_NAME", "maxvpn_db")
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-1.5-pro-latest")

SERVER_HOST = os.environ.get("SERVER_HOST", "localhost")
USE_VALID_SSL = os.environ.get("USE_VALID_SSL", "False").lower() == "true"

PYROGRAM_SESSION_STRING = os.environ.get("PYROGRAM_SESSION_STRING", "")

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
