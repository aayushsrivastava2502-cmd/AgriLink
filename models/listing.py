import os
import secrets
from datetime import date, datetime
from decimal import Decimal

from . import CATEGORIES, QUALITIES
from services.distance_service import valid_coords
from services.money import parse_decimal, q2, to_decimal

IMAGE_SIGNATURES = {  # magic bytes -> extension (never trust the client's file name/type)
    b"\x89PNG\r\n\x1a\n": "png",
    b"\xff\xd8\xff": "jpg",
    b"GIF87a": "gif",
    b"GIF89a": "gif",
}


def validate_listing(form, today=None):
    today = today or date.today()
    errors, clean = {}, {}
    clean["crop_name"] = " ".join((form.get("crop_name") or "").split())
    clean["category"] = (form.get("category") or "").strip()
    clean["quality"] = (form.get("quality") or "").strip()
    clean["city"] = " ".join((form.get("city") or "").split())
    clean["state"] = " ".join((form.get("state") or "").split())
    clean["description"] = (form.get("description") or "").strip()
    clean["image_url"] = (form.get("image_url") or "").strip()

    if not 2 <= len(clean["crop_name"]) <= 60:
        errors["crop_name"] = "Enter the crop name (2–60 characters)."
    if clean["category"] not in CATEGORIES:
        errors["category"] = "Choose a category."
    if clean["quality"] not in QUALITIES:
        errors["quality"] = "Choose the crop quality."
    if not 2 <= len(clean["city"]) <= 80:
        errors["city"] = "Enter the village or city."
    if not 2 <= len(clean["state"]) <= 60:
        errors["state"] = "Enter the state."
    if len(clean["description"]) > 1000:
        errors["description"] = "Description must be 1000 characters or fewer."
    if clean["image_url"] and (len(clean["image_url"]) > 500
                               or not clean["image_url"].lower().startswith(("http://", "https://"))):
        errors["image_url"] = "Image URL must start with http:// or https://."

    for key, label, kw in (
        ("quantity_kg", "Quantity", dict(minimum=Decimal(0), maximum=Decimal(1_000_000))),
        ("price_per_kg", "Asking price (₹/kg)", dict(minimum=Decimal(0), maximum=Decimal(10_000))),
    ):
        try:
            clean[key] = parse_decimal(form.get(key), label, **kw)
        except ValueError as exc:
            errors[key] = str(exc)

    try:
        hd = datetime.strptime((form.get("harvest_date") or "").strip(), "%Y-%m-%d").date()
        if hd > today:
            errors["harvest_date"] = "Harvest date cannot be in the future."
        else:
            clean["harvest_date"] = hd.isoformat()
    except ValueError:
        errors["harvest_date"] = "Enter a valid harvest date."

    lat_raw, lng_raw = (form.get("latitude") or "").strip(), (form.get("longitude") or "").strip()
    clean["latitude"] = clean["longitude"] = None
    if lat_raw or lng_raw:
        try:
            lat = float(parse_decimal(lat_raw, "Latitude", places=6))
            lng = float(parse_decimal(lng_raw, "Longitude", places=6))
            if not valid_coords(lat, lng):
                raise ValueError("Latitude must be -90 to 90 and longitude -180 to 180.")
            clean["latitude"], clean["longitude"] = lat, lng
        except ValueError as exc:
            errors["latitude"] = str(exc)
    return clean, errors


def save_upload(file_storage, upload_folder):
    """Validate (size, magic bytes) and store an uploaded image under a random name."""
    if not file_storage or not file_storage.filename:
        return None
    head = file_storage.stream.read(16)
    file_storage.stream.seek(0)
    ext = next((e for sig, e in IMAGE_SIGNATURES.items() if head.startswith(sig)), None)
    if ext is None and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        ext = "webp"
    if ext is None:
        raise ValueError("Upload a PNG, JPG, GIF or WEBP image.")
    os.makedirs(upload_folder, exist_ok=True)
    name = f"{secrets.token_hex(12)}.{ext}"
    file_storage.save(os.path.join(upload_folder, name))
    return f"/static/uploads/{name}"


def _status_for(quantity, requested_status="active"):
    if requested_status == "unavailable":
        return "unavailable"
    return "sold_out" if to_decimal(quantity) <= 0 else "active"


def create_listing(db, farmer_id, clean, image_url, is_demo=False):
    cur = db.execute(
        "INSERT INTO crop_listings (farmer_id, crop_name, category, quantity_kg, price_per_kg, quality,"
        " harvest_date, city, state, latitude, longitude, description, image_url, status, is_demo)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (farmer_id, clean["crop_name"], clean["category"], float(q2(clean["quantity_kg"])),
         float(q2(clean["price_per_kg"])), clean["quality"], clean["harvest_date"], clean["city"],
         clean["state"], clean["latitude"], clean["longitude"], clean["description"] or None,
         image_url or None, _status_for(clean["quantity_kg"]), int(is_demo)))
    return cur.lastrowid


def get_listing(db, listing_id):
    return db.execute(
        "SELECT l.*, u.full_name AS farmer_name, u.city AS farmer_city, u.state AS farmer_state,"
        " u.created_at AS farmer_since FROM crop_listings l JOIN users u ON u.id = l.farmer_id"
        " WHERE l.id = ?", (listing_id,)).fetchone()


def update_listing(db, listing_id, farmer_id, clean, image_url):
    """Ownership is enforced in SQL (WHERE farmer_id = ?). Returns True if a row was updated."""
    current = db.execute("SELECT status FROM crop_listings WHERE id = ? AND farmer_id = ?",
                         (listing_id, farmer_id)).fetchone()
    if current is None:
        return False
    status = _status_for(clean["quantity_kg"], current["status"])
    db.execute(
        "UPDATE crop_listings SET crop_name=?, category=?, quantity_kg=?, price_per_kg=?, quality=?,"
        " harvest_date=?, city=?, state=?, latitude=?, longitude=?, description=?, image_url=?,"
        " status=?, updated_at=CURRENT_TIMESTAMP WHERE id=? AND farmer_id=?",
        (clean["crop_name"], clean["category"], float(q2(clean["quantity_kg"])),
         float(q2(clean["price_per_kg"])), clean["quality"], clean["harvest_date"], clean["city"],
         clean["state"], clean["latitude"], clean["longitude"], clean["description"] or None,
         image_url or None, status, listing_id, farmer_id))
    return True


def delete_listing(db, listing_id, farmer_id):
    """Returns 'deleted', 'not_found' or 'has_open_orders'."""
    row = db.execute("SELECT id FROM crop_listings WHERE id=? AND farmer_id=?",
                     (listing_id, farmer_id)).fetchone()
    if row is None:
        return "not_found"
    open_orders = db.execute(
        "SELECT COUNT(*) FROM order_requests WHERE listing_id=? AND status IN ('pending','accepted')",
        (listing_id,)).fetchone()[0]
    if open_orders:
        return "has_open_orders"
    db.execute("DELETE FROM crop_listings WHERE id=? AND farmer_id=?", (listing_id, farmer_id))
    return "deleted"


def toggle_availability(db, listing_id, farmer_id):
    """active <-> unavailable. A sold-out listing needs its quantity edited first."""
    row = db.execute("SELECT status, quantity_kg FROM crop_listings WHERE id=? AND farmer_id=?",
                     (listing_id, farmer_id)).fetchone()
    if row is None:
        return None
    if row["status"] == "active":
        new = "unavailable"
    elif row["status"] == "unavailable" and row["quantity_kg"] > 0:
        new = "active"
    else:
        return row["status"]
    db.execute("UPDATE crop_listings SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=? AND farmer_id=?",
               (new, listing_id, farmer_id))
    return new


def farmer_listings(db, farmer_id):
    return db.execute("SELECT * FROM crop_listings WHERE farmer_id=? ORDER BY created_at DESC, id DESC",
                      (farmer_id,)).fetchall()


def farmer_stats(db, farmer_id):
    total = db.execute("SELECT COUNT(*) FROM crop_listings WHERE farmer_id=?", (farmer_id,)).fetchone()[0]
    counts = {r["status"]: r["n"] for r in db.execute(
        "SELECT status, COUNT(*) AS n FROM order_requests WHERE farmer_id=? GROUP BY status", (farmer_id,))}
    value = sum((to_decimal(r["quantity_kg"]) * to_decimal(r["price_per_kg"]) for r in db.execute(
        "SELECT quantity_kg, price_per_kg FROM crop_listings WHERE farmer_id=? AND status='active'",
        (farmer_id,))), Decimal(0))
    return {"total_listings": total, "pending": counts.get("pending", 0),
            "accepted": counts.get("accepted", 0), "completed": counts.get("completed", 0),
            "available_value": q2(value)}
