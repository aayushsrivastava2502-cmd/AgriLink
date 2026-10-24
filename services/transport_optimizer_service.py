"""Transport Cost Optimization service: nearby matching, shared delivery clustering,
greedy route optimization, transparent cost allocation, group order pooling, and collection points.
All money calculations use Python Decimal; amounts are in Indian Rupees (INR).
Distances are straight-line (Haversine) approximations unless otherwise noted.
"""
import math
import secrets
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Tuple

from models import transaction
from services.distance_service import EARTH_RADIUS_KM, haversine_km, transport_cost, delivered_cost, valid_coords
from services.money import q2, to_decimal, inr


def route_distance_km(points: List[Tuple[float, float]]) -> float:
    """Calculate the cumulative straight-line distance along a path of coordinates."""
    if not points or len(points) < 2:
        return 0.0
    total = 0.0
    for i in range(len(points) - 1):
        d = haversine_km(points[i][0], points[i][1], points[i + 1][0], points[i + 1][1])
        if d is not None:
            total += d
    return round(total, 2)


def optimize_delivery_route(origin: Dict, stops: List[Dict]) -> Dict:
    """Nearest Neighbour heuristic to arrange multiple delivery stops from an origin.

    Origin format: {'lat': float, 'lng': float, 'name': str}
    Stops format: list of {'id': any, 'lat': float, 'lng': float, 'name': str, ...}
    """
    if not stops:
        return {
            "origin": origin,
            "stops": [],
            "waypoints": [origin],
            "optimized_distance_km": 0.0,
            "unoptimized_distance_km": 0.0,
            "separate_distance_km": 0.0,
            "distance_saved_km": 0.0,
            "distance_saved_percent": 0.0,
            "is_straight_line": True,
            "routing_disclaimer": "Straight-line distance (Haversine approximation). Actual road distance is typically 20–30% longer."
        }

    valid_stops = [s for s in stops if valid_coords(s.get("lat"), s.get("lng"))]
    if len(valid_stops) <= 1:
        single_dist = haversine_km(origin["lat"], origin["lng"], valid_stops[0]["lat"], valid_stops[0]["lng"]) if valid_stops else 0.0
        dist = round(single_dist or 0.0, 2)
        waypoints = [
            {"lat": origin["lat"], "lng": origin["lng"], "label": origin.get("name", "Farm / Origin"), "role": "origin"}
        ] + [
            {"lat": s["lat"], "lng": s["lng"], "label": s.get("name", f"Stop {i+1}"), "stop_num": i + 1, "role": "stop", **{k: v for k, v in s.items() if k not in ("lat", "lng", "label", "stop_num", "role")}}
            for i, s in enumerate(valid_stops)
        ]
        return {
            "origin": origin,
            "stops": valid_stops,
            "waypoints": waypoints,
            "optimized_distance_km": dist,
            "unoptimized_distance_km": dist,
            "separate_distance_km": dist,
            "distance_saved_km": 0.0,
            "distance_saved_percent": 0.0,
            "is_straight_line": True,
            "routing_disclaimer": "Straight-line distance (Haversine approximation). Actual road distance is typically 20–30% longer."
        }

    # Calculate unoptimized distance (original order)
    unopt_points = [(origin["lat"], origin["lng"])] + [(s["lat"], s["lng"]) for s in valid_stops]
    unoptimized_distance = route_distance_km(unopt_points)

    # Calculate separate deliveries distance (individual direct one-way trips from origin)
    separate_distance = sum(
        haversine_km(origin["lat"], origin["lng"], s["lat"], s["lng"]) or 0.0
        for s in valid_stops
    )
    separate_distance = round(separate_distance, 2)

    # Nearest Neighbour TSP heuristic
    remaining = list(valid_stops)
    current_lat, current_lng = origin["lat"], origin["lng"]
    optimized_stops = []

    while remaining:
        best_idx = 0
        best_dist = float("inf")
        for i, s in enumerate(remaining):
            d = haversine_km(current_lat, current_lng, s["lat"], s["lng"])
            if d is not None and d < best_dist:
                best_dist = d
                best_idx = i
        chosen = remaining.pop(best_idx)
        optimized_stops.append(chosen)
        current_lat, current_lng = chosen["lat"], chosen["lng"]

    # Calculate optimized route distance
    opt_points = [(origin["lat"], origin["lng"])] + [(s["lat"], s["lng"]) for s in optimized_stops]
    optimized_distance = route_distance_km(opt_points)

    saved_km = round(max(0.0, separate_distance - optimized_distance), 2)
    saved_pct = round((saved_km / separate_distance * 100), 1) if separate_distance > 0 else 0.0

    waypoints = [
        {"lat": origin["lat"], "lng": origin["lng"], "label": origin.get("name", "Farm / Origin"), "role": "origin"}
    ] + [
        {"lat": s["lat"], "lng": s["lng"], "label": s.get("name", f"Stop {i+1}"), "stop_num": i + 1, "role": "stop"}
        for i, s in enumerate(optimized_stops)
    ]

    return {
        "origin": origin,
        "stops": optimized_stops,
        "waypoints": waypoints,
        "optimized_distance_km": optimized_distance,
        "unoptimized_distance_km": unoptimized_distance,
        "separate_distance_km": separate_distance,
        "distance_saved_km": saved_km,
        "distance_saved_percent": saved_pct,
        "is_straight_line": True,
        "routing_disclaimer": "Straight-line distance (Haversine approximation). Actual road distance is typically 20–30% longer depending on road geometry."
    }


def allocate_shared_costs(
    total_trip_cost: Decimal,
    items: List[Dict],
    method: str = "proportional_weight"
) -> List[Dict]:
    """Divide a shared transportation trip cost among participating orders.

    Supported methods:
      1. 'proportional_weight' (Default):
         Share_i = Total_Cost * (Quantity_i / Total_Quantity)
         Fair cargo-weight based allocation.

      2. 'proportional_standalone':
         Share_i = Total_Cost * (Standalone_Cost_i / Total_Standalone_Costs)
         Fair savings-distribution based on what each order would cost alone.

    Guarantees that the sum of allocated shares exactly matches total_trip_cost.
    """
    if not items:
        return []

    total_cost_dec = q2(total_trip_cost)
    total_qty = sum((to_decimal(it.get("quantity_kg", 0)) for it in items), Decimal(0))
    total_standalone = sum((to_decimal(it.get("individual_cost", 0)) for it in items), Decimal(0))

    allocated_items = []
    running_sum = Decimal(0)

    for it in items:
        qty = to_decimal(it.get("quantity_kg", 0))
        standalone = to_decimal(it.get("individual_cost", 0))

        if method == "proportional_standalone" and total_standalone > 0:
            share = q2(total_cost_dec * (standalone / total_standalone))
        elif total_qty > 0:
            share = q2(total_cost_dec * (qty / total_qty))
        else:
            share = q2(total_cost_dec / Decimal(len(items)))

        running_sum += share
        savings = q2(standalone - share)
        savings_pct = round(float((savings / standalone) * 100), 1) if standalone > 0 else 0.0

        allocated_items.append({
            **it,
            "allocated_cost": share,
            "savings": savings,
            "savings_percent": savings_pct
        })

    # Reconcile penny-rounding discrepancy on the largest item so exact equality holds
    diff = total_cost_dec - running_sum
    if diff != Decimal(0) and allocated_items:
        allocated_items[0]["allocated_cost"] = q2(allocated_items[0]["allocated_cost"] + diff)
        standalone = to_decimal(allocated_items[0].get("individual_cost", 0))
        allocated_items[0]["savings"] = q2(standalone - allocated_items[0]["allocated_cost"])
        allocated_items[0]["savings_percent"] = round(
            float((allocated_items[0]["savings"] / standalone) * 100), 1
        ) if standalone > 0 else 0.0

    return allocated_items


# ---------------------------------------------------------------------------
# Database Queries & Management: Collection Points
# ---------------------------------------------------------------------------

def list_collection_points(db, active_only: bool = True) -> List[Dict]:
    sql = "SELECT * FROM collection_points"
    if active_only:
        sql += " WHERE is_active = 1"
    sql += " ORDER BY city, name"
    return [dict(r) for r in db.execute(sql).fetchall()]


def get_collection_point(db, cp_id: int) -> Optional[Dict]:
    row = db.execute("SELECT * FROM collection_points WHERE id = ?", (cp_id,)).fetchone()
    return dict(row) if row else None


def find_nearby_farmers_for_hub(db, cp_id: int, max_dist_km: float = 30.0) -> List[Dict]:
    """Find active crop listings from farmers within range of a collection point."""
    hub = get_collection_point(db, cp_id)
    if not hub:
        return []
    listings = db.execute(
        "SELECT l.*, u.full_name AS farmer_name, u.phone AS farmer_phone, u.city AS farmer_city "
        "FROM crop_listings l JOIN users u ON u.id = l.farmer_id "
        "WHERE l.status = 'active' AND l.quantity_kg > 0 AND l.latitude IS NOT NULL"
    ).fetchall()

    results = []
    for l in listings:
        d = haversine_km(hub["latitude"], hub["longitude"], l["latitude"], l["longitude"])
        if d is not None and d <= max_dist_km:
            r = dict(l)
            r["distance_to_hub_km"] = round(d, 2)
            results.append(r)
    results.sort(key=lambda x: x["distance_to_hub_km"])
    return results


def compare_direct_vs_hub(
    farmer_coords: Tuple[float, float],
    hub_coords: Tuple[float, float],
    buyer_coords: Tuple[float, float],
    rate_per_km: Decimal,
    quantity_kg: Decimal,
    price_per_kg: Decimal
) -> Dict:
    """Compare direct farm-to-buyer delivery against collection-point hub delivery."""
    direct_dist = haversine_km(farmer_coords[0], farmer_coords[1], buyer_coords[0], buyer_coords[1]) or 0.0
    farm_to_hub = haversine_km(farmer_coords[0], farmer_coords[1], hub_coords[0], hub_coords[1]) or 0.0
    hub_to_buyer = haversine_km(hub_coords[0], hub_coords[1], buyer_coords[0], buyer_coords[1]) or 0.0

    direct_transport = transport_cost(direct_dist, rate_per_km)
    product_cost = q2(quantity_kg * price_per_kg)
    direct_delivered = delivered_cost(product_cost, direct_transport)

    # Consolidated hub trip: farmer leg is subsidized in bulk (e.g. 50% consolidation efficiency)
    farm_to_hub_cost = transport_cost(farm_to_hub, rate_per_km * Decimal("0.5"))
    hub_to_buyer_cost = transport_cost(hub_to_buyer, rate_per_km)
    hub_delivered = delivered_cost(product_cost, farm_to_hub_cost + hub_to_buyer_cost)
    hub_pickup_delivered = delivered_cost(product_cost, farm_to_hub_cost)  # Buyer collects at hub

    return {
        "direct_distance_km": round(direct_dist, 2),
        "direct_transport_cost": direct_transport,
        "direct_delivered_cost": direct_delivered,
        "farm_to_hub_km": round(farm_to_hub, 2),
        "hub_to_buyer_km": round(hub_to_buyer, 2),
        "hub_total_distance_km": round(farm_to_hub + hub_to_buyer, 2),
        "hub_transport_cost": q2(farm_to_hub_cost + hub_to_buyer_cost),
        "hub_delivered_cost": hub_delivered,
        "hub_pickup_delivered_cost": hub_pickup_delivered,
        "product_cost": product_cost
    }


# ---------------------------------------------------------------------------
# Database Queries & Management: Shared Transportation Trips
# ---------------------------------------------------------------------------

def find_eligible_orders_for_shared_trip(
    db,
    farmer_id: Optional[int] = None,
    destination_area: Optional[str] = None
) -> List[Dict]:
    """Find accepted or pending delivery orders not yet assigned to an active shared trip."""
    sql = (
        "SELECT o.*, b.full_name AS buyer_name, b.city AS buyer_city, b.phone AS buyer_phone, "
        "f.full_name AS farmer_name, f.city AS farmer_city, l.latitude AS farmer_lat, l.longitude AS farmer_lng "
        "FROM order_requests o "
        "JOIN users b ON b.id = o.buyer_id "
        "JOIN users f ON f.id = o.farmer_id "
        "LEFT JOIN crop_listings l ON l.id = o.listing_id "
        "WHERE o.delivery_preference = 'delivery' "
        "AND o.status IN ('pending', 'accepted') "
        "AND o.id NOT IN (SELECT order_id FROM shared_trip_orders) "
    )
    params = []
    if farmer_id:
        sql += " AND o.farmer_id = ?"
        params.append(farmer_id)
    if destination_area:
        sql += " AND (b.city LIKE ? OR o.delivery_address LIKE ?)"
        params.extend([f"%{destination_area}%", f"%{destination_area}%"])

    sql += " ORDER BY o.created_at DESC"
    return [dict(r) for r in db.execute(sql, params).fetchall()]


def calculate_shared_trip_proposal(
    db,
    farmer_id: int,
    order_ids: List[int],
    rate_per_km: Decimal,
    allocation_method: str = "proportional_weight",
    collection_point_id: Optional[int] = None
) -> Dict:
    """Calculate and return a proposed shared delivery trip without modifying orders."""
    if not order_ids:
        raise ValueError("At least one order must be selected for a shared trip.")

    # Retrieve farmer origin
    farmer = db.execute("SELECT * FROM users WHERE id = ?", (farmer_id,)).fetchone()
    if not farmer:
        raise ValueError("Farmer not found.")

    origin_name = f"{farmer['full_name']}'s Farm ({farmer['city']})"
    origin_lat, origin_lng = None, None

    # Check collection point origin or listing coordinates
    if collection_point_id:
        cp = get_collection_point(db, collection_point_id)
        if cp:
            origin_name = cp["name"]
            origin_lat, origin_lng = cp["latitude"], cp["longitude"]

    if origin_lat is None:
        f_listing = db.execute(
            "SELECT latitude, longitude FROM crop_listings WHERE farmer_id = ? AND latitude IS NOT NULL LIMIT 1",
            (farmer_id,)
        ).fetchone()
        if f_listing:
            origin_lat, origin_lng = f_listing["latitude"], f_listing["longitude"]
        else:
            # Fallback to Greater Noida coordinates if not set
            origin_lat, origin_lng = 28.4744, 77.5040

    # Retrieve selected orders
    placeholders = ",".join("?" for _ in order_ids)
    rows = db.execute(
        f"SELECT o.*, b.full_name AS buyer_name, b.city AS buyer_city, b.phone AS buyer_phone "
        f"FROM order_requests o JOIN users b ON b.id = o.buyer_id "
        f"WHERE o.id IN ({placeholders}) AND o.farmer_id = ?",
        order_ids + [farmer_id]
    ).fetchall()

    if len(rows) != len(order_ids):
        raise ValueError("Some selected orders do not exist or belong to a different farmer.")

    # Build stops
    stops = []
    for r in rows:
        lat = r["delivery_lat"] or 28.5355  # default nearby if unassigned
        lng = r["delivery_lng"] or 77.3910
        dist = haversine_km(origin_lat, origin_lng, lat, lng) or 5.0
        ind_cost = transport_cost(dist, rate_per_km)
        stops.append({
            "order_id": r["id"],
            "buyer_id": r["buyer_id"],
            "buyer_name": r["buyer_name"],
            "crop_name": r["crop_name"],
            "quantity_kg": r["quantity_kg"],
            "name": f"Order #{r['id']} ({r['buyer_name']})",
            "lat": lat,
            "lng": lng,
            "individual_distance_km": round(dist, 2),
            "individual_cost": ind_cost
        })

    origin_dict = {"name": origin_name, "lat": origin_lat, "lng": origin_lng}
    route_res = optimize_delivery_route(origin_dict, stops)

    shared_trip_cost = transport_cost(route_res["optimized_distance_km"], rate_per_km)
    separate_total_cost = sum((to_decimal(s["individual_cost"]) for s in stops), Decimal(0))
    total_savings = q2(separate_total_cost - shared_trip_cost)
    savings_pct = round(float(total_savings / separate_total_cost * 100), 1) if separate_total_cost > 0 else 0.0

    allocated_stops = allocate_shared_costs(shared_trip_cost, route_res["stops"], allocation_method)

    # Assign stop sequence indices
    for idx, s in enumerate(allocated_stops, start=1):
        s["stop_sequence"] = idx

    dest_area = rows[0]["buyer_city"] if rows else "Delivery Cluster"

    return {
        "farmer_id": farmer_id,
        "farmer_name": farmer["full_name"],
        "collection_point_id": collection_point_id,
        "origin_name": origin_name,
        "origin_lat": origin_lat,
        "origin_lng": origin_lng,
        "destination_area": dest_area,
        "rate_per_km": rate_per_km,
        "allocation_method": allocation_method,
        "total_distance_km": route_res["optimized_distance_km"],
        "separate_total_cost": separate_total_cost,
        "shared_total_cost": shared_trip_cost,
        "total_savings": total_savings,
        "savings_percent": savings_pct,
        "stops": allocated_stops,
        "waypoints": route_res["waypoints"],
        "is_straight_line": True,
        "routing_disclaimer": route_res["routing_disclaimer"]
    }


def create_and_persist_shared_trip(
    db,
    farmer_id: int,
    order_ids: List[int],
    rate_per_km: Decimal,
    allocation_method: str = "proportional_weight",
    collection_point_id: Optional[int] = None,
    notes: str = ""
) -> int:
    """Create a persistent shared delivery trip and register its order cost shares inside a transaction."""
    proposal = calculate_shared_trip_proposal(
        db, farmer_id, order_ids, rate_per_km, allocation_method, collection_point_id
    )

    trip_code = f"TRIP-{secrets.token_hex(4).upper()}"

    with transaction(db):
        cur = db.execute(
            "INSERT INTO shared_trips ("
            "trip_code, farmer_id, collection_point_id, origin_name, origin_lat, origin_lng, "
            "destination_area, status, rate_per_km, total_distance_km, separate_total_cost, "
            "shared_total_cost, total_savings, savings_percent, allocation_method, notes"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                trip_code, farmer_id, collection_point_id, proposal["origin_name"],
                proposal["origin_lat"], proposal["origin_lng"], proposal["destination_area"],
                "proposed", float(rate_per_km), float(proposal["total_distance_km"]),
                float(proposal["separate_total_cost"]), float(proposal["shared_total_cost"]),
                float(proposal["total_savings"]), float(proposal["savings_percent"]),
                allocation_method, notes
            )
        )
        trip_id = cur.lastrowid

        for s in proposal["stops"]:
            db.execute(
                "INSERT INTO shared_trip_orders ("
                "trip_id, order_id, stop_sequence, individual_distance_km, individual_cost, "
                "allocated_cost, savings, savings_percent"
                ") VALUES (?,?,?,?,?,?,?,?)",
                (
                    trip_id, s["order_id"], s["stop_sequence"], float(s["individual_distance_km"]),
                    float(s["individual_cost"]), float(s["allocated_cost"]),
                    float(s["savings"]), float(s["savings_percent"])
                )
            )

    return trip_id


def get_shared_trip_details(db, trip_id: int) -> Optional[Dict]:
    """Retrieve full details of a shared delivery trip, stops, and orders."""
    trip = db.execute("SELECT * FROM shared_trips WHERE id = ?", (trip_id,)).fetchone()
    if not trip:
        return None
    trip_dict = dict(trip)

    orders = db.execute(
        "SELECT sto.*, o.crop_name, o.quantity_kg, o.price_per_kg, o.product_cost, o.status AS order_status, "
        "b.full_name AS buyer_name, b.phone AS buyer_phone, b.city AS buyer_city, o.delivery_address, "
        "o.delivery_lat, o.delivery_lng "
        "FROM shared_trip_orders sto "
        "JOIN order_requests o ON o.id = sto.order_id "
        "JOIN users b ON b.id = o.buyer_id "
        "WHERE sto.trip_id = ? "
        "ORDER BY sto.stop_sequence ASC",
        (trip_id,)
    ).fetchall()

    trip_dict["orders"] = [dict(r) for r in orders]
    trip_dict["stops_count"] = len(orders)
    trip_dict["total_kg"] = sum(o["quantity_kg"] for o in trip_dict["orders"])
    return trip_dict


def update_shared_trip_status(db, trip_id: int, new_status: str, user_id: int, user_role: str) -> bool:
    """Transition shared trip status: proposed -> confirmed -> dispatched -> completed | cancelled."""
    allowed = ("proposed", "confirmed", "dispatched", "completed", "cancelled")
    if new_status not in allowed:
        raise ValueError(f"Invalid status {new_status}")

    trip = db.execute("SELECT * FROM shared_trips WHERE id = ?", (trip_id,)).fetchone()
    if not trip:
        return False
    if user_role != "farmer" or trip["farmer_id"] != user_id:
        raise PermissionError("Only the owning farmer can update this delivery trip.")

    db.execute(
        "UPDATE shared_trips SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (new_status, trip_id)
    )
    return True


def list_shared_trips(db, user_id: Optional[int] = None, role: Optional[str] = None) -> List[Dict]:
    sql = (
        "SELECT st.id, st.trip_code, st.farmer_id, st.collection_point_id, st.origin_name, "
        "st.origin_lat, st.origin_lng, st.destination_area, st.status, st.rate_per_km, "
        "st.total_distance_km, st.separate_total_cost, st.shared_total_cost, st.total_savings, "
        "st.savings_percent, st.allocation_method, st.notes, st.created_at, st.updated_at, "
        "MAX(f.full_name) AS farmer_name, COUNT(sto.id) AS order_count, "
        "COALESCE(SUM(o.quantity_kg), 0) AS total_kg "
        "FROM shared_trips st "
        "JOIN users f ON f.id = st.farmer_id "
        "LEFT JOIN shared_trip_orders sto ON sto.trip_id = st.id "
        "LEFT JOIN order_requests o ON o.id = sto.order_id "
    )
    params = []
    if role == "farmer" and user_id:
        sql += " WHERE st.farmer_id = ?"
        params.append(user_id)
    elif role == "buyer" and user_id:
        sql += " WHERE st.id IN (SELECT trip_id FROM shared_trip_orders WHERE order_id IN (SELECT id FROM order_requests WHERE buyer_id = ?))"
        params.append(user_id)

    sql += (
        " GROUP BY st.id, st.trip_code, st.farmer_id, st.collection_point_id, st.origin_name, "
        "st.origin_lat, st.origin_lng, st.destination_area, st.status, st.rate_per_km, "
        "st.total_distance_km, st.separate_total_cost, st.shared_total_cost, st.total_savings, "
        "st.savings_percent, st.allocation_method, st.notes, st.created_at, st.updated_at, "
        "f.full_name "
        "ORDER BY st.created_at DESC"
    )
    return [dict(r) for r in db.execute(sql, params).fetchall()]


# ---------------------------------------------------------------------------
# Database Queries & Management: Group Ordering Pools
# ---------------------------------------------------------------------------

def create_group_pool(
    db,
    user_id: int,
    listing_id: int,
    target_area: str,
    target_lat: float,
    target_lng: float,
    min_total_kg: Decimal = Decimal("50.0"),
    notes: str = ""
) -> int:
    """Create an open group ordering pool for a crop listing."""
    listing = db.execute("SELECT * FROM crop_listings WHERE id = ?", (listing_id,)).fetchone()
    if not listing or listing["status"] != "active":
        raise ValueError("Listing is not available for group ordering.")

    avail_qty = to_decimal(listing["quantity_kg"])
    if avail_qty < min_total_kg:
        raise ValueError(f"Listing has only {avail_qty:g} kg available, which is less than the pool target of {min_total_kg:g} kg.")

    pool_code = f"GRP-{listing['crop_name'][:4].upper()}-{secrets.token_hex(3).upper()}"

    cur = db.execute(
        "INSERT INTO group_order_pools ("
        "pool_code, listing_id, farmer_id, crop_name, price_per_kg, target_delivery_area, "
        "target_lat, target_lng, min_total_kg, current_total_kg, status, created_by_id, notes"
        ") VALUES (?,?,?,?,?,?,?,?,?,0.0,'open',?,?)",
        (
            pool_code, listing_id, listing["farmer_id"], listing["crop_name"],
            float(listing["price_per_kg"]), target_area.strip(), target_lat, target_lng,
            float(min_total_kg), user_id, notes.strip()
        )
    )
    return cur.lastrowid


def join_group_pool(
    db,
    buyer_id: int,
    pool_id: int,
    quantity_kg: Decimal,
    delivery_pref: str = "delivery",
    delivery_address: str = "",
    dest_lat: Optional[float] = None,
    dest_lng: Optional[float] = None
) -> int:
    """Add a buyer's order request pledge to an open group order pool."""
    pool = db.execute("SELECT * FROM group_order_pools WHERE id = ?", (pool_id,)).fetchone()
    if not pool:
        raise ValueError("Group pool not found.")
    if pool["status"] not in ("open", "target_reached"):
        raise ValueError(f"This group pool is {pool['status']} and no longer accepts pledges.")

    listing = db.execute("SELECT * FROM crop_listings WHERE id = ?", (pool["listing_id"],)).fetchone()
    if not listing or listing["status"] != "active":
        raise ValueError("The crop listing is no longer active.")

    curr_kg = to_decimal(pool["current_total_kg"])
    avail_kg = to_decimal(listing["quantity_kg"])
    new_total = curr_kg + quantity_kg

    if new_total > avail_kg:
        raise ValueError(f"Adding {quantity_kg:g} kg exceeds the farmer's remaining stock of {avail_kg:g} kg (current pledges: {curr_kg:g} kg).")

    with transaction(db):
        cur = db.execute(
            "INSERT INTO group_order_members ("
            "pool_id, buyer_id, quantity_kg, delivery_preference, delivery_address, dest_lat, dest_lng"
            ") VALUES (?,?,?,?,?,?,?)",
            (pool_id, buyer_id, float(quantity_kg), delivery_pref, delivery_address.strip(), dest_lat, dest_lng)
        )
        mem_id = cur.lastrowid

        new_status = "target_reached" if new_total >= to_decimal(pool["min_total_kg"]) else "open"
        db.execute(
            "UPDATE group_order_pools SET current_total_kg = ?, status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (float(new_total), new_status, pool_id)
        )

    return mem_id


def confirm_group_pool(db, pool_id: int, user_id: int) -> bool:
    """Convert a target-reached group pool into formal accepted orders and deduct stock atomically."""
    pool = db.execute("SELECT * FROM group_order_pools WHERE id = ?", (pool_id,)).fetchone()
    if not pool:
        raise ValueError("Group pool not found.")
    if pool["status"] not in ("open", "target_reached"):
        raise ValueError(f"Group pool cannot be confirmed from status '{pool['status']}'.")

    # Authorization: only the farmer or pool creator can confirm
    if user_id != pool["farmer_id"] and user_id != pool["created_by_id"]:
        raise PermissionError("Only the farmer or pool creator can confirm this group order.")

    members = db.execute(
        "SELECT * FROM group_order_members WHERE pool_id = ?", (pool_id,)
    ).fetchall()
    if not members:
        raise ValueError("No members have pledged to this group pool yet.")

    total_pledged = sum(to_decimal(m["quantity_kg"]) for m in members)
    if total_pledged < to_decimal(pool["min_total_kg"]):
        raise ValueError(f"Group pool has only reached {total_pledged:g} kg of its {pool['min_total_kg']:g} kg target.")

    with transaction(db):
        listing = db.execute("SELECT * FROM crop_listings WHERE id = ?", (pool["listing_id"],)).fetchone()
        if not listing or listing["status"] != "active":
            raise ValueError("The listing is no longer active.")

        remaining = to_decimal(listing["quantity_kg"]) - total_pledged
        if remaining < 0:
            raise ValueError("Insufficient stock remaining to fulfill this group pool.")

        # Create formal order_requests for all members
        for m in members:
            total_cost = q2(to_decimal(m["quantity_kg"]) * to_decimal(pool["price_per_kg"]))
            cur = db.execute(
                "INSERT INTO order_requests ("
                "listing_id, buyer_id, farmer_id, crop_name, price_per_kg, quantity_kg, product_cost, "
                "delivery_preference, message, status, delivery_address, delivery_lat, delivery_lng"
                ") VALUES (?,?,?,?,?,?,?,'delivery',?, 'accepted', ?,?,?)",
                (
                    pool["listing_id"], m["buyer_id"], pool["farmer_id"], pool["crop_name"],
                    float(pool["price_per_kg"]), float(m["quantity_kg"]), float(total_cost),
                    f"Group Order via Pool {pool['pool_code']}", m["delivery_address"],
                    m["dest_lat"], m["dest_lng"]
                )
            )
            order_id = cur.lastrowid
            db.execute("UPDATE group_order_members SET order_id = ? WHERE id = ?", (order_id, m["id"]))

        # Update listing stock
        db.execute(
            "UPDATE crop_listings SET quantity_kg = ?, status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (float(q2(remaining)), "sold_out" if remaining == 0 else "active", pool["listing_id"])
        )

        # Update pool status
        db.execute(
            "UPDATE group_order_pools SET status = 'confirmed', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (pool_id,)
        )

    return True


def get_group_pool_details(db, pool_id: int) -> Optional[Dict]:
    pool = db.execute(
        "SELECT p.*, l.category, l.quality, l.quantity_kg AS current_listing_stock, "
        "f.full_name AS farmer_name, f.city AS farmer_city, f.phone AS farmer_phone, "
        "u.full_name AS creator_name "
        "FROM group_order_pools p "
        "JOIN crop_listings l ON l.id = p.listing_id "
        "JOIN users f ON f.id = p.farmer_id "
        "JOIN users u ON u.id = p.created_by_id "
        "WHERE p.id = ?",
        (pool_id,)
    ).fetchone()
    if not pool:
        return None

    pool_dict = dict(pool)
    members = db.execute(
        "SELECT m.*, b.full_name AS buyer_name, b.city AS buyer_city "
        "FROM group_order_members m JOIN users b ON b.id = m.buyer_id "
        "WHERE m.pool_id = ? ORDER BY m.created_at ASC",
        (pool_id,)
    ).fetchall()
    pool_dict["members"] = [dict(r) for r in members]
    pool_dict["member_count"] = len(members)

    min_kg = pool_dict["min_total_kg"]
    curr_kg = pool_dict["current_total_kg"]
    pool_dict["progress_percent"] = min(100.0, round((curr_kg / min_kg * 100), 1)) if min_kg > 0 else 100.0

    # Calculate estimated bulk transport savings compared to separate individual trips
    rate = Decimal("12")  # illustrative rate
    sample_dist = 12.0  # approximate cluster distance
    separate_cost = len(members) * transport_cost(sample_dist, rate)
    shared_cost = transport_cost(sample_dist + len(members) * 2.0, rate)
    pool_dict["est_separate_transport"] = separate_cost
    pool_dict["est_shared_transport"] = shared_cost
    pool_dict["est_savings"] = q2(max(Decimal(0), separate_cost - shared_cost))

    return pool_dict


def list_group_pools(db, crop: Optional[str] = None, status: Optional[str] = None) -> List[Dict]:
    sql = (
        "SELECT p.id, p.pool_code, p.listing_id, p.farmer_id, p.crop_name, p.price_per_kg, "
        "p.target_delivery_area, p.target_lat, p.target_lng, p.min_total_kg, p.current_total_kg, "
        "p.status, p.created_by_id, p.notes, p.created_at, p.updated_at, "
        "MAX(f.full_name) AS farmer_name, COUNT(m.id) AS member_count "
        "FROM group_order_pools p "
        "JOIN users f ON f.id = p.farmer_id "
        "LEFT JOIN group_order_members m ON m.pool_id = p.id "
    )
    where, params = [], []
    if crop:
        where.append("p.crop_name LIKE ?")
        params.append(f"%{crop}%")
    if status:
        where.append("p.status = ?")
        params.append(status)

    if where:
        sql += " WHERE " + " AND ".join(where)

    sql += (
        " GROUP BY p.id, p.pool_code, p.listing_id, p.farmer_id, p.crop_name, p.price_per_kg, "
        "p.target_delivery_area, p.target_lat, p.target_lng, p.min_total_kg, p.current_total_kg, "
        "p.status, p.created_by_id, p.notes, p.created_at, p.updated_at, "
        "f.full_name "
        "ORDER BY p.created_at DESC"
    )
    rows = db.execute(sql, params).fetchall()
    res = []
    for r in rows:
        d = dict(r)
        min_kg = d["min_total_kg"]
        curr_kg = d["current_total_kg"]
        d["progress_percent"] = min(100.0, round((curr_kg / min_kg * 100), 1)) if min_kg > 0 else 100.0
        res.append(d)
    return res


# ---------------------------------------------------------------------------
# Overview Metrics for Cost Comparison Dashboard
# ---------------------------------------------------------------------------

def get_transport_overview_metrics(db, rate_per_km: Decimal = Decimal("12")) -> Dict:
    """Aggregate real database statistics for the Transport Cost Optimization dashboard."""
    trips = db.execute(
        "SELECT COUNT(*) AS n_trips, "
        "COALESCE(SUM(total_distance_km), 0) AS total_km, "
        "COALESCE(SUM(separate_total_cost), 0) AS sep_cost, "
        "COALESCE(SUM(shared_total_cost), 0) AS shared_cost, "
        "COALESCE(SUM(total_savings), 0) AS savings "
        "FROM shared_trips WHERE status IN ('proposed', 'confirmed', 'dispatched', 'completed')"
    ).fetchone()

    n_orders = db.execute("SELECT COUNT(*) FROM shared_trip_orders").fetchone()[0]
    total_kg_trips = db.execute(
        "SELECT COALESCE(SUM(o.quantity_kg), 0) "
        "FROM shared_trip_orders sto JOIN order_requests o ON o.id = sto.order_id"
    ).fetchone()[0]

    n_pools = db.execute("SELECT COUNT(*) FROM group_order_pools").fetchone()[0]
    n_hubs = db.execute("SELECT COUNT(*) FROM collection_points WHERE is_active = 1").fetchone()[0]

    sep_cost = to_decimal(trips["sep_cost"])
    shared_cost = to_decimal(trips["shared_cost"])
    savings = to_decimal(trips["savings"])
    savings_pct = round(float(savings / sep_cost * 100), 1) if sep_cost > 0 else 0.0

    return {
        "active_trips_count": trips["n_trips"],
        "consolidated_orders_count": n_orders,
        "total_kg_transported": round(float(total_kg_trips), 2),
        "total_distance_km": round(float(trips["total_km"]), 1),
        "separate_total_cost": q2(sep_cost),
        "shared_total_cost": q2(shared_cost),
        "total_savings": q2(savings),
        "average_savings_percent": savings_pct,
        "group_pools_count": n_pools,
        "collection_points_count": n_hubs,
        "rate_per_km": rate_per_km
    }
