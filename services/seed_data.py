"""Fictional demonstration data. Every name, price, location and order here is invented."""
from datetime import date, timedelta
from decimal import Decimal

from werkzeug.security import generate_password_hash

from models import listing as L, order as O, user as U
from .pricing_service import seed_market_references

DEMO_PASSWORD = "Demo@1234"

COLLECTION_POINTS = [
    ("Dadri Agro Logistics Hub", "GT Road, Dadri Mandi Area", "Dadri", "Uttar Pradesh", 28.5530, 77.5540, "Suresh Kumar", "9811001122", 8000, "06:00 AM - 08:00 PM"),
    ("Pari Chowk Consolidation Depot", "Surajpur-Kasna Road, Pari Chowk", "Greater Noida", "Uttar Pradesh", 28.4744, 77.5040, "Rajesh Verma", "9811001133", 10000, "05:30 AM - 09:00 PM"),
    ("Surajpur Farmers Market Center", "Main Road, Surajpur Industrial Area", "Surajpur", "Uttar Pradesh", 28.5133, 77.5177, "Vinod Singh", "9811001144", 6000, "06:00 AM - 07:30 PM"),
    ("Jewar Rural Produce Center", "Jewar Mandi Bypass", "Jewar", "Uttar Pradesh", 28.1270, 77.5570, "Praveen Sharma", "9811001155", 12000, "05:00 AM - 08:00 PM"),
]

FARMERS = [  # name, email, phone, city, state
    ("Ramesh Yadav (Demo)", "farmer1@demo.agrilink.test", "9000000001", "Dadri", "Uttar Pradesh"),
    ("Sunita Devi (Demo)", "farmer2@demo.agrilink.test", "9000000002", "Surajpur", "Uttar Pradesh"),
    ("Mahesh Chauhan (Demo)", "farmer3@demo.agrilink.test", "9000000003", "Jewar", "Uttar Pradesh"),
    ("Kiran Tomar (Demo)", "farmer4@demo.agrilink.test", "9000000004", "Dankaur", "Uttar Pradesh"),
    ("Anil Bhati (Demo)", "farmer5@demo.agrilink.test", "9000000005", "Kasna", "Uttar Pradesh"),
    ("Pooja Sharma (Demo)", "farmer6@demo.agrilink.test", "9000000006", "Greater Noida West", "Uttar Pradesh"),
]
BUYERS = [
    ("Aarav Gupta (Demo)", "buyer1@demo.agrilink.test", "9000000011", "Noida", "Uttar Pradesh"),
    ("Neha Singh (Demo)", "buyer2@demo.agrilink.test", "9000000012", "Greater Noida", "Uttar Pradesh"),
    ("Fresh Basket Kirana (Demo)", "buyer3@demo.agrilink.test", "9000000013", "Ghaziabad", "Uttar Pradesh"),
]
# farmer index, crop, category, qty kg, INR/kg (illustrative), quality, days since harvest, lat, lng, note
LISTINGS = [
    (0, "Wheat", "Cereals", 600, 27, "Standard", 12, 28.5560, 77.5520, "Sharbati variety, cleaned and bagged."),
    (0, "Mustard", "Oilseeds", 250, 60, "Premium", 20, 28.5560, 77.5520, "Good oil content, sun-dried."),
    (1, "Tomatoes", "Vegetables", 180, 22, "Standard", 2, 28.5190, 77.5120, "Picked this week, firm and red."),
    (1, "Cauliflower", "Vegetables", 120, 28, "Standard", 1, 28.5190, 77.5120, "Medium heads, harvested daily."),
    (1, "Green Peas", "Vegetables", 90, 55, "Premium", 3, 28.5190, 77.5120, "Tender pods, shelled on request."),
    (2, "Potatoes", "Vegetables", 800, 17, "Standard", 15, 28.1300, 77.5600, "Bulk lots available."),
    (2, "Onions", "Vegetables", 500, 23, "Standard", 18, 28.1300, 77.5600, "Dry, storage-grade onions."),
    (2, "Wheat", "Cereals", 1200, 25, "Basic", 25, 28.1300, 77.5600, "Mixed grade, good for flour milling."),
    (3, "Rice", "Cereals", 700, 39, "Premium", 30, 28.3650, 77.5500, "Long-grain, aged."),
    (3, "Tomatoes", "Vegetables", 250, 24, "Premium", 2, 28.3650, 77.5500, "Uniform size, ideal for retail."),
    (3, "Mustard", "Oilseeds", 400, 57, "Standard", 22, 28.3650, 77.5500, "Clean seed."),
    (4, "Onions", "Vegetables", 350, 26, "Premium", 10, 28.4300, 77.4800, "Large bulbs."),
    (4, "Potatoes", "Vegetables", 300, 19, "Premium", 8, 28.4300, 77.4800, "Washed, table-quality."),
    (4, "Green Peas", "Vegetables", 150, 52, "Standard", 4, 28.4300, 77.4800, "Fresh in pods."),
    (5, "Cauliflower", "Vegetables", 200, 30, "Premium", 1, 28.4650, 77.4300, "Tight white curds."),
    (5, "Rice", "Cereals", 400, 36, "Standard", 28, 28.4650, 77.4300, "Everyday table rice."),
    (5, "Tomatoes", "Vegetables", 100, 21, "Basic", 3, 28.4650, 77.4300, "Good for sauces and cooking."),
]
# buyer idx, listing idx, qty, delivery, message, action
ORDERS = [
    (0, 2, 10, "pickup", "Can I collect on Saturday morning?", "pending"),
    (1, 9, 20, "delivery", "Please deliver to Greater Noida.", "accept"),
    (2, 5, 100, "delivery", "Weekly supply for my shop.", "complete"),
    (0, 8, 15, "pickup", "", "reject"),
    (1, 3, 5, "pickup", "Changed my plan.", "cancel"),
    (2, 6, 60, "pickup", "Will pick up with my own tempo.", "pending"),
]


def seed_collection_points(db):
    """Seed fixed collection points if they do not exist."""
    existing = {r[0] for r in db.execute("SELECT name FROM collection_points").fetchall()}
    for name, addr, city, state, lat, lng, contact, phone, cap, hours in COLLECTION_POINTS:
        if name not in existing:
            db.execute(
                "INSERT INTO collection_points (name, address, city, state, latitude, longitude, contact_person, contact_phone, capacity_kg, operating_hours) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (name, addr, city, state, lat, lng, contact, phone, cap, hours)
            )


def seed(db):
    """Populate an empty database. Safe to call repeatedly (does nothing if users exist)."""
    seed_collection_points(db)
    if db.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
        return False
    pw_hash = generate_password_hash(DEMO_PASSWORD)  # hash once; all demo accounts share the password
    fids, bids = [], []
    for group, role, ids in ((FARMERS, "farmer", fids), (BUYERS, "buyer", bids)):
        for name, email, phone, city, state in group:
            clean = dict(full_name=name, email=email, phone=phone, role=role, city=city, state=state)
            ids.append(U.create_user(db, clean, None, is_demo=True, password_hash=pw_hash))
    lids = []
    today = date.today()
    for fi, crop, cat, qty, price, quality, days, lat, lng, note in LISTINGS:
        farmer = FARMERS[fi]
        clean = dict(crop_name=crop, category=cat, quantity_kg=Decimal(qty), price_per_kg=Decimal(price),
                     quality=quality, harvest_date=(today - timedelta(days=days)).isoformat(), city=farmer[3],
                     state=farmer[4], latitude=lat, longitude=lng, description=note + " (Demonstration listing)",
                     image_url="")
        lids.append(L.create_listing(db, fids[fi], clean, None, is_demo=True))

    # Buyer default delivery locations
    buyer_locs = [
        ("Sector 62, Noida", 28.6270, 77.3650),
        ("Pari Chowk, Greater Noida", 28.4744, 77.5040),
        ("Main Market, Ghaziabad", 28.6692, 77.4538),
    ]

    created_orders = []
    for bi, li, qty, delivery, msg, action in ORDERS:
        b_loc = buyer_locs[bi]
        clean_ord = dict(
            quantity_kg=Decimal(qty),
            delivery_preference=delivery,
            message=msg,
            delivery_address=b_loc[0] if delivery == "delivery" else "",
            delivery_lat=b_loc[1] if delivery == "delivery" else None,
            delivery_lng=b_loc[2] if delivery == "delivery" else None
        )
        oid = O.create_order(db, bids[bi], lids[li], clean_ord, is_demo=True)
        created_orders.append((oid, bi, li, action))
        farmer_id = fids[LISTINGS[li][0]]
        if action == "accept":
            O.accept(db, oid, farmer_id)
        elif action == "complete":
            O.accept(db, oid, farmer_id); O.complete(db, oid, farmer_id)
        elif action == "reject":
            O.reject(db, oid, farmer_id)
        elif action == "cancel":
            O.cancel(db, oid, bids[bi])

    # Seed an eligible pair of orders and a demonstration shared trip for Farmer Kiran Tomar (farmer4, index 3)
    kiran_id = fids[3]
    kiran_tomato_lid = lids[9]  # Tomatoes, 250 kg
    o_trip1 = O.create_order(db, bids[0], kiran_tomato_lid, dict(
        quantity_kg=Decimal("35"), delivery_preference="delivery", message="Deliver with shared truck please",
        delivery_address="Sector 62, Noida", delivery_lat=28.6270, delivery_lng=77.3650
    ), is_demo=True)
    O.accept(db, o_trip1, kiran_id)

    o_trip2 = O.create_order(db, bids[1], kiran_tomato_lid, dict(
        quantity_kg=Decimal("25"), delivery_preference="delivery", message="Morning delivery preferred",
        delivery_address="Pari Chowk, Greater Noida", delivery_lat=28.4744, delivery_lng=77.5040
    ), is_demo=True)
    O.accept(db, o_trip2, kiran_id)

    try:
        from services.transport_optimizer_service import create_and_persist_shared_trip
        create_and_persist_shared_trip(
            db, kiran_id, [o_trip1, o_trip2], Decimal("12"),
            allocation_method="proportional_weight",
            notes="Demonstration shared trip consolidating Noida and Greater Noida tomato orders."
        )
    except Exception:
        pass

    # Seed an open demonstration group order pool for Wheat in Greater Noida
    try:
        from services.transport_optimizer_service import create_group_pool, join_group_pool
        pool_id = create_group_pool(
            db, bids[0], lids[0], "Greater Noida (Pari Chowk area)",
            28.4744, 77.5040, min_total_kg=Decimal("150.0"),
            notes="Bulk Sharbati Wheat procurement pool for Greater Noida residential society."
        )
        join_group_pool(
            db, bids[0], pool_id, Decimal("50.0"), "delivery",
            "Pari Chowk, Greater Noida", 28.4744, 77.5040
        )
        join_group_pool(
            db, bids[1], pool_id, Decimal("40.0"), "delivery",
            "Surajpur Commercial Area", 28.5133, 77.5177
        )
    except Exception:
        pass

    seed_market_references(db)
    return True
