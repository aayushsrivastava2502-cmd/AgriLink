import re
import sqlite3

from werkzeug.security import check_password_hash, generate_password_hash

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
PHONE_RE = re.compile(r"^(?:\+91[\s-]?)?[6-9]\d{9}$")
_DUMMY_HASH = generate_password_hash("not-a-real-password")


def validate_registration(form):
    errors, clean = {}, {}
    clean["full_name"] = " ".join((form.get("full_name") or "").split())
    clean["email"] = (form.get("email") or "").strip().lower()
    clean["phone"] = (form.get("phone") or "").strip()
    clean["role"] = (form.get("role") or "").strip()
    clean["city"] = " ".join((form.get("city") or "").split())
    clean["state"] = " ".join((form.get("state") or "").split())
    password = form.get("password") or ""
    if not 2 <= len(clean["full_name"]) <= 80:
        errors["full_name"] = "Enter your full name (2–80 characters)."
    if not EMAIL_RE.match(clean["email"]) or len(clean["email"]) > 120:
        errors["email"] = "Enter a valid email address."
    if not PHONE_RE.match(clean["phone"]):
        errors["phone"] = "Enter a valid 10-digit Indian mobile number (optionally with +91)."
    if clean["role"] not in ("farmer", "buyer"):
        errors["role"] = "Choose whether you are a farmer or a buyer."
    if not 2 <= len(clean["city"]) <= 80:
        errors["city"] = "Enter your village or city."
    if not 2 <= len(clean["state"]) <= 60:
        errors["state"] = "Enter your state."
    if len(password) < 8 or len(password) > 128 or not re.search(r"[A-Za-z]", password) \
            or not re.search(r"\d", password):
        errors["password"] = "Password must be 8+ characters with at least one letter and one number."
    elif password != (form.get("confirm_password") or ""):
        errors["confirm_password"] = "Passwords do not match."
    return clean, password, errors


def create_user(db, clean, password, is_demo=False, password_hash=None):
    """Returns the new user id, or None if the email is already registered."""
    try:
        cur = db.execute(
            "INSERT INTO users (full_name, email, password_hash, phone, role, city, state, is_demo)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (clean["full_name"], clean["email"], password_hash or generate_password_hash(password),
             clean["phone"], clean["role"], clean["city"], clean["state"], int(is_demo)))
        return cur.lastrowid
    except Exception as exc:
        if "unique" in str(exc).lower() or "integrity" in str(exc).lower() or "duplicate" in str(exc).lower():
            return None
        raise


def get_by_id(db, user_id):
    return db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def authenticate(db, email, password):
    row = db.execute("SELECT * FROM users WHERE email = ?", ((email or "").strip().lower(),)).fetchone()
    if row is None:
        check_password_hash(_DUMMY_HASH, password or "")  # keep timing similar
        return None
    return row if check_password_hash(row["password_hash"], password or "") else None
