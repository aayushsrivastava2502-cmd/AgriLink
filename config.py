"""Application configuration.
Environment variables configure secrets, databases, and runtime behavior:
- AGRILINK_SECRET_KEY / SECRET_KEY: Session signing key (required in production).
- DATABASE_URL / POSTGRES_URL: PostgreSQL connection URI (for managed production DB).
- AGRILINK_DB: Path to local SQLite database (for local development or testing).
- AGRILINK_HTTPS: Set to 1 when running behind HTTPS (automatically True on Vercel).
- AUTO_SEED: Set to 0 to skip automatic demo data seeding.
"""
import os
import secrets
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"


def _load_secret_key() -> str:
    env_key = os.environ.get("AGRILINK_SECRET_KEY") or os.environ.get("SECRET_KEY")
    if env_key:
        return env_key
    # On Vercel / serverless environment, local filesystem outside /tmp is read-only
    if os.environ.get("VERCEL"):
        tmp_key = Path("/tmp/secret.key")
        if tmp_key.exists():
            try:
                return tmp_key.read_text().strip()
            except Exception:
                pass
        gen_key = secrets.token_hex(32)
        try:
            tmp_key.write_text(gen_key)
        except Exception:
            pass
        return gen_key

    # Local development: persist to instance/secret.key
    try:
        INSTANCE_DIR.mkdir(exist_ok=True)
        key_file = INSTANCE_DIR / "secret.key"
        if not key_file.exists():
            key_file.write_text(secrets.token_hex(32))
        return key_file.read_text().strip()
    except OSError:
        return secrets.token_hex(32)


def _load_database_uri() -> str:
    # 1. Managed PostgreSQL database URL (Neon, Supabase, Vercel Postgres, Render, etc.)
    db_url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if db_url:
        return db_url
    # 2. Explicit SQLite override
    custom_sqlite = os.environ.get("AGRILINK_DB")
    if custom_sqlite:
        return custom_sqlite
    # 3. Serverless fallback: /tmp is the only writable directory on Vercel
    if os.environ.get("VERCEL"):
        return "/tmp/agrilink.db"
    # 4. Standard local development path
    return str(INSTANCE_DIR / "agrilink.db")


class Config:
    SECRET_KEY = _load_secret_key()
    DATABASE = _load_database_uri()
    UPLOAD_FOLDER = "/tmp/uploads" if os.environ.get("VERCEL") else str(BASE_DIR / "static" / "uploads")
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024  # 2 MB uploads
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("AGRILINK_HTTPS", "0") == "1" or bool(os.environ.get("VERCEL"))
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    MODEL_DIR = str(BASE_DIR / "ml" / "artifacts")
    DEFAULT_TRANSPORT_RATE = 12  # illustrative Rs per km
    CSRF_ENABLED = True
    AUTO_SEED = os.environ.get("AUTO_SEED", "1").lower() not in ("0", "false", "no")
