"""Tests for Vercel deployment readiness and PostgreSQL database compatibility."""
import os
import unittest
from pathlib import Path

import models
from config import Config, _load_database_uri, _load_secret_key


class VercelAndDatabaseTests(unittest.TestCase):
    def test_vercel_entry_point_import(self):
        """Verify that api/index.py imports and exposes the Flask app correctly."""
        from api.index import app as vercel_app
        self.assertIsNotNone(vercel_app)
        self.assertEqual(vercel_app.name, "app")

    def test_postgres_url_detection(self):
        """Verify URL protocol detection for PostgreSQL vs SQLite."""
        self.assertTrue(models.is_postgres_url("postgresql://user:pass@localhost:5432/agrilink"))
        self.assertTrue(models.is_postgres_url("postgres://user:pass@ep-cool-1234.us-east-1.neon.tech/agrilink"))
        self.assertFalse(models.is_postgres_url("instance/agrilink.db"))
        self.assertFalse(models.is_postgres_url("/tmp/agrilink.db"))

    def test_query_conversion_for_postgres(self):
        """Verify ? to %s parameter marker conversion and INSERT OR IGNORE translation."""
        q1 = "SELECT * FROM users WHERE email = ? AND role = ?"
        conv1 = models._convert_query(q1)
        self.assertEqual(conv1, "SELECT * FROM users WHERE email = %s AND role = %s")

        # Literal question marks inside quotes must be preserved
        q2 = "SELECT * FROM users WHERE description = 'Is this a question?' AND id = ?"
        conv2 = models._convert_query(q2)
        self.assertIn("'Is this a question?'", conv2)
        self.assertIn("= %s", conv2)

        # INSERT OR IGNORE conversion
        q3 = "INSERT OR IGNORE INTO market_references (crop_name) VALUES (?)"
        conv3 = models._convert_query(q3)
        self.assertTrue(conv3.startswith("INSERT INTO market_references"))
        self.assertIn("ON CONFLICT DO NOTHING", conv3)

        # PRAGMA removal
        q4 = "PRAGMA foreign_keys = ON"
        conv4 = models._convert_query(q4)
        self.assertEqual(conv4, "")

        # sqlite_sequence removal
        q5 = "DELETE FROM sqlite_sequence"
        conv5 = models._convert_query(q5)
        self.assertEqual(conv5, "")

        # Wrapper classes contain executemany
        self.assertTrue(hasattr(models.PostgresCursorWrapper, "executemany"))
        self.assertTrue(hasattr(models.PostgresConnectionWrapper, "executemany"))

    def test_config_database_resolution(self):
        """Verify that Config honors DATABASE_URL or POSTGRES_URL when present."""
        old_db_url = os.environ.get("DATABASE_URL")
        try:
            os.environ["DATABASE_URL"] = "postgresql://test_user:test_pass@neon.tech/prod_db"
            self.assertEqual(_load_database_uri(), "postgresql://test_user:test_pass@neon.tech/prod_db")
        finally:
            if old_db_url is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = old_db_url

    def test_static_files_mirrored_for_vercel_cdn(self):
        """Verify essential static assets are present in public/static for Vercel CDN serving."""
        base = Path(__file__).resolve().parent.parent
        self.assertTrue((base / "public" / "static" / "css" / "style.css").exists())
        self.assertTrue((base / "public" / "static" / "js" / "map.js").exists())
        self.assertTrue((base / "public" / "static" / "vendor" / "leaflet" / "leaflet.js").exists())
        self.assertTrue((base / "public" / "static" / "vendor" / "leaflet" / "leaflet.css").exists())

    def test_vercel_config_and_ignore(self):
        """Verify vercel.json and .vercelignore exist and are valid."""
        base = Path(__file__).resolve().parent.parent
        self.assertTrue((base / "vercel.json").exists())
        self.assertTrue((base / ".vercelignore").exists())
        self.assertTrue((base / ".python-version").exists())

    def test_homepage_route_returns_200(self):
        """Regression test: verify root URL returns 200 and renders the homepage."""
        from api.index import app as vercel_app
        client = vercel_app.test_client()
        resp = client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"AgriLink AI", resp.data)
        self.assertIn(b"Marketplace", resp.data)

    def test_vercel_routing_middleware_root_and_fallback(self):
        """Verify Vercel rewrite captures and dispatches to homepage with 200 OK."""
        from api.index import app as vercel_app
        client = vercel_app.test_client()

        # 1. URL rewritten with __vercel_path__=/
        resp1 = client.get("/api/index?__vercel_path__=/")
        self.assertEqual(resp1.status_code, 200)
        self.assertIn(b"AgriLink AI", resp1.data)

        # 2. URL accessed directly as /api/index (fallback)
        resp2 = client.get("/api/index")
        self.assertEqual(resp2.status_code, 200)
        self.assertIn(b"AgriLink AI", resp2.data)

        # 3. URL accessed as /api/index.py (fallback)
        resp3 = client.get("/api/index.py")
        self.assertEqual(resp3.status_code, 200)
        self.assertIn(b"AgriLink AI", resp3.data)

    def test_vercel_routing_middleware_marketplace_and_subpaths(self):
        """Verify Vercel rewrite forwards subpaths and preserves query parameters cleanly."""
        from api.index import app as vercel_app
        client = vercel_app.test_client()

        # Marketplace with query parameters
        resp = client.get("/api/index?__vercel_path__=/marketplace&crop=wheat")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Marketplace", resp.data)

        # Route planner
        resp_planner = client.get("/api/index?__vercel_path__=/transport-optimizer/route-planner")
        self.assertEqual(resp_planner.status_code, 200)
        self.assertIn(b"Route Planner", resp_planner.data)

    def test_safe_next_normalizes_vercel_paths(self):
        """Verify safe_next normalizes /api/index back to /."""
        from routes.helpers import safe_next
        self.assertEqual(safe_next("/api/index"), "/")
        self.assertEqual(safe_next("/api/index.py"), "/")
        self.assertEqual(safe_next("/api/index/marketplace"), "/marketplace")
        self.assertEqual(safe_next("/marketplace"), "/marketplace")
        self.assertIsNone(safe_next("https://attacker.com"))



if __name__ == "__main__":
    unittest.main()
