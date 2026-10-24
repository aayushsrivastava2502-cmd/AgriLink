from datetime import date, datetime
from decimal import Decimal

from flask import Blueprint, abort, current_app, g, jsonify, redirect, render_template, request, session, url_for

from models import CATEGORIES, QUALITIES, get_db, listing as L
from services import marketplace_service as M
from services import pricing_service as P
from services.distance_service import PRESET_LOCATIONS, haversine_km, transport_cost, valid_coords
from services.money import q2, to_decimal
from .helpers import get_location, safe_next

bp = Blueprint("main", __name__)


def _rate(raw):
    try:
        d = Decimal(str(raw).strip())
        return d if d.is_finite() and 0 <= d <= 1000 else Decimal(current_app.config["DEFAULT_TRANSPORT_RATE"])
    except Exception:
        return Decimal(current_app.config["DEFAULT_TRANSPORT_RATE"])


@bp.route("/")
def index():
    db = get_db()
    one = lambda sql: db.execute(sql).fetchone()[0]
    stats = {"farmers": one("SELECT COUNT(*) FROM users WHERE role='farmer'"),
             "buyers": one("SELECT COUNT(*) FROM users WHERE role='buyer'"),
             "listings": one("SELECT COUNT(*) FROM crop_listings WHERE status='active'"),
             "kg": one("SELECT COALESCE(SUM(quantity_kg),0) FROM crop_listings WHERE status='active'"),
             "orders": one("SELECT COUNT(*) FROM order_requests"),
             "has_demo": one("SELECT COUNT(*) FROM users WHERE is_demo=1") > 0}
    featured = [dict(r) for r in db.execute(
        "SELECT l.*, u.full_name AS farmer_name FROM crop_listings l JOIN users u ON u.id=l.farmer_id"
        " WHERE l.status='active' AND l.quantity_kg>0 ORDER BY l.created_at DESC, l.id DESC LIMIT 8")]
    return render_template("index.html", stats=stats, featured=featured, crops=P.known_crops(db),
                           model=P.model_status(current_app.config["MODEL_DIR"]))


@bp.route("/marketplace")
def marketplace():
    db = get_db()
    f = M.parse_filters(request.args)
    loc = get_location()
    items, total, notice = M.search_listings(db, f, loc[:2] if loc else None)
    pages = max(1, -(-total // M.PER_PAGE))
    args = {k: v for k, v in request.args.items() if k != "page"}
    return render_template("marketplace.html", items=items, total=total, f=f, raw=request.args, loc=loc,
                           notice=notice, pages=pages, page_args=args, categories=CATEGORIES, qualities=QUALITIES,
                           sorts=M.SORTS)


@bp.route("/listing/<int:listing_id>")
def product_detail(listing_id):
    listing = L.get_listing(get_db(), listing_id)
    if listing is None:
        abort(404)
    listing = dict(listing)
    loc = get_location()
    rate = _rate(request.args.get("rate", current_app.config["DEFAULT_TRANSPORT_RATE"]))
    dist = haversine_km(loc[0], loc[1], listing["latitude"], listing["longitude"]) if loc else None
    other = [dict(r) for r in get_db().execute(
        "SELECT id, crop_name, price_per_kg, quantity_kg FROM crop_listings WHERE farmer_id=? AND id<>? AND"
        " status='active' ORDER BY id", (listing["farmer_id"], listing_id))]
    return render_template("product_detail.html", l=listing, loc=loc, distance=dist, rate=rate, other=other,
                           transport=transport_cost(dist, rate) if dist is not None else None,
                           is_owner=bool(g.user and g.user["id"] == listing["farmer_id"]))


@bp.route("/price-estimator")
def price_estimator():
    db = get_db()
    args = request.args
    values = {"crop": args.get("crop", "").strip(), "market": args.get("market", "").strip(),
              "date": args.get("date") or date.today().isoformat(), "quantity": args.get("quantity", ""),
              "quality": args.get("quality", ""), "asking": args.get("asking", "")}
    errors, result = [], None
    listing_id = args.get("listing", type=int)
    if listing_id and not values["crop"]:
        l = L.get_listing(db, listing_id)
        if l:
            values.update(crop=l["crop_name"], market=l["city"], quality=l["quality"],
                          asking=f"{l['price_per_kg']:g}", quantity=f"{l['quantity_kg']:g}")
            args = {**values}
    if values["crop"] or args.get("go"):
        try:
            target = datetime.strptime(values["date"], "%Y-%m-%d").date()
        except ValueError:
            errors.append("Enter a valid date."); target = None
        asking = None
        if values["asking"].strip():
            try:
                asking = Decimal(values["asking"].strip())
                if asking <= 0 or not asking.is_finite():
                    raise ValueError
            except Exception:
                errors.append("Asking price must be a positive number in ₹/kg."); asking = None
        if not values["crop"].strip():
            errors.append("Enter a crop name.")
        if not errors:
            result = P.estimate(db, current_app.config["DATABASE"], current_app.config["MODEL_DIR"], values["crop"],
                                values["market"], target, values["quantity"] or None,
                                values["quality"] if values["quality"] in QUALITIES else None, asking)
    chart = None
    if result and result["reference"] is not None:
        labels, data = ["Reference price"], [float(result["reference"])]
        if result.get("asking") is not None:
            labels.append("Asking price"); data.append(float(result["asking"]))
        chart = {"type": "bar", "labels": labels, "data": data, "label": "₹ per kg"}
    return render_template("price_estimator.html", values=values, errors=errors, result=result, chart=chart,
                           crops=P.known_crops(db), markets=P.known_markets(db), qualities=QUALITIES,
                           model=P.model_status(current_app.config["MODEL_DIR"]))


@bp.route("/nearby-farmers")
def nearby_farmers():
    db = get_db()
    a = request.args
    loc = get_location()
    qty = M._dec(a.get("quantity", "")) if a.get("quantity") else None
    max_price = M._dec(a.get("max_price", "")) if a.get("max_price") else None
    quality = a.get("quality") if a.get("quality") in QUALITIES else None
    rate = _rate(a.get("rate", current_app.config["DEFAULT_TRANSPORT_RATE"]))
    crop = a.get("crop", "").strip()[:60]
    results = M.rank_farmers(db, crop, qty, loc[:2] if loc else None, max_price, quality, rate)
    markers = M.group_by_farmer(results)
    return render_template("nearby_farmers.html", results=results, markers=markers, loc=loc, rate=rate, qty=qty,
                           f={"crop": crop, "quantity": a.get("quantity", ""), "max_price": a.get("max_price", ""),
                              "quality": quality or ""}, qualities=QUALITIES, presets=PRESET_LOCATIONS,
                           crops=P.known_crops(db),
                           map_data={"markers": markers,
                                     "user": {"lat": loc[0], "lng": loc[1], "label": loc[2]} if loc else None})


# ---- JSON API (used by the price estimator, the map and external demos) ----
@bp.route("/api/estimate")
def api_estimate():
    crop = request.args.get("crop", "").strip()
    if not crop:
        return jsonify(error="crop is required"), 400
    try:
        target = datetime.strptime(request.args.get("date") or date.today().isoformat(), "%Y-%m-%d").date()
        asking = to_decimal(request.args["asking"]) if request.args.get("asking") else None
    except Exception:
        return jsonify(error="invalid date or asking price"), 400
    r = P.estimate(get_db(), current_app.config["DATABASE"], current_app.config["MODEL_DIR"], crop,
                   request.args.get("market", ""), target, None, request.args.get("quality"), asking)
    out = {k: (str(v) if isinstance(v, (Decimal, date)) else v) for k, v in r.items()}
    return jsonify(out)


@bp.route("/api/farmers")
def api_farmers():
    a = request.args
    loc = None
    if valid_coords(a.get("lat"), a.get("lng")):
        loc = (float(a["lat"]), float(a["lng"]))
    qty = M._dec(a.get("quantity", "")) if a.get("quantity") else None
    rows = M.rank_farmers(get_db(), a.get("crop", "").strip()[:60], qty, loc, M._dec(a.get("max_price", "")) if a.get("max_price") else None,
                          a.get("quality"), _rate(a.get("rate")))
    return jsonify(markers=M.group_by_farmer(rows), count=len(rows))


@bp.route("/api/transport")
def api_transport():
    a = request.args
    if not (valid_coords(a.get("lat1"), a.get("lng1")) and valid_coords(a.get("lat2"), a.get("lng2"))):
        return jsonify(error="valid coordinates are required"), 400
    d = haversine_km(a["lat1"], a["lng1"], a["lat2"], a["lng2"])
    rate = _rate(a.get("rate"))
    return jsonify(distance_km=round(d, 2), rate_per_km=str(rate), estimated_transport_cost=str(transport_cost(d, rate)),
                   note="Straight-line distance and illustrative rate; not a delivery quote.")


@bp.route("/set-language", methods=["GET", "POST"])
def set_language():
    lang = (request.form.get("lang") or request.args.get("lang") or "").strip().lower()
    from services.i18n import SUPPORTED_LANGUAGES
    if lang in SUPPORTED_LANGUAGES:
        session["lang"] = lang
    next_url = request.form.get("next") or request.args.get("next") or request.referrer
    return redirect(safe_next(next_url) or url_for("main.index"))
