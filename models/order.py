"""Order workflow.

Stock model used by this prototype (no payments):
  * Sending a request does NOT lock stock; it only checks the quantity against what is available.
  * When the farmer ACCEPTS, stock is deducted inside one BEGIN IMMEDIATE transaction after
    re-checking availability, so stock can never go negative and two accepts cannot oversell.
  * REJECT / CANCEL of a pending request changes nothing in stock (nothing was reserved).
  * COMPLETE marks an accepted order as handed over. Stock stays deducted.
Allowed transitions: pending -> accepted | rejected | cancelled ; accepted -> completed.
"""
from decimal import Decimal

from . import transaction
from services.money import q2, to_decimal


class OrderError(ValueError):
    pass


def validate_order_input(form):
    from services.money import parse_decimal
    from services.distance_service import valid_coords
    errors, clean = {}, {}
    try:
        clean["quantity_kg"] = parse_decimal(form.get("quantity_kg"), "Quantity",
                                             minimum=Decimal(0), maximum=Decimal(1_000_000))
    except ValueError as exc:
        errors["quantity_kg"] = str(exc)
    clean["delivery_preference"] = (form.get("delivery_preference") or "pickup").strip()
    if clean["delivery_preference"] not in ("pickup", "delivery"):
        errors["delivery_preference"] = "Choose pickup or delivery."
    clean["message"] = (form.get("message") or "").strip()
    if len(clean["message"]) > 500:
        errors["message"] = "Message must be 500 characters or fewer."
    clean["delivery_address"] = (form.get("delivery_address") or "").strip()[:200]
    lat_val, lng_val = (form.get("delivery_lat") or "").strip(), (form.get("delivery_lng") or "").strip()
    clean["delivery_lat"] = float(lat_val) if lat_val and valid_coords(lat_val, lng_val) else None
    clean["delivery_lng"] = float(lng_val) if lng_val and valid_coords(lat_val, lng_val) else None
    return clean, errors


def create_order(db, buyer_id, listing_id, clean, is_demo=False):
    with transaction(db):
        listing = db.execute("SELECT * FROM crop_listings WHERE id=?", (listing_id,)).fetchone()
        if listing is None:
            raise OrderError("This listing no longer exists.")
        if listing["status"] != "active":
            raise OrderError("This listing is not available right now.")
        if listing["farmer_id"] == buyer_id:
            raise OrderError("You cannot order your own listing.")
        qty = clean["quantity_kg"]
        if qty <= 0:
            raise OrderError("Quantity must be greater than zero.")
        if qty > to_decimal(listing["quantity_kg"]):
            raise OrderError(f"Only {to_decimal(listing['quantity_kg']).normalize():f} kg is available.")
        total = q2(qty * to_decimal(listing["price_per_kg"]))
        cur = db.execute(
            "INSERT INTO order_requests (listing_id, buyer_id, farmer_id, crop_name, price_per_kg,"
            " quantity_kg, product_cost, delivery_preference, message, is_demo,"
            " delivery_address, delivery_lat, delivery_lng)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (listing_id, buyer_id, listing["farmer_id"], listing["crop_name"], listing["price_per_kg"],
             float(q2(qty)), float(total), clean["delivery_preference"], clean.get("message") or None,
             int(is_demo), clean.get("delivery_address") or None,
             clean.get("delivery_lat"), clean.get("delivery_lng")))
        return cur.lastrowid


def _set_status(db, order_id, user_id, role, allowed_from, new_status):
    owner_col = "farmer_id" if role == "farmer" else "buyer_id"
    with transaction(db):
        order = db.execute(f"SELECT * FROM order_requests WHERE id=? AND {owner_col}=?",
                           (order_id, user_id)).fetchone()
        if order is None:
            raise OrderError("Order not found.")
        if order["status"] not in allowed_from:
            raise OrderError(f"A {order['status']} order cannot be changed to {new_status}.")
        if new_status == "accepted":
            listing = db.execute("SELECT * FROM crop_listings WHERE id=?", (order["listing_id"],)).fetchone()
            if listing is None or listing["status"] != "active":
                raise OrderError("The listing is no longer available, so this order cannot be accepted.")
            remaining = to_decimal(listing["quantity_kg"]) - to_decimal(order["quantity_kg"])
            if remaining < 0:
                raise OrderError("Not enough stock left to accept this order.")
            db.execute("UPDATE crop_listings SET quantity_kg=?, status=?, updated_at=CURRENT_TIMESTAMP"
                       " WHERE id=?", (float(q2(remaining)), "sold_out" if remaining == 0 else "active",
                                       listing["id"]))
        db.execute("UPDATE order_requests SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                   (new_status, order_id))


def accept(db, order_id, farmer_id):
    _set_status(db, order_id, farmer_id, "farmer", ("pending",), "accepted")


def reject(db, order_id, farmer_id):
    _set_status(db, order_id, farmer_id, "farmer", ("pending",), "rejected")


def complete(db, order_id, farmer_id):
    _set_status(db, order_id, farmer_id, "farmer", ("accepted",), "completed")


def cancel(db, order_id, buyer_id):
    _set_status(db, order_id, buyer_id, "buyer", ("pending",), "cancelled")


_SELECT = ("SELECT o.*, b.full_name AS buyer_name, b.city AS buyer_city, f.full_name AS farmer_name,"
           " f.city AS farmer_city, f.phone AS farmer_phone, b.phone AS buyer_phone,"
           " sto.trip_id, st.trip_code, st.status AS trip_status, sto.allocated_cost AS trip_allocated_cost,"
           " sto.savings AS trip_savings, sto.savings_percent AS trip_savings_percent"
           " FROM order_requests o JOIN users b ON b.id=o.buyer_id JOIN users f ON f.id=o.farmer_id "
           " LEFT JOIN shared_trip_orders sto ON sto.order_id=o.id"
           " LEFT JOIN shared_trips st ON st.id=sto.trip_id ")


def orders_for(db, user_id, role, status=None, limit=None):
    col = "farmer_id" if role == "farmer" else "buyer_id"
    sql, params = _SELECT + f"WHERE o.{col}=?", [user_id]
    if status:
        sql += " AND o.status=?"
        params.append(status)
    sql += " ORDER BY o.created_at DESC, o.id DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return db.execute(sql, params).fetchall()


def buyer_stats(db, buyer_id):
    counts = {r["status"]: r["n"] for r in db.execute(
        "SELECT status, COUNT(*) AS n FROM order_requests WHERE buyer_id=? GROUP BY status", (buyer_id,))}
    committed = sum((to_decimal(r["product_cost"]) for r in db.execute(
        "SELECT product_cost FROM order_requests WHERE buyer_id=? AND status IN ('accepted','completed')",
        (buyer_id,))), Decimal(0))
    return {"counts": counts, "total": sum(counts.values()), "committed_value": q2(committed)}
