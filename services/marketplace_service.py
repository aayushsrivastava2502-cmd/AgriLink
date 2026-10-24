"""Marketplace search, nearby-farmer ranking and delivered-cost estimates (all INR)."""
from decimal import Decimal, InvalidOperation

from models import QUALITIES
from .distance_service import haversine_km, transport_cost, delivered_cost, valid_coords
from .money import q2, to_decimal

PER_PAGE = 12
SORTS = {"newest": "Recently added", "price_asc": "Price: low to high",
         "price_desc": "Price: high to low", "nearest": "Nearest farmer"}


def _dec(value):
    try:
        d = Decimal(str(value).strip().replace(",", ""))
        return d if d.is_finite() and d >= 0 else None
    except (InvalidOperation, ValueError, AttributeError):
        return None


def _like(text):
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def parse_filters(args):
    f = {"q": (args.get("q") or "").strip()[:60], "category": (args.get("category") or "").strip(),
         "location": (args.get("location") or "").strip()[:60], "quality": (args.get("quality") or "").strip(),
         "min_price": _dec(args.get("min_price", "")) if args.get("min_price") else None,
         "max_price": _dec(args.get("max_price", "")) if args.get("max_price") else None,
         "min_qty": _dec(args.get("min_qty", "")) if args.get("min_qty") else None,
         "sort": args.get("sort") if args.get("sort") in SORTS else "newest"}
    if f["quality"] not in QUALITIES:
        f["quality"] = ""
    try:
        f["farmer"] = int(args.get("farmer")) if args.get("farmer") else None
    except ValueError:
        f["farmer"] = None
    try:
        f["page"] = max(1, int(args.get("page", 1)))
    except ValueError:
        f["page"] = 1
    return f


def search_listings(db, f, location=None):
    where, params = ["l.status='active'", "l.quantity_kg>0"], []
    if f["q"]:
        where.append("l.crop_name LIKE ? ESCAPE '\\'"); params.append(_like(f["q"]))
    if f["category"]:
        where.append("l.category=?"); params.append(f["category"])
    if f["location"]:
        where.append("(l.city LIKE ? ESCAPE '\\' OR l.state LIKE ? ESCAPE '\\')")
        params += [_like(f["location"])] * 2
    if f["quality"]:
        where.append("l.quality=?"); params.append(f["quality"])
    if f["min_price"] is not None:
        where.append("l.price_per_kg>=?"); params.append(float(f["min_price"]))
    if f["max_price"] is not None:
        where.append("l.price_per_kg<=?"); params.append(float(f["max_price"]))
    if f["min_qty"] is not None:
        where.append("l.quantity_kg>=?"); params.append(float(f["min_qty"]))
    if f["farmer"]:
        where.append("l.farmer_id=?"); params.append(f["farmer"])
    order = {"price_asc": "l.price_per_kg ASC, l.id", "price_desc": "l.price_per_kg DESC, l.id"}.get(
        f["sort"], "l.created_at DESC, l.id DESC")
    rows = [dict(r) for r in db.execute(
        "SELECT l.*, u.full_name AS farmer_name FROM crop_listings l JOIN users u ON u.id=l.farmer_id"
        f" WHERE {' AND '.join(where)} ORDER BY {order}", params)]
    notice = None
    for r in rows:
        r["distance_km"] = (haversine_km(location[0], location[1], r["latitude"], r["longitude"])
                            if location else None)
    if f["sort"] == "nearest":
        if location:
            rows.sort(key=lambda r: (r["distance_km"] is None, r["distance_km"] or 0))
        else:
            notice = "Set your location to sort by nearest farmer; showing recently added instead."
    total = len(rows)
    start = (f["page"] - 1) * PER_PAGE
    return rows[start:start + PER_PAGE], total, notice


def rank_farmers(db, crop, qty, location, max_price=None, quality=None, rate=None, min_qty=None):
    """Rank matching listings. Score (0-100) blends availability, price and, when both sides have valid
    coordinates, distance. Weights: availability 40%, price 30%, distance 30% (re-normalised without distance)."""
    where, params = ["l.status='active'", "l.quantity_kg>0"], []
    if crop:
        where.append("l.crop_name LIKE ? ESCAPE '\\'"); params.append(_like(crop))
    if quality in QUALITIES:
        where.append("l.quality=?"); params.append(quality)
    if max_price is not None:
        where.append("l.price_per_kg<=?"); params.append(float(max_price))
    if min_qty is not None:
        where.append("l.quantity_kg>=?"); params.append(float(min_qty))
    rows = [dict(r) for r in db.execute(
        "SELECT l.*, u.full_name AS farmer_name, u.is_demo AS farmer_is_demo FROM crop_listings l"
        f" JOIN users u ON u.id=l.farmer_id WHERE {' AND '.join(where)}", params)]
    if not rows:
        return []
    cheapest = min(r["price_per_kg"] for r in rows)
    for r in rows:
        r["distance_km"] = haversine_km(location[0], location[1], r["latitude"], r["longitude"]) if location else None
        avail = 1.0 if not qty else min(1.0, r["quantity_kg"] / float(qty))
        price_s = cheapest / r["price_per_kg"]
        r["covers_request"] = (not qty) or r["quantity_kg"] >= float(qty)
        if r["distance_km"] is not None:
            dist_s = max(0.0, 1 - r["distance_km"] / 150.0)
            score = 0.4 * avail + 0.3 * price_s + 0.3 * dist_s
        else:
            score = (0.4 * avail + 0.3 * price_s) / 0.7
        r["score"] = round(score * 100)
        buy_qty = to_decimal(min(float(qty), r["quantity_kg"])) if qty else None
        r["product_cost"] = q2(buy_qty * to_decimal(r["price_per_kg"])) if buy_qty else None
        r["transport_cost"] = r["delivered_cost"] = None
        if r["distance_km"] is not None and rate is not None:
            r["transport_cost"] = transport_cost(r["distance_km"], rate)
            if r["product_cost"] is not None:
                r["delivered_cost"] = delivered_cost(r["product_cost"], r["transport_cost"])
    rows.sort(key=lambda r: (-r["score"], r["distance_km"] is None, r["distance_km"] or 0))
    return rows


def group_by_farmer(rows):
    """One map marker per farmer location, listing every matching crop."""
    groups = {}
    for r in rows:
        if not valid_coords(r["latitude"], r["longitude"]):
            continue
        key = (r["farmer_id"], round(r["latitude"], 4), round(r["longitude"], 4))
        g = groups.setdefault(key, {"farmer_id": r["farmer_id"], "farmer": r["farmer_name"], "lat": r["latitude"],
                                    "lng": r["longitude"], "place": f"{r['city']}, {r['state']}",
                                    "distance_km": r["distance_km"], "crops": []})
        g["crops"].append({"listing_id": r["id"], "crop": r["crop_name"], "price": float(r["price_per_kg"]),
                           "quantity": float(r["quantity_kg"]), "quality": r["quality"]})
    return list(groups.values())
