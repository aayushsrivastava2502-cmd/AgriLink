"""Transport Cost Optimization Blueprint:
Shared deliveries, route planning, group ordering pools, collection points, and cost comparison dashboard.
"""
import json
from decimal import Decimal

from flask import Blueprint, abort, current_app, flash, g, jsonify, redirect, render_template, request, url_for

from models import get_db, listing as L
from routes.helpers import get_location, login_required, role_required, safe_next
from services import transport_optimizer_service as TOS
from services.distance_service import PRESET_LOCATIONS, haversine_km, transport_cost, valid_coords
from services.money import q2, to_decimal

bp = Blueprint("transport", __name__, url_prefix="/transport-optimizer")


def _rate(raw=None):
    try:
        d = Decimal(str(raw).strip())
        return d if d.is_finite() and 0 <= d <= 1000 else Decimal(current_app.config["DEFAULT_TRANSPORT_RATE"])
    except Exception:
        return Decimal(current_app.config["DEFAULT_TRANSPORT_RATE"])


# ---------------------------------------------------------------------------
# 1. Transport Cost Optimization Dashboard
# ---------------------------------------------------------------------------

@bp.route("", strict_slashes=False)
@bp.route("/", strict_slashes=False)
def dashboard():
    db = get_db()
    rate = _rate(request.args.get("rate"))
    metrics = TOS.get_transport_overview_metrics(db, rate)
    recent_trips = TOS.list_shared_trips(db)[:4]
    active_pools = TOS.list_group_pools(db, status="open")[:4]
    hubs = TOS.list_collection_points(db)

    # Simulator defaults for interactive cost comparison
    sim_dist = float(request.args.get("sim_dist") or 15.0)
    sim_stops = int(request.args.get("sim_stops") or 3)
    sim_qty = float(request.args.get("sim_qty") or 60.0)

    # Separate deliveries: courier dispatches for each order from origin
    separate_sim_dist = sim_dist * sim_stops
    separate_sim_cost = transport_cost(separate_sim_dist, rate)

    # Shared delivery: optimized multi-stop route
    # Extra distance between clustered stops is approximately 2.5 km per additional stop
    shared_sim_dist = sim_dist + max(0, sim_stops - 1) * 3.0
    shared_sim_cost = transport_cost(shared_sim_dist, rate)
    sim_savings = q2(separate_sim_cost - shared_sim_cost)
    sim_savings_pct = round(float(sim_savings / separate_sim_cost * 100), 1) if separate_sim_cost > 0 else 0.0

    simulation = {
        "dist": sim_dist,
        "stops": sim_stops,
        "qty": sim_qty,
        "separate_dist": round(separate_sim_dist, 1),
        "separate_cost": separate_sim_cost,
        "shared_dist": round(shared_sim_dist, 1),
        "shared_cost": shared_sim_cost,
        "savings": sim_savings,
        "savings_pct": sim_savings_pct,
        "cost_per_order": q2(shared_sim_cost / Decimal(sim_stops)) if sim_stops > 0 else Decimal(0)
    }

    return render_template(
        "transport_dashboard.html",
        metrics=metrics,
        recent_trips=recent_trips,
        active_pools=active_pools,
        hubs=hubs,
        rate=rate,
        simulation=simulation,
        presets=PRESET_LOCATIONS
    )


# ---------------------------------------------------------------------------
# 2. Shared Delivery Trips
# ---------------------------------------------------------------------------

@bp.route("/shared-trips")
def list_shared_trips():
    db = get_db()
    user_id = g.user["id"] if g.user else None
    role = g.user["role"] if g.user else None
    filter_role = request.args.get("my")
    trips = TOS.list_shared_trips(db, user_id=user_id if filter_role else None, role=role if filter_role else None)
    return render_template("shared_trips_list.html", trips=trips, filter_role=filter_role)


@bp.route("/shared-trips/new", methods=["GET", "POST"])
@role_required("farmer")
def new_shared_trip():
    db = get_db()
    rate = _rate(request.args.get("rate") or request.form.get("rate"))
    method = request.form.get("allocation_method") or request.args.get("method") or "proportional_weight"
    dest_filter = request.args.get("dest", "").strip()

    eligible = TOS.find_eligible_orders_for_shared_trip(db, farmer_id=g.user["id"], destination_area=dest_filter)
    hubs = TOS.list_collection_points(db)

    proposal = None
    selected_ids = []

    if request.method == "POST":
        order_id_strs = request.form.getlist("order_ids")
        try:
            selected_ids = [int(x) for x in order_id_strs]
            if not selected_ids:
                flash("Select at least one order to group into a shared trip.", "error")
            else:
                cp_id = int(request.form["collection_point_id"]) if request.form.get("collection_point_id") else None
                notes = request.form.get("notes", "").strip()

                if request.form.get("action") == "confirm":
                    trip_id = TOS.create_and_persist_shared_trip(
                        db, g.user["id"], selected_ids, rate, method, cp_id, notes
                    )
                    flash("Shared transportation trip created successfully. Review the delivery route and cost allocations below.", "success")
                    return redirect(url_for("transport.trip_details", trip_id=trip_id))
                else:
                    proposal = TOS.calculate_shared_trip_proposal(
                        db, g.user["id"], selected_ids, rate, method, cp_id
                    )
        except Exception as exc:
            flash(str(exc), "error")

    return render_template(
        "shared_trip_form.html",
        eligible=eligible,
        hubs=hubs,
        rate=rate,
        method=method,
        proposal=proposal,
        selected_ids=selected_ids,
        dest_filter=dest_filter
    )


@bp.route("/shared-trips/<int:trip_id>")
def trip_details(trip_id):
    db = get_db()
    trip = TOS.get_shared_trip_details(db, trip_id)
    if not trip:
        abort(404)

    is_owner = bool(g.user and g.user["role"] == "farmer" and g.user["id"] == trip["farmer_id"])
    waypoints = [
        {"lat": trip["origin_lat"], "lng": trip["origin_lng"], "label": trip["origin_name"], "role": "origin"}
    ]
    for o in trip["orders"]:
        if o["delivery_lat"] and o["delivery_lng"]:
            waypoints.append({
                "lat": o["delivery_lat"],
                "lng": o["delivery_lng"],
                "label": f"Stop {o['stop_sequence']}: {o['buyer_name']} ({o['crop_name']})",
                "stop_num": o["stop_sequence"],
                "role": "stop"
            })

    return render_template(
        "shared_trip_detail.html",
        trip=trip,
        is_owner=is_owner,
        waypoints=waypoints
    )


@bp.route("/shared-trips/<int:trip_id>/status", methods=["POST"])
@role_required("farmer")
def update_trip_status(trip_id):
    db = get_db()
    new_status = request.form.get("status")
    try:
        TOS.update_shared_trip_status(db, trip_id, new_status, g.user["id"], g.user["role"])
        flash(f"Trip status updated to '{new_status.replace('_', ' ').title()}'.", "success")
    except Exception as exc:
        flash(str(exc), "error")
    return redirect(safe_next(request.form.get("back")) or url_for("transport.trip_details", trip_id=trip_id))


# ---------------------------------------------------------------------------
# 3. Group Ordering Pools
# ---------------------------------------------------------------------------

@bp.route("/group-pools")
def list_group_pools():
    db = get_db()
    crop = request.args.get("crop", "").strip()
    status = request.args.get("status", "").strip() or None
    pools = TOS.list_group_pools(db, crop=crop, status=status)
    return render_template("group_pools_list.html", pools=pools, crop=crop, status=status)


@bp.route("/group-pools/new", methods=["GET", "POST"])
@login_required
def new_group_pool():
    db = get_db()
    listing_id = request.args.get("listing", type=int) or request.form.get("listing_id", type=int)
    listing = L.get_listing(db, listing_id) if listing_id else None

    # Get active listings to choose from
    active_listings = [
        dict(r) for r in db.execute(
            "SELECT l.*, u.full_name AS farmer_name FROM crop_listings l JOIN users u ON u.id = l.farmer_id "
            "WHERE l.status = 'active' AND l.quantity_kg >= 25 ORDER BY l.created_at DESC"
        ).fetchall()
    ]

    loc = get_location()

    if request.method == "POST":
        sel_listing_id = request.form.get("listing_id", type=int)
        area = request.form.get("target_area", "").strip()
        lat_raw = request.form.get("target_lat", "").strip()
        lng_raw = request.form.get("target_lng", "").strip()
        min_kg = request.form.get("min_total_kg", "").strip()
        notes = request.form.get("notes", "").strip()

        errors = []
        if not sel_listing_id:
            errors.append("Select a crop listing.")
        if not area:
            errors.append("Enter the target delivery area or cluster.")
        if not (lat_raw and lng_raw and valid_coords(lat_raw, lng_raw)):
            errors.append("Enter valid coordinates for the delivery destination cluster.")
        try:
            min_kg_dec = Decimal(min_kg)
            if min_kg_dec <= 0:
                raise ValueError
        except Exception:
            errors.append("Minimum target quantity must be a positive number.")

        if not errors:
            try:
                pool_id = TOS.create_group_pool(
                    db, g.user["id"], sel_listing_id, area, float(lat_raw), float(lng_raw),
                    min_total_kg=min_kg_dec, notes=notes
                )
                flash("Group order pool created! Share it with nearby buyers to reach the bulk delivery threshold.", "success")
                return redirect(url_for("transport.pool_details", pool_id=pool_id))
            except Exception as exc:
                errors.append(str(exc))

        for e in errors:
            flash(e, "error")

    return render_template(
        "group_pool_new.html",
        listing=listing,
        active_listings=active_listings,
        presets=PRESET_LOCATIONS,
        loc=loc
    )


@bp.route("/group-pools/<int:pool_id>", methods=["GET", "POST"])
def pool_details(pool_id):
    db = get_db()
    pool = TOS.get_group_pool_details(db, pool_id)
    if not pool:
        abort(404)

    loc = get_location()
    is_farmer_or_creator = bool(
        g.user and (g.user["id"] == pool["farmer_id"] or g.user["id"] == pool["created_by_id"])
    )

    if request.method == "POST":
        if not g.user:
            flash("Please log in to pledge to this group order pool.", "info")
            return redirect(url_for("auth.login", next=request.path))
        if g.user["role"] != "buyer":
            flash("Only buyer accounts can pledge orders.", "error")
            return redirect(url_for("transport.pool_details", pool_id=pool_id))

        qty_raw = request.form.get("quantity_kg", "").strip()
        pref = request.form.get("delivery_preference", "delivery")
        addr = request.form.get("delivery_address", "").strip()
        lat_raw = request.form.get("dest_lat", "").strip()
        lng_raw = request.form.get("dest_lng", "").strip()

        try:
            qty = Decimal(qty_raw)
            if qty <= 0:
                raise ValueError("Quantity must be greater than zero.")
            dest_lat = float(lat_raw) if lat_raw and valid_coords(lat_raw, lng_raw) else pool["target_lat"]
            dest_lng = float(lng_raw) if lng_raw and valid_coords(lat_raw, lng_raw) else pool["target_lng"]

            TOS.join_group_pool(
                db, g.user["id"], pool_id, qty, pref, addr or pool["target_delivery_area"],
                dest_lat, dest_lng
            )
            flash(f"Successfully joined group pool for {qty:g} kg of {pool['crop_name']}!", "success")
            return redirect(url_for("transport.pool_details", pool_id=pool_id))
        except Exception as exc:
            flash(str(exc), "error")

    return render_template(
        "group_pool_detail.html",
        pool=pool,
        loc=loc,
        is_farmer_or_creator=is_farmer_or_creator
    )


@bp.route("/group-pools/<int:pool_id>/confirm", methods=["POST"])
@login_required
def confirm_group_pool(pool_id):
    db = get_db()
    try:
        TOS.confirm_group_pool(db, pool_id, g.user["id"])
        flash("Group order pool successfully confirmed! Customer order requests have been created and listing stock updated.", "success")
    except Exception as exc:
        flash(str(exc), "error")
    return redirect(url_for("transport.pool_details", pool_id=pool_id))


# ---------------------------------------------------------------------------
# 4. Collection Points & Hubs
# ---------------------------------------------------------------------------

@bp.route("/collection-points")
def collection_points():
    db = get_db()
    hubs = TOS.list_collection_points(db)
    selected_id = request.args.get("hub", type=int) or (hubs[0]["id"] if hubs else None)
    selected_hub = TOS.get_collection_point(db, selected_id) if selected_id else None
    nearby_crops = TOS.find_nearby_farmers_for_hub(db, selected_id) if selected_id else []

    loc = get_location()
    rate = _rate(request.args.get("rate"))

    comparison = None
    if selected_hub and loc and nearby_crops:
        first_crop = nearby_crops[0]
        comparison = TOS.compare_direct_vs_hub(
            (first_crop["latitude"], first_crop["longitude"]),
            (selected_hub["latitude"], selected_hub["longitude"]),
            (loc[0], loc[1]),
            rate,
            to_decimal(first_crop["quantity_kg"]),
            to_decimal(first_crop["price_per_kg"])
        )

    return render_template(
        "collection_points.html",
        hubs=hubs,
        selected_hub=selected_hub,
        nearby_crops=nearby_crops,
        loc=loc,
        rate=rate,
        comparison=comparison
    )


# ---------------------------------------------------------------------------
# 5. Interactive Route Planner
# ---------------------------------------------------------------------------

@bp.route("/route-planner")
def route_planner():
    db = get_db()
    rate = _rate(request.args.get("rate"))
    hubs = TOS.list_collection_points(db)

    # Preset candidate stops from farmers and collection points
    farmers = [
        dict(r) for r in db.execute(
            "SELECT l.crop_name, l.latitude, l.longitude, u.full_name AS farmer_name, u.city "
            "FROM crop_listings l JOIN users u ON u.id = l.farmer_id "
            "WHERE l.status = 'active' AND l.latitude IS NOT NULL"
        ).fetchall()
    ]

    # Pre-calculated default origin and stops for instant server-side rendering
    default_origin = {
        "name": hubs[0]["name"] if hubs else "Dadri Agro Logistics Hub",
        "lat": hubs[0]["latitude"] if hubs else 28.5530,
        "lng": hubs[0]["longitude"] if hubs else 77.5540
    }
    default_stops = [
        {"name": "Pari Chowk, Greater Noida", "lat": 28.4744, "lng": 77.5040},
        {"name": "Surajpur Commercial Area", "lat": 28.5133, "lng": 77.5177},
        {"name": "Sector 62, Noida", "lat": 28.6270, "lng": 77.3650}
    ]

    initial_calc = TOS.optimize_delivery_route(default_origin, default_stops)
    separate_cost = transport_cost(initial_calc["separate_distance_km"], rate)
    optimized_cost = transport_cost(initial_calc["optimized_distance_km"], rate)
    cost_saved = q2(max(Decimal(0), separate_cost - optimized_cost))

    initial_route = {
        **initial_calc,
        "rate_per_km": float(rate),
        "separate_cost": str(separate_cost),
        "optimized_cost": str(optimized_cost),
        "cost_saved": str(cost_saved)
    }

    return render_template(
        "route_planner.html",
        hubs=hubs,
        farmers=farmers,
        presets=PRESET_LOCATIONS,
        rate=rate,
        default_origin=default_origin,
        default_stops=default_stops,
        initial_route=initial_route,
        initial_route_json=json.dumps(initial_route)
    )


# ---------------------------------------------------------------------------
# 6. JSON APIs (Route optimization & Allocation Preview)
# ---------------------------------------------------------------------------

@bp.route("/api/route-optimize", methods=["POST"])
def api_route_optimize():
    data = request.get_json(force=True, silent=True) or {}
    origin = data.get("origin")
    stops = data.get("stops", [])
    if not origin or not valid_coords(origin.get("lat"), origin.get("lng")):
        return jsonify(error="Valid origin coordinates required."), 400

    res = TOS.optimize_delivery_route(origin, stops)
    rate = _rate(data.get("rate"))
    res["rate_per_km"] = str(rate)
    res["separate_cost"] = str(transport_cost(res["separate_distance_km"], rate))
    res["shared_cost"] = str(transport_cost(res["optimized_distance_km"], rate))
    res["cost_saved"] = str(q2(to_decimal(res["separate_cost"]) - to_decimal(res["shared_cost"])))
    return jsonify(res)


@bp.route("/api/allocation-preview", methods=["POST"])
def api_allocation_preview():
    data = request.get_json(force=True, silent=True) or {}
    total_cost = data.get("total_cost")
    orders = data.get("orders", [])
    method = data.get("method", "proportional_weight")
    if total_cost is None:
        return jsonify(error="total_cost required"), 400
    try:
        cost_dec = to_decimal(total_cost)
        allocated = TOS.allocate_shared_costs(cost_dec, orders, method)
        return jsonify(orders=allocated, total_cost=str(cost_dec), method=method)
    except Exception as exc:
        return jsonify(error=str(exc)), 400
