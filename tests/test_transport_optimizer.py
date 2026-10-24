"""Unit and integration tests for the Transport Cost Optimization module:
Nearby matching, shared delivery clustering, greedy route planning, transparent cost allocation,
group order pooling, and collection point hubs.

Run with:  python -m unittest discover -s tests -v
"""
import os
import shutil
import tempfile
import unittest
from datetime import date
from decimal import Decimal

from app import create_app
from services import transport_optimizer_service as TOS
from services.distance_service import haversine_km, transport_cost
from services.money import q2, to_decimal, inr

PW = "Demo@1234"


class TransportOptimizerBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = {
            "DATABASE": os.path.join(self.tmp, "test_transport.db"),
            "MODEL_DIR": os.path.join(self.tmp, "model"),
            "UPLOAD_FOLDER": os.path.join(self.tmp, "up"),
            "TESTING": True,
            "AUTO_SEED": True
        }
        self.app = create_app(self.cfg)
        self.c = self.app.test_client()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def post(self, url, data=None, client=None, **kw):
        c = client or self.c
        with c.session_transaction() as s:
            tok = s.setdefault("_csrf", "test-token")
        d = dict(data or {})
        d["_csrf"] = tok
        return c.post(url, data=d, **kw)

    def login(self, email, client=None):
        r = self.post("/login", {"email": email, "password": PW}, client=client)
        self.assertEqual(r.status_code, 302)

    def client_for(self, email):
        c = self.app.test_client()
        self.login(email, c)
        return c


class RouteOptimizationAndDistanceTests(TransportOptimizerBase):
    def test_haversine_and_route_distance(self):
        # Pari Chowk (28.4744, 77.5040) to Dadri (28.5530, 77.5540) is ~10 km
        d = haversine_km(28.4744, 77.5040, 28.5530, 77.5540)
        self.assertAlmostEqual(d, 10.0, delta=1.0)

        # Route distance cumulative
        points = [(28.4744, 77.5040), (28.5133, 77.5177), (28.5530, 77.5540)]
        dist = TOS.route_distance_km(points)
        self.assertGreater(dist, 9.0)
        self.assertLess(dist, 13.0)

    def test_nearest_neighbour_route_optimizer(self):
        origin = {"name": "Dadri Farm", "lat": 28.5530, "lng": 77.5540}
        # Stop A is Surajpur (~5.8 km), Stop B is Sector 62 Noida (~20 km), Stop C is Pari Chowk (~10 km)
        stops = [
            {"id": "B", "name": "Noida Sec 62", "lat": 28.6270, "lng": 77.3650},
            {"id": "A", "name": "Surajpur", "lat": 28.5133, "lng": 77.5177},
            {"id": "C", "name": "Pari Chowk", "lat": 28.4744, "lng": 77.5040}
        ]
        res = TOS.optimize_delivery_route(origin, stops)
        self.assertEqual(len(res["stops"]), 3)
        # Nearest neighbour from Dadri visits Surajpur first, then Pari Chowk, then Noida
        self.assertEqual(res["stops"][0]["id"], "A")
        # Optimized route should save significant distance over separate individual roundtrips
        self.assertLess(res["optimized_distance_km"], res["separate_distance_km"])
        self.assertGreater(res["distance_saved_km"], 0)
        self.assertTrue(res["is_straight_line"])
        self.assertIn("Straight-line", res["routing_disclaimer"])

    def test_missing_coordinates_handling(self):
        origin = {"name": "Test Origin", "lat": 28.5530, "lng": 77.5540}
        stops_with_missing = [
            {"id": 1, "name": "Valid Stop", "lat": 28.5133, "lng": 77.5177},
            {"id": 2, "name": "Invalid Stop", "lat": None, "lng": "invalid"}
        ]
        res = TOS.optimize_delivery_route(origin, stops_with_missing)
        # Should gracefully drop invalid coords without crashing
        self.assertEqual(len(res["stops"]), 1)
        self.assertEqual(res["stops"][0]["id"], 1)


class CostAllocationTests(unittest.TestCase):
    def test_proportional_weight_allocation(self):
        total_trip_cost = Decimal("210.00")
        items = [
            {"order_id": 1, "quantity_kg": 40, "individual_cost": Decimal("180.00")},
            {"order_id": 2, "quantity_kg": 20, "individual_cost": Decimal("120.00")},
        ]
        allocated = TOS.allocate_shared_costs(total_trip_cost, items, method="proportional_weight")
        # 40 kg out of 60 kg = 2/3 of 210 = 140; 20 kg = 1/3 of 210 = 70
        self.assertEqual(allocated[0]["allocated_cost"], Decimal("140.00"))
        self.assertEqual(allocated[1]["allocated_cost"], Decimal("70.00"))
        # Sum of shares must exactly equal total trip cost
        sum_shares = sum(it["allocated_cost"] for it in allocated)
        self.assertEqual(sum_shares, total_trip_cost)
        # Both buyers save money compared to standalone
        self.assertLess(allocated[0]["allocated_cost"], items[0]["individual_cost"])
        self.assertLess(allocated[1]["allocated_cost"], items[1]["individual_cost"])

    def test_proportional_standalone_allocation(self):
        total_trip_cost = Decimal("240.00")
        items = [
            {"order_id": 1, "quantity_kg": 50, "individual_cost": Decimal("200.00")},
            {"order_id": 2, "quantity_kg": 10, "individual_cost": Decimal("100.00")},
        ]
        allocated = TOS.allocate_shared_costs(total_trip_cost, items, method="proportional_standalone")
        sum_shares = sum(it["allocated_cost"] for it in allocated)
        self.assertEqual(sum_shares, total_trip_cost)
        self.assertEqual(allocated[0]["allocated_cost"], Decimal("160.00"))
        self.assertEqual(allocated[1]["allocated_cost"], Decimal("80.00"))


class SharedTransportationWorkflowTests(TransportOptimizerBase):
    def test_shared_trip_lifecycle(self):
        farmer_client = self.client_for("farmer4@demo.agrilink.test")
        buyer_client = self.client_for("buyer1@demo.agrilink.test")

        # 1. Check dashboard renders transport overview metrics
        r = self.c.get("/transport-optimizer")
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertIn("Transport Cost Optimizer", html)
        self.assertIn("Estimated Shared Savings", html)
        self.assertIn("₹", html)

        # 2. Check proposed trips list
        r = self.c.get("/transport-optimizer/shared-trips")
        self.assertEqual(r.status_code, 200)

        # 3. Create two new eligible delivery orders for farmer 4
        with self.app.app_context():
            from models import get_db, order as O
            db = get_db()
            lid = db.execute("SELECT id FROM crop_listings WHERE farmer_id = 4 LIMIT 1").fetchone()[0]
            o1 = O.create_order(db, 7, lid, {
                "quantity_kg": Decimal("15"), "delivery_preference": "delivery",
                "delivery_address": "Pari Chowk", "delivery_lat": 28.4744, "delivery_lng": 77.5040
            })
            o2 = O.create_order(db, 8, lid, {
                "quantity_kg": Decimal("25"), "delivery_preference": "delivery",
                "delivery_address": "Surajpur", "delivery_lat": 28.5133, "delivery_lng": 77.5177
            })
            eligible = TOS.find_eligible_orders_for_shared_trip(db, farmer_id=4)
            self.assertGreaterEqual(len(eligible), 2)
            sel_ids = [o1, o2]
            trip_id = TOS.create_and_persist_shared_trip(
                db, 4, sel_ids, Decimal("12"),
                allocation_method="proportional_weight",
                notes="Automated test shared trip"
            )

        # 4. View trip detail
        r = self.c.get(f"/transport-optimizer/shared-trips/{trip_id}")
        self.assertEqual(r.status_code, 200)
        detail_html = r.get_data(as_text=True)
        self.assertIn("Shared Trip:", detail_html)
        self.assertIn("Participating Orders & Cost Allocation", detail_html)

        # 5. Farmer transitions trip: proposed -> confirmed -> dispatched -> completed
        r = self.post(f"/transport-optimizer/shared-trips/{trip_id}/status", {"status": "confirmed"}, client=farmer_client)
        self.assertEqual(r.status_code, 302)
        with self.app.app_context():
            trip = TOS.get_shared_trip_details(get_db(), trip_id)
            self.assertEqual(trip["status"], "confirmed")

        # Unauthorized transition by buyer must be rejected
        r = self.post(f"/transport-optimizer/shared-trips/{trip_id}/status", {"status": "dispatched"}, client=buyer_client)
        self.assertEqual(r.status_code, 403)


class GroupOrderingPoolTests(TransportOptimizerBase):
    def test_group_pool_creation_joining_and_confirmation(self):
        farmer_client = self.client_for("farmer1@demo.agrilink.test")
        buyer1_client = self.client_for("buyer1@demo.agrilink.test")
        buyer2_client = self.client_for("buyer2@demo.agrilink.test")

        # 1. Create a group pool for listing 1 (Wheat, 600 kg) with target 80 kg
        r = self.post("/transport-optimizer/group-pools/new", {
            "listing_id": 1,
            "target_area": "Pari Chowk, Greater Noida",
            "target_lat": "28.4744",
            "target_lng": "77.5040",
            "min_total_kg": "80",
            "notes": "Society wheat pool"
        }, client=buyer1_client)
        self.assertEqual(r.status_code, 302)

        with self.app.app_context():
            from models import get_db
            db = get_db()
            pool_row = db.execute("SELECT id, min_total_kg, current_total_kg, status FROM group_order_pools ORDER BY id DESC LIMIT 1").fetchone()
            pool_id = pool_row["id"]
            self.assertEqual(pool_row["status"], "open")
            self.assertEqual(pool_row["min_total_kg"], 80.0)

        # 2. Buyer 1 pledges 50 kg
        r = self.post(f"/transport-optimizer/group-pools/{pool_id}", {
            "quantity_kg": "50",
            "delivery_preference": "delivery",
            "delivery_address": "Tower A, Pari Chowk"
        }, client=buyer1_client)
        self.assertEqual(r.status_code, 302)

        with self.app.app_context():
            pool = TOS.get_group_pool_details(get_db(), pool_id)
            self.assertEqual(pool["current_total_kg"], 50.0)
            self.assertEqual(pool["status"], "open")  # Not yet reached target

        # 3. Confirming prematurely must fail
        with self.app.app_context():
            with self.assertRaises(ValueError):
                TOS.confirm_group_pool(get_db(), pool_id, user_id=1)

        # 4. Buyer 2 pledges 35 kg -> total = 85 kg >= 80 kg target
        r = self.post(f"/transport-optimizer/group-pools/{pool_id}", {
            "quantity_kg": "35",
            "delivery_preference": "delivery",
            "delivery_address": "Tower B, Pari Chowk"
        }, client=buyer2_client)
        self.assertEqual(r.status_code, 302)

        with self.app.app_context():
            pool = TOS.get_group_pool_details(get_db(), pool_id)
            self.assertEqual(pool["current_total_kg"], 85.0)
            self.assertEqual(pool["status"], "target_reached")

        # 5. Farmer confirms group pool -> creates formal accepted orders & deducts stock
        r = self.post(f"/transport-optimizer/group-pools/{pool_id}/confirm", client=farmer_client)
        self.assertEqual(r.status_code, 302)

        with self.app.app_context():
            db = get_db()
            pool = TOS.get_group_pool_details(db, pool_id)
            self.assertEqual(pool["status"], "confirmed")
            # Listing stock must be reduced by 85 kg (from 600 kg to 515 kg)
            stock = db.execute("SELECT quantity_kg FROM crop_listings WHERE id = 1").fetchone()[0]
            self.assertEqual(stock, 515.0)
            # Both members must have linked formal accepted order_requests
            for m in pool["members"]:
                self.assertIsNotNone(m["order_id"])
                ord_status = db.execute("SELECT status FROM order_requests WHERE id = ?", (m["order_id"],)).fetchone()[0]
                self.assertEqual(ord_status, "accepted")


class CollectionPointAndApiTests(TransportOptimizerBase):
    def test_collection_points_seeded_and_queryable(self):
        r = self.c.get("/transport-optimizer/collection-points")
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertIn("Dadri Agro Logistics Hub", html)
        self.assertIn("Pari Chowk Consolidation Depot", html)
        self.assertIn("Active Produce Available Near", html)

    def test_direct_vs_hub_comparison(self):
        farmer_coords = (28.5560, 77.5520)  # Dadri farm
        hub_coords = (28.5530, 77.5540)     # Dadri hub
        buyer_coords = (28.6270, 77.3650)   # Noida buyer
        rate = Decimal("12")
        qty = Decimal("100")
        price = Decimal("25")

        cmp_res = TOS.compare_direct_vs_hub(farmer_coords, hub_coords, buyer_coords, rate, qty, price)
        self.assertIn("direct_delivered_cost", cmp_res)
        self.assertIn("hub_delivered_cost", cmp_res)
        self.assertIn("hub_pickup_delivered_cost", cmp_res)
        # Buyer pickup at hub should be cheaper than direct delivery
        self.assertLess(cmp_res["hub_pickup_delivered_cost"], cmp_res["direct_delivered_cost"])

    def test_api_route_optimize(self):
        payload = {
            "origin": {"name": "Test Farm", "lat": 28.55, "lng": 77.55},
            "stops": [
                {"name": "Stop 1", "lat": 28.62, "lng": 77.36},
                {"name": "Stop 2", "lat": 28.47, "lng": 77.50}
            ],
            "rate": "15"
        }
        r = self.c.post("/transport-optimizer/api/route-optimize", json=payload)
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("optimized_distance_km", data)
        self.assertIn("separate_distance_km", data)
        self.assertEqual(data["rate_per_km"], "15")
        self.assertIn("cost_saved", data)
        self.assertIn("waypoints", data)
        # Mathematical integrity: distance saved = max(0.0, separate - optimized)
        calc_saved = round(max(0.0, data["separate_distance_km"] - data["optimized_distance_km"]), 2)
        self.assertAlmostEqual(data["distance_saved_km"], calc_saved, places=2)

    def test_route_planner_page_and_csrf(self):
        # 1. GET route planner page
        r = self.c.get("/transport-optimizer/route-planner")
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertIn("Delivery Route Planner", html)
        self.assertIn('id="planner-map"', html)
        self.assertIn('id="planner-map-fallback"', html)
        self.assertIn('id="stops-list"', html)
        self.assertIn('id="btn-optimize"', html)
        self.assertIn('leaflet.js', html)
        self.assertIn('leaflet.css', html)

        # 2. Get CSRF token established by GET
        with self.c.session_transaction() as s:
            csrf_tok = s.get("_csrf")
        self.assertTrue(bool(csrf_tok))

        # 3. POST with X-CSRF-Token header
        payload = {
            "origin": {"name": "Dadri", "lat": 28.553, "lng": 77.554},
            "stops": [
                {"name": "Pari Chowk", "lat": 28.4744, "lng": 77.5040},
                {"name": "Surajpur", "lat": 28.5133, "lng": 77.5177}
            ],
            "rate": 12
        }
        r2 = self.c.post(
            "/transport-optimizer/api/route-optimize",
            json=payload,
            headers={"X-CSRF-Token": csrf_tok}
        )
        self.assertEqual(r2.status_code, 200)
        res = r2.get_json()
        self.assertEqual(len(res["waypoints"]), 3)
        self.assertGreater(float(res["cost_saved"]), 0)

        # 4. POST with _csrf in JSON payload
        payload_with_csrf = dict(payload)
        payload_with_csrf["_csrf"] = csrf_tok
        r3 = self.c.post("/transport-optimizer/api/route-optimize", json=payload_with_csrf)
        self.assertEqual(r3.status_code, 200)

        # 5. Invalid origin coordinates rejected with 400
        bad_payload = {"origin": {"name": "Bad", "lat": "bad", "lng": 77.5}, "stops": []}
        r4 = self.c.post(
            "/transport-optimizer/api/route-optimize",
            json=bad_payload,
            headers={"X-CSRF-Token": csrf_tok}
        )
        self.assertEqual(r4.status_code, 400)
        self.assertIn("error", r4.get_json())

    def test_api_allocation_preview(self):
        payload = {
            "total_cost": "500",
            "orders": [
                {"order_id": 1, "quantity_kg": 60, "individual_cost": 300},
                {"order_id": 2, "quantity_kg": 40, "individual_cost": 200}
            ],
            "method": "proportional_weight"
        }
        r = self.c.post("/transport-optimizer/api/allocation-preview", json=payload)
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        orders = data["orders"]
        self.assertEqual(Decimal(orders[0]["allocated_cost"]), Decimal("300.00"))
        self.assertEqual(Decimal(orders[1]["allocated_cost"]), Decimal("200.00"))


if __name__ == "__main__":
    unittest.main()
