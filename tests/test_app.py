"""Run with:  python -m unittest discover -s tests -v"""
import io
import json
import os
import pathlib
import re
import shutil
import sqlite3
import tempfile
import unittest
from datetime import date
from decimal import Decimal

from app import create_app
from ml import make_sample_dataset
from ml.train_model import InsufficientData, train
from services import money, pricing_service as P
from services.distance_service import delivered_cost, haversine_km, transport_cost, valid_coords

PW = "Demo@1234"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = {"DATABASE": os.path.join(self.tmp, "t.db"), "MODEL_DIR": os.path.join(self.tmp, "model"),
                    "UPLOAD_FOLDER": os.path.join(self.tmp, "up"), "TESTING": True}
        self.app = create_app(self.cfg)
        self.c = self.app.test_client()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def post(self, url, data=None, client=None, **kw):
        c = client or self.c
        with c.session_transaction() as s:
            tok = s.setdefault("_csrf", "test-token")
        d = dict(data or {}); d["_csrf"] = tok
        return c.post(url, data=d, **kw)

    def login(self, email, client=None):
        r = self.post("/login", {"email": email, "password": PW}, client=client)
        self.assertEqual(r.status_code, 302, r.get_data(as_text=True)[:300])

    def client_for(self, email):
        c = self.app.test_client(); self.login(email, c); return c

    def sql(self, q, *a):
        conn = sqlite3.connect(self.cfg["DATABASE"]); conn.row_factory = sqlite3.Row
        try:
            return conn.execute(q, a).fetchall()
        finally:
            conn.close()

    def listing_form(self, **o):
        d = dict(crop_name="Spinach", category="Vegetables", quantity_kg="100", price_per_kg="30", quality="Standard",
                 harvest_date=date.today().isoformat(), city="Dadri", state="Uttar Pradesh", latitude="28.55",
                 longitude="77.55", description="Test", image_url="")
        d.update(o); return d


class AuthTests(Base):
    def test_register_login_logout(self):
        r = self.post("/register", dict(full_name="Test Farmer", email="t1@example.com", password="Passw0rdX", confirm_password="Passw0rdX",
                                        phone="9876543210", role="farmer", city="Dadri", state="Uttar Pradesh"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("/farmer/dashboard", r.headers["Location"])
        row = self.sql("SELECT password_hash FROM users WHERE email='t1@example.com'")[0]
        self.assertNotIn("Passw0rdX", row[0]); self.assertTrue(row[0].startswith(("scrypt:", "pbkdf2:")))
        self.assertEqual(self.c.get("/farmer/dashboard").status_code, 200)
        self.post("/logout")
        self.assertEqual(self.c.get("/farmer/dashboard").status_code, 302)
        self.login("t1@example.com") if False else None
        r = self.post("/login", {"email": "t1@example.com", "password": "Passw0rdX"})
        self.assertEqual(r.status_code, 302)

    def test_validation_and_duplicates(self):
        base = dict(full_name="A B", email="dup@example.com", password="Passw0rdX", confirm_password="Passw0rdX",
                    phone="9876543210", role="buyer", city="Noida", state="UP")
        self.assertEqual(self.post("/register", base).status_code, 302)
        self.post("/logout")
        self.assertIn("already exists", self.post("/register", base).get_data(as_text=True))
        for bad, msg in ((dict(base, email="x", password="Passw0rdX"), "valid email"),
                         (dict(base, email="n1@example.com", password="short", confirm_password="short"), "8+ characters"),
                         (dict(base, email="n2@example.com", phone="123"), "10-digit"),
                         (dict(base, email="n3@example.com", role="admin"), "farmer or a buyer")):
            self.assertIn(msg, self.post("/register", bad).get_data(as_text=True))

    def test_wrong_password_and_csrf(self):
        r = self.post("/login", {"email": "farmer1@demo.agrilink.test", "password": "wrong"})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(self.c.post("/login", data={"email": "a", "password": "b"}).status_code, 400)  # no CSRF token

    def test_open_redirect_blocked(self):
        r = self.post("/login?next=//evil.example", {"email": "buyer1@demo.agrilink.test", "password": PW})
        self.assertNotIn("evil.example", r.headers["Location"])


class AccessControlTests(Base):
    def test_roles(self):
        self.assertEqual(self.c.get("/orders").status_code, 302)  # anonymous -> login
        buyer, farmer = self.client_for("buyer1@demo.agrilink.test"), self.client_for("farmer1@demo.agrilink.test")
        self.assertEqual(buyer.get("/farmer/dashboard").status_code, 403)
        self.assertEqual(buyer.get("/farmer/listings/new").status_code, 403)
        self.assertEqual(farmer.get("/buyer/dashboard").status_code, 403)
        self.assertEqual(self.post("/listing/1/order", {"quantity_kg": "1"}, client=farmer).status_code, 403)
        self.assertEqual(buyer.get("/buyer/dashboard").status_code, 200)


class ListingTests(Base):
    def test_crud_and_ownership(self):
        f1, f2 = self.client_for("farmer1@demo.agrilink.test"), self.client_for("farmer2@demo.agrilink.test")
        r = self.post("/farmer/listings/new", self.listing_form(), client=f1)
        self.assertEqual(r.status_code, 302)
        lid = self.sql("SELECT id FROM crop_listings WHERE crop_name='Spinach'")[0][0]
        self.assertEqual(self.post(f"/farmer/listings/{lid}/edit", self.listing_form(price_per_kg="33.50"), client=f1).status_code, 302)
        self.assertEqual(self.sql("SELECT price_per_kg FROM crop_listings WHERE id=?", lid)[0][0], 33.5)
        # another farmer cannot edit / delete / toggle
        for path in (f"/farmer/listings/{lid}/edit", f"/farmer/listings/{lid}/delete", f"/farmer/listings/{lid}/toggle"):
            self.assertEqual(self.post(path, self.listing_form(), client=f2).status_code, 403, path)
        self.assertEqual(f2.get(f"/farmer/listings/{lid}/edit").status_code, 403)
        # toggle availability hides it from the marketplace
        self.post(f"/farmer/listings/{lid}/toggle", client=f1)
        self.assertNotIn("Spinach", self.c.get("/marketplace?q=spinach").get_data(as_text=True).split("listing")[0] + "")
        self.assertEqual(self.sql("SELECT status FROM crop_listings WHERE id=?", lid)[0][0], "unavailable")
        self.post(f"/farmer/listings/{lid}/delete", client=f1)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM crop_listings WHERE id=?", lid)[0][0], 0)

    def test_backend_validation(self):
        f = self.client_for("farmer1@demo.agrilink.test")
        before = self.sql("SELECT COUNT(*) FROM crop_listings")[0][0]
        for bad in (dict(quantity_kg="-5"), dict(quantity_kg="0"), dict(price_per_kg="0"), dict(price_per_kg="abc"),
                    dict(harvest_date="2999-01-01"), dict(latitude="95", longitude="77"), dict(latitude="28", longitude=""),
                    dict(category="Gold"), dict(image_url="javascript:alert(1)")):
            r = self.post("/farmer/listings/new", self.listing_form(**bad), client=f)
            self.assertEqual(r.status_code, 200, bad)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM crop_listings")[0][0], before)

    def test_upload_validation(self):
        f = self.client_for("farmer1@demo.agrilink.test")
        data = self.listing_form(crop_name="Okra"); data["image_file"] = (io.BytesIO(b"not an image at all"), "evil.png")
        r = self.post("/farmer/listings/new", data, client=f, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 200); self.assertIn("Upload a PNG", r.get_data(as_text=True))
        png = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
        data = self.listing_form(crop_name="Okra"); data["image_file"] = (io.BytesIO(png), "../../x.png")
        r = self.post("/farmer/listings/new", data, client=f, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 302)
        url = self.sql("SELECT image_url FROM crop_listings WHERE crop_name='Okra'")[0][0]
        self.assertRegex(url, r"^/static/uploads/[0-9a-f]{24}\.png$")


class MarketplaceTests(Base):
    def test_search_filters_sort_and_currency(self):
        html = self.c.get("/marketplace?q=tomato").get_data(as_text=True)
        self.assertIn("Tomatoes", html); self.assertNotIn("Wheat</a>", html)
        self.assertEqual(len(re.findall(r'class="pcard"', html)), 3)
        self.assertEqual(len(re.findall(r'class="pcard"', self.c.get("/marketplace?category=Oilseeds").get_data(as_text=True))), 2)
        self.assertEqual(len(re.findall(r'class="pcard"', self.c.get("/marketplace?max_price=20").get_data(as_text=True))), 2)
        self.assertEqual(len(re.findall(r'class="pcard"', self.c.get("/marketplace?min_qty=1000").get_data(as_text=True))), 1)
        self.assertEqual(len(re.findall(r'class="pcard"', self.c.get("/marketplace?quality=Basic&q=wheat").get_data(as_text=True))), 1)
        self.assertEqual(len(re.findall(r'class="pcard"', self.c.get("/marketplace?location=Jewar").get_data(as_text=True))), 3)
        html = self.c.get("/marketplace?sort=price_asc&per=1").get_data(as_text=True)
        prices = [int(p) for p in re.findall(r'class="price">₹(\d+)', html)]
        self.assertEqual(prices, sorted(prices)); self.assertTrue(prices)
        html = self.c.get("/marketplace?sort=price_desc").get_data(as_text=True)
        prices = [int(p) for p in re.findall(r'class="price">₹(\d+)', html)]
        self.assertEqual(prices, sorted(prices, reverse=True))
        self.assertIn("₹", html); self.assertNotRegex(html, r"\$\d|USD|€")
        self.assertIn("Demo data", html)

    def test_sql_injection_and_bad_params(self):
        r = self.c.get("/marketplace?q=' OR 1=1 --&min_price=abc&page=zzz&sort=evil")
        self.assertEqual(r.status_code, 200); self.assertIn("0</strong> listing", r.get_data(as_text=True))

    def test_nearest_sort(self):
        html = self.c.get("/marketplace?sort=nearest&lat=28.1270&lng=77.5570").get_data(as_text=True)
        first = html.split('class="pcard"')[1]
        self.assertIn("Mahesh Chauhan", first); self.assertIn("0.4 km", first)  # Jewar farmer is closest to Jewar
        self.assertIn("km", html)
        self.assertIn("Set your location", self.app.test_client().get("/marketplace?sort=nearest").get_data(as_text=True))


class MoneyTests(unittest.TestCase):
    def test_inr_and_units(self):
        self.assertEqual(money.inr(25), "₹25"); self.assertEqual(money.inr(1250), "₹1,250")
        self.assertEqual(money.inr(125000), "₹1,25,000"); self.assertEqual(money.inr(24.5), "₹24.50")
        self.assertEqual(money.inr(1234567.8), "₹12,34,567.80"); self.assertEqual(money.per_kg(24), "₹24/kg")
        self.assertEqual(money.quintal_to_kg(2500), Decimal("25"))
        self.assertEqual(money.q2(Decimal("10") * Decimal("24")), Decimal("240.00"))
        self.assertEqual(money.q2(Decimal("2.675")), Decimal("2.68"))

    def test_example_comparison(self):
        c = P._compare(Decimal("22"), Decimal("24"))
        self.assertEqual((c["difference"], c["percent"], c["verdict"]), (Decimal("2.00"), Decimal("9.09"), "close"))


class OrderTests(Base):
    def setUp(self):
        super().setUp()
        self.farmer = self.client_for("farmer1@demo.agrilink.test")
        self.buyer = self.client_for("buyer1@demo.agrilink.test")
        self.buyer2 = self.client_for("buyer2@demo.agrilink.test")
        self.post("/farmer/listings/new", self.listing_form(crop_name="Carrot", quantity_kg="100", price_per_kg="24"), client=self.farmer)
        self.lid = self.sql("SELECT id FROM crop_listings WHERE crop_name='Carrot'")[0][0]

    def order(self, qty, client=None, lid=None):
        return self.post(f"/listing/{lid or self.lid}/order", {"quantity_kg": qty, "delivery_preference": "pickup", "message": "hi"}, client=client or self.buyer)

    def row(self, oid):
        return self.sql("SELECT * FROM order_requests WHERE id=?", oid)[0]

    def stock(self):
        return self.sql("SELECT quantity_kg, status FROM crop_listings WHERE id=?", self.lid)[0]

    def last_order(self):
        return self.sql("SELECT id FROM order_requests ORDER BY id DESC LIMIT 1")[0][0]

    def test_total_and_validation(self):
        self.assertEqual(self.order("10").status_code, 302)
        o = self.row(self.last_order()); self.assertEqual((o["product_cost"], o["status"], o["price_per_kg"]), (240.0, "pending", 24.0))
        n = self.sql("SELECT COUNT(*) FROM order_requests")[0][0]
        for bad in ("0", "-3", "abc", "100.01", "", "1e9"):
            self.order(bad)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM order_requests")[0][0], n)
        self.assertEqual(self.stock()[0], 100.0)  # a request does not touch stock

    def test_accept_deducts_stock_and_status_visible_to_buyer(self):
        self.order("40"); oid = self.last_order()
        self.assertIn("Pending", self.buyer.get("/orders").get_data(as_text=True))
        self.assertIn("Carrot", self.farmer.get("/farmer/dashboard").get_data(as_text=True))
        self.post(f"/orders/{oid}/accept", client=self.farmer)
        self.assertEqual(self.row(oid)["status"], "accepted"); self.assertEqual(self.stock()[0], 60.0)
        self.assertIn("Accepted", self.buyer.get("/orders").get_data(as_text=True))
        self.post(f"/orders/{oid}/accept", client=self.farmer)           # invalid: already accepted
        self.assertEqual(self.stock()[0], 60.0)
        self.post(f"/orders/{oid}/cancel", client=self.buyer)            # buyer cannot cancel accepted
        self.assertEqual(self.row(oid)["status"], "accepted")
        self.post(f"/orders/{oid}/complete", client=self.farmer)
        self.assertEqual(self.row(oid)["status"], "completed")
        self.post(f"/orders/{oid}/reject", client=self.farmer)           # completed cannot be rejected
        self.assertEqual(self.row(oid)["status"], "completed")

    def test_no_overselling(self):
        self.order("70"); a = self.last_order(); self.order("70", client=self.buyer2); b = self.last_order()  # both fit individually
        self.post(f"/orders/{a}/accept", client=self.farmer); self.post(f"/orders/{b}/accept", client=self.farmer)
        self.assertEqual(self.row(a)["status"], "accepted"); self.assertEqual(self.row(b)["status"], "pending")
        self.assertEqual(self.stock()[0], 30.0)
        self.order("31")  # exceeds remaining stock
        self.assertEqual(self.sql("SELECT COUNT(*) FROM order_requests WHERE quantity_kg=31")[0][0], 0)
        self.order("30", client=self.buyer2); c = self.last_order(); self.post(f"/orders/{c}/accept", client=self.farmer)
        self.assertEqual(tuple(self.stock()), (0.0, "sold_out"))
        self.order("1")  # sold out listing refuses requests
        self.assertEqual(self.sql("SELECT COUNT(*) FROM order_requests WHERE quantity_kg=1 AND listing_id=?", self.lid)[0][0], 0)
        self.assertGreaterEqual(self.stock()[0], 0)

    def test_reject_cancel_and_authorization(self):
        self.order("5"); a = self.last_order(); self.order("6"); b = self.last_order()
        other_farmer = self.client_for("farmer2@demo.agrilink.test")
        self.post(f"/orders/{a}/accept", client=other_farmer); self.assertEqual(self.row(a)["status"], "pending")
        self.post(f"/orders/{a}/cancel", client=self.buyer2); self.assertEqual(self.row(a)["status"], "pending")
        self.assertEqual(self.post(f"/orders/{a}/accept", client=self.buyer).status_code, 403)
        self.post(f"/orders/{a}/reject", client=self.farmer); self.assertEqual(self.row(a)["status"], "rejected")
        self.post(f"/orders/{b}/cancel", client=self.buyer); self.assertEqual(self.row(b)["status"], "cancelled")
        self.assertEqual(self.stock()[0], 100.0)
        self.assertIn("Rejected", self.buyer.get("/orders").get_data(as_text=True))

    def test_delete_blocked_with_open_orders(self):
        self.order("5")
        self.post(f"/farmer/listings/{self.lid}/delete", client=self.farmer)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM crop_listings WHERE id=?", self.lid)[0][0], 1)

    def test_persistence_after_restart(self):
        self.order("12")
        app2 = create_app(self.cfg)
        c2 = app2.test_client()
        self.assertIn("Carrot", c2.get("/marketplace?q=carrot").get_data(as_text=True))
        self.assertEqual(self.sql("SELECT COUNT(*) FROM users")[0][0], 9)  # seed did not duplicate
        self.assertEqual(self.sql("SELECT COUNT(*) FROM order_requests WHERE quantity_kg=12")[0][0], 1)


class DistanceTests(unittest.TestCase):
    def test_distance_and_transport(self):
        self.assertAlmostEqual(haversine_km(28, 77, 29, 77), 111.2, delta=0.3)
        self.assertEqual(haversine_km(28, 77, 28, 77), 0)
        self.assertIsNone(haversine_km(None, 77, 28, 77)); self.assertIsNone(haversine_km(95, 77, 28, 77))
        self.assertFalse(valid_coords("abc", 1)); self.assertTrue(valid_coords("28.5", "77.5"))
        t = transport_cost(25, 12); self.assertEqual(t, Decimal("300.00"))
        self.assertEqual(delivered_cost(Decimal("240"), t), Decimal("540.00"))

    def test_nearby_page_costs(self):
        app = create_app({"DATABASE": tempfile.mkdtemp() + "/n.db", "MODEL_DIR": tempfile.mkdtemp(), "TESTING": True})
        c = app.test_client()
        html = c.get("/nearby-farmers?crop=Tomato&quantity=10&rate=10&lat=28.4744&lng=77.5040").get_data(as_text=True)
        self.assertIn("Est. delivered cost", html); self.assertRegex(html, r"<strong>₹[\d,]+\.\d\d</strong>")
        no_loc = app.test_client().get("/nearby-farmers?crop=Tomato&quantity=10").get_data(as_text=True)
        self.assertNotRegex(no_loc, r"<strong>₹[\d,]+\.\d\d</strong>")  # no distance -> no delivered cost
        api = c.get("/api/farmers?crop=Wheat&lat=28.47&lng=77.5").get_json()
        self.assertGreater(api["count"], 0); self.assertTrue(all("lat" in m and "lng" in m for m in api["markers"]))
        self.assertEqual(c.get("/api/transport?lat1=28.5&lng1=77.5&lat2=28.6&lng2=77.5&rate=10").get_json()["rate_per_km"], "10")
        self.assertEqual(c.get("/api/transport?lat1=x&lng1=77.5&lat2=28.6&lng2=77.5").status_code, 400)


class MapTests(Base):
    def test_map_page(self):
        html = self.c.get("/nearby-farmers").get_data(as_text=True)
        self.assertIn("leaflet@1.9.4/dist/leaflet.js", html); self.assertIn('id="farmer-map"', html)
        self.assertIn("OpenStreetMap contributors", html)
        data = json.loads(re.search(r'id="map-data">(.*?)</script>', html, re.S).group(1))
        self.assertEqual(len(data["markers"]), 6)  # one marker per fictional farmer location
        self.assertTrue(all(27 < m["lat"] < 29 and 77 < m["lng"] < 78 for m in data["markers"]))
        self.assertIn("tile.openstreetmap.org", pathlib.Path("static/js/map.js").read_text(encoding="utf-8"))


class EstimatorTests(Base):
    def test_demo_mode_is_labelled(self):
        r = self.c.get("/price-estimator?crop=Tomato&asking=24&date=2026-07-01&go=1").get_data(as_text=True)
        self.assertIn("Demonstration mode", r); self.assertIn("illustrative", r.lower()); self.assertNotIn("Model trained and evaluated", r)
        j = self.c.get("/api/estimate?crop=Tomato&asking=24&date=2026-07-01").get_json()
        self.assertEqual(j["mode"], "demo"); self.assertIsNone(j["metrics"]); self.assertEqual(j["verdict"] in ("close", "above", "below"), True)
        self.assertEqual(self.c.get("/api/estimate?crop=Dragonfruit").get_json()["reference"], None)
        self.assertEqual(self.c.get("/api/estimate").status_code, 400)

    def test_import_train_and_estimate_on_synthetic_data(self):
        csv_path = os.path.join(self.tmp, "SYNTHETIC_test.csv")
        make_sample_dataset.make(csv_path, days=400)
        from models import connect
        conn = connect(self.cfg["DATABASE"])
        with self.assertRaises(InsufficientData):  # nothing imported yet -> must refuse to train
            train(self.cfg["DATABASE"], self.cfg["MODEL_DIR"])
        self.assertFalse(os.path.exists(os.path.join(self.cfg["MODEL_DIR"], "metadata.json")))
        stats = P.import_mandi_csv(conn, csv_path)
        self.assertGreater(stats["rows_imported"], 1000)
        row = conn.execute("SELECT modal_price_per_kg FROM price_history WHERE commodity='Wheat' LIMIT 1").fetchone()[0]
        self.assertTrue(10 < row < 60, row)  # converted from INR/quintal (~2600) to INR/kg (~26)
        self.assertEqual(P.import_mandi_csv(conn, csv_path)["rows_imported"], 0)  # idempotent
        meta = train(self.cfg["DATABASE"], self.cfg["MODEL_DIR"], ["SYNTHETIC_test.csv"])
        conn.close()
        self.assertGreater(meta["mae_per_kg"], 0); self.assertLess(meta["mae_per_kg"], 5)
        self.assertGreater(meta["test_rows"], 50)
        j = self.c.get("/api/estimate?crop=Tomato&market=Dadri&asking=24").get_json()
        self.assertEqual(j["mode"], "model"); self.assertIsNotNone(j["metrics"])
        self.assertTrue(any("SYNTHETIC" in w for w in j["warnings"]))
        self.assertIn("Model trained and evaluated", self.c.get("/price-estimator").get_data(as_text=True))
        from ml.evaluate_model import evaluate
        ev = evaluate(self.cfg["DATABASE"], self.cfg["MODEL_DIR"]); self.assertEqual(ev["test_rows"], meta["test_rows"])

    def test_bad_csv_rejected(self):
        p = os.path.join(self.tmp, "bad.csv"); pathlib.Path(p).write_text("a,b\n1,2\n")
        from models import connect
        with self.assertRaises(ValueError):
            P.import_mandi_csv(connect(self.cfg["DATABASE"]), p)


class ErrorTests(Base):
    def test_errors(self):
        self.assertEqual(self.c.get("/nope").status_code, 404)
        self.assertEqual(self.c.get("/listing/99999").status_code, 404)
        self.assertEqual(self.c.get("/farmer/listings/1/edit").status_code, 302)


class WorkflowAndIntegrationTests(Base):
    def test_end_to_end_farmer_to_buyer_lifecycle(self):
        # 1. Register a new farmer
        f_client = self.app.test_client()
        r = self.post("/register", {
            "full_name": "Dev Farmer", "email": "devfarmer@example.com", "password": PW, "confirm_password": PW,
            "phone": "9876543299", "role": "farmer", "city": "Greater Noida", "state": "Uttar Pradesh"
        }, client=f_client)
        self.assertEqual(r.status_code, 302)
        self.assertIn("/farmer/dashboard", r.headers["Location"])

        # 2. Farmer creates a new listing (Cabbage, 100 kg @ ₹25/kg)
        r = self.post("/farmer/listings/new", self.listing_form(
            crop_name="Cabbage", category="Vegetables", quantity_kg="100", price_per_kg="25",
            quality="Premium", city="Greater Noida", state="Uttar Pradesh", latitude="28.4744", longitude="77.5040"
        ), client=f_client)
        self.assertEqual(r.status_code, 302)
        lid = self.sql("SELECT id FROM crop_listings WHERE crop_name='Cabbage'")[0][0]

        # 3. Register a new buyer
        b_client = self.app.test_client()
        r = self.post("/register", {
            "full_name": "Dev Buyer", "email": "devbuyer@example.com", "password": PW, "confirm_password": PW,
            "phone": "9123456789", "role": "buyer", "city": "Noida", "state": "Uttar Pradesh"
        }, client=b_client)
        self.assertEqual(r.status_code, 302)

        # 4. Buyer searches marketplace for Cabbage
        market_html = b_client.get("/marketplace?q=cabbage").get_data(as_text=True)
        self.assertIn("Cabbage", market_html)
        self.assertIn("₹25", market_html)

        # 5. Buyer views product detail page
        detail_html = b_client.get(f"/listing/{lid}").get_data(as_text=True)
        self.assertIn("Dev Farmer", detail_html)
        self.assertIn("Send an order request", detail_html)

        # 6. Buyer places an order for 20 kg
        r = self.post(f"/listing/{lid}/order", {
            "quantity_kg": "20", "delivery_preference": "delivery", "message": "Fresh cabbage please"
        }, client=b_client)
        self.assertEqual(r.status_code, 302)
        oid = self.sql("SELECT id FROM order_requests WHERE listing_id=? AND buyer_id=(SELECT id FROM users WHERE email='devbuyer@example.com')", lid)[0][0]

        # 7. Verify pending order details: cost = 20 * 25 = 500, stock not yet deducted
        order_row = self.sql("SELECT * FROM order_requests WHERE id=?", oid)[0]
        self.assertEqual(order_row["status"], "pending")
        self.assertEqual(order_row["product_cost"], 500.0)
        stock_row = self.sql("SELECT quantity_kg, status FROM crop_listings WHERE id=?", lid)[0]
        self.assertEqual(stock_row["quantity_kg"], 100.0)

        # 8. Farmer dashboard shows pending order and accepts it
        dash_html = f_client.get("/farmer/dashboard").get_data(as_text=True)
        self.assertIn("Cabbage", dash_html)
        self.assertIn("Dev Buyer", dash_html)
        r = self.post(f"/orders/{oid}/accept", client=f_client)
        self.assertEqual(r.status_code, 302)

        # 9. Verify stock deducted to 80 kg and order status accepted
        self.assertEqual(self.sql("SELECT status FROM order_requests WHERE id=?", oid)[0][0], "accepted")
        self.assertEqual(self.sql("SELECT quantity_kg FROM crop_listings WHERE id=?", lid)[0][0], 80.0)

        # 10. Buyer sees accepted status and farmer contact info
        buyer_orders = b_client.get("/orders").get_data(as_text=True)
        self.assertIn("Accepted", buyer_orders)
        self.assertIn("9876543299", buyer_orders)

        # 11. Farmer marks order completed
        r = self.post(f"/orders/{oid}/complete", client=f_client)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.sql("SELECT status FROM order_requests WHERE id=?", oid)[0][0], "completed")

        # 12. Buyer orders remaining 80 kg -> stock reaches 0 -> status becomes sold_out
        r = self.post(f"/listing/{lid}/order", {"quantity_kg": "80", "delivery_preference": "pickup"}, client=b_client)
        self.assertEqual(r.status_code, 302)
        oid2 = self.sql("SELECT id FROM order_requests WHERE listing_id=? ORDER BY id DESC LIMIT 1", lid)[0][0]
        self.post(f"/orders/{oid2}/accept", client=f_client)
        l_after = self.sql("SELECT quantity_kg, status FROM crop_listings WHERE id=?", lid)[0]
        self.assertEqual(tuple(l_after), (0.0, "sold_out"))

        # 13. Farmer restocks listing by editing quantity to 45 kg
        r = self.post(f"/farmer/listings/{lid}/edit", self.listing_form(
            crop_name="Cabbage", category="Vegetables", quantity_kg="45", price_per_kg="25",
            quality="Premium", city="Greater Noida", state="Uttar Pradesh"
        ), client=f_client)
        self.assertEqual(r.status_code, 302)
        restocked = self.sql("SELECT quantity_kg, status FROM crop_listings WHERE id=?", lid)[0]
        self.assertEqual(tuple(restocked), (45.0, "active"))

    def test_transport_api_and_safe_redirect(self):
        # Test transport API with custom rate
        t = self.c.get("/api/transport?lat1=28.4744&lng1=77.5040&lat2=28.5530&lng2=77.5540&rate=15").get_json()
        self.assertGreater(t["distance_km"], 5)
        self.assertEqual(t["rate_per_km"], "15")
        self.assertIn("estimated_transport_cost", t)

        # Test safe_next on back redirect in order transition
        f = self.client_for("farmer1@demo.agrilink.test")
        b = self.client_for("buyer1@demo.agrilink.test")
        self.post("/farmer/listings/new", self.listing_form(crop_name="Garlic", quantity_kg="50", price_per_kg="80"), client=f)
        lid = self.sql("SELECT id FROM crop_listings WHERE crop_name='Garlic'")[0][0]
        self.post(f"/listing/{lid}/order", {"quantity_kg": "5", "delivery_preference": "pickup"}, client=b)
        oid = self.sql("SELECT id FROM order_requests WHERE listing_id=?", lid)[0][0]
        
        # Test malicious back url redirects safely to orders list
        r = self.post(f"/orders/{oid}/accept", {"back": "https://evil.com"}, client=f)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.headers["Location"], "/orders")


if __name__ == "__main__":
    unittest.main()
