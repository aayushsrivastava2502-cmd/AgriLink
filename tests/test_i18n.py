"""Comprehensive tests for bilingual (English & Hindi) internationalization support."""
import os
import shutil
import tempfile
import unittest

from app import create_app

PW = "Demo@1234"


class I18nTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = {
            "DATABASE": os.path.join(self.tmp, "t.db"),
            "MODEL_DIR": os.path.join(self.tmp, "model"),
            "UPLOAD_FOLDER": os.path.join(self.tmp, "up"),
            "TESTING": True,
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

    def test_set_language_endpoint_post_and_get(self):
        """Test switching language via POST and GET with safe redirect validation."""
        # 1. POST switch to Hindi
        r = self.post("/set-language", {"lang": "hi", "next": "/marketplace"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.headers.get("Location"), "/marketplace")
        with self.c.session_transaction() as s:
            self.assertEqual(s.get("lang"), "hi")

        # 2. GET switch back to English
        r = self.c.get("/set-language?lang=en&next=/price-estimator")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.headers.get("Location"), "/price-estimator")
        with self.c.session_transaction() as s:
            self.assertEqual(s.get("lang"), "en")

        # 3. Invalid language code is rejected and falls back safely
        r = self.post("/set-language", {"lang": "french", "next": "/"})
        self.assertEqual(r.status_code, 302)
        with self.c.session_transaction() as s:
            self.assertNotEqual(s.get("lang"), "french")

        # 4. Open redirect is prevented
        r = self.post("/set-language", {"lang": "hi", "next": "https://attacker.example.com"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.headers.get("Location"), "/")

    def test_language_persistence_across_login_and_logout(self):
        """Verify that selecting Hindi persists through login and logout sessions."""
        # Switch to Hindi before login
        self.post("/set-language", {"lang": "hi"})
        with self.c.session_transaction() as s:
            self.assertEqual(s.get("lang"), "hi")

        # Log in as a farmer
        self.login("farmer1@demo.agrilink.test", self.c)
        with self.c.session_transaction() as s:
            self.assertEqual(s.get("lang"), "hi")
            self.assertEqual(s.get("user_id"), 1)

        # Farmer dashboard should render in Hindi
        r = self.c.get("/farmer/dashboard")
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertIn("किसान डैशबोर्ड", html)
        self.assertIn("फसल जोड़ें", html)

        # Log out
        r = self.post("/logout", client=self.c)
        self.assertEqual(r.status_code, 302)
        with self.c.session_transaction() as s:
            self.assertEqual(s.get("lang"), "hi")
            self.assertIsNone(s.get("user_id"))

        # Navigating to home after logout remains in Hindi
        r = self.c.get("/")
        html = r.get_data(as_text=True)
        self.assertIn("होम", html)
        self.assertIn("बाज़ार", html)

    def test_hindi_content_on_marketplace_and_pricing(self):
        """Verify Hindi UI text on public and core marketplace pages."""
        # Switch to Hindi
        self.post("/set-language", {"lang": "hi"})

        # Homepage
        r = self.c.get("/")
        html = r.get_data(as_text=True)
        self.assertIn("बाज़ार", html)
        self.assertIn("स्मार्ट मूल्य", html)
        self.assertIn("आस-पास के किसान", html)
        self.assertIn("यह कैसे काम करता है", html)

        # Marketplace
        r = self.c.get("/marketplace")
        html = r.get_data(as_text=True)
        self.assertIn("फसल का नाम", html)
        self.assertIn("सभी श्रेणियां", html)
        self.assertIn("क्रमबद्ध करें", html)

        # Smart Price Estimator
        r = self.c.get("/price-estimator")
        html = r.get_data(as_text=True)
        self.assertIn("स्मार्ट मूल्य कैलकुलेटर", html)
        self.assertIn("फसल का नाम", html)
        self.assertIn("उचित मूल्य का अनुमान लगाएं", html)

        # Nearby Farmers
        r = self.c.get("/nearby-farmers")
        html = r.get_data(as_text=True)
        self.assertIn("आस-पास के किसान", html)
        self.assertIn("किसान खोजें", html)

    def test_hindi_content_on_transport_optimization_pages(self):
        """Verify Hindi translations on transport optimization, shared trips, pools, and hubs."""
        self.post("/set-language", {"lang": "hi"})

        # Transport dashboard
        r = self.c.get("/transport-optimizer/")
        html = r.get_data(as_text=True)
        self.assertIn("परिवहन लागत अनुकूलन", html)
        self.assertIn("साझा डिलीवरी", html)
        self.assertIn("अनुमानित साझा बचत", html)
        self.assertIn("संग्रह केंद्र", html)

        # Shared trips
        r = self.c.get("/transport-optimizer/shared-trips")
        html = r.get_data(as_text=True)
        self.assertIn("साझा डिलीवरी ट्रिप", html)

        # Group pools
        r = self.c.get("/transport-optimizer/group-pools")
        html = r.get_data(as_text=True)
        self.assertIn("सामूहिक ऑर्डर पूल", html)
        self.assertIn("नया सामूहिक पूल शुरू करें", html)

        # Collection hubs
        r = self.c.get("/transport-optimizer/collection-points")
        html = r.get_data(as_text=True)
        self.assertIn("क्षेत्रीय संग्रह केंद्र (हब)", html)

        # Route planner
        r = self.c.get("/transport-optimizer/route-planner")
        html = r.get_data(as_text=True)
        self.assertIn("डिलीवरी मार्ग योजनाकार", html)

    def test_currency_and_units_integrity(self):
        """Monetary values must retain ₹, weights kg, and distances km regardless of language."""
        # Check in English
        self.post("/set-language", {"lang": "en"})
        r = self.c.get("/marketplace")
        html_en = r.get_data(as_text=True)
        self.assertIn("₹", html_en)
        self.assertIn("/kg", html_en)

        # Check in Hindi
        self.post("/set-language", {"lang": "hi"})
        r = self.c.get("/marketplace")
        html_hi = r.get_data(as_text=True)
        self.assertIn("₹", html_hi)
        self.assertIn("/kg", html_hi)

        # Transport dashboard costs & distances
        r = self.c.get("/transport-optimizer/")
        html_t = r.get_data(as_text=True)
        self.assertIn("₹", html_t)
        self.assertIn("kg", html_t)
        self.assertIn("km", html_t)

    def test_client_side_i18n_payload(self):
        """Verify window.AGRI_I18N contains localized labels for Leaflet and Chart.js."""
        # 1. Hindi payload
        self.post("/set-language", {"lang": "hi"})
        r = self.c.get("/")
        html = r.get_data(as_text=True)
        self.assertIn('window.currentLang = "hi"', html)
        self.assertIn('"contact": "\\u0938\\u0902\\u092a\\u0930\\u094d\\u0915"', html)  # संपर्क in unicode or utf-8

        # 2. English payload
        self.post("/set-language", {"lang": "en"})
        r = self.c.get("/")
        html = r.get_data(as_text=True)
        self.assertIn('window.currentLang = "en"', html)
        self.assertIn('"contact": "Contact"', html)


if __name__ == "__main__":
    unittest.main()
