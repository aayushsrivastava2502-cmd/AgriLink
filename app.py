"""AgriLink AI - Flask application factory, CSRF protection, template filters and CLI commands."""
import hmac
import os
import secrets
from datetime import datetime
from urllib.parse import parse_qs, unquote, urlencode

import click
from flask import Flask, abort, g, render_template, request, session

import models
from config import Config
from models import user as U
from ml.features import normalize_crop
from services import i18n, money, pricing_service
from services.seed_data import DEMO_PASSWORD, seed, seed_collection_points

CROP_IMAGES = {"wheat": "wheat", "rice": "rice", "tomato": "tomato", "potato": "potato", "onion": "onion",
               "mustard": "mustard", "cauliflower": "cauliflower", "green peas": "peas"}


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    try:
        os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    except OSError:
        pass
    db_target = app.config["DATABASE"]
    if not models.is_postgres_url(db_target):
        try:
            db_dir = os.path.dirname(db_target)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)
        except OSError:
            pass
    models.init_app(app)

    # ---- database bootstrap (idempotent) ----
    models.init_db(app.config["DATABASE"])
    conn = models.connect(app.config["DATABASE"])
    pricing_service.seed_market_references(conn)
    seed_collection_points(conn)
    if app.config.get("AUTO_SEED", True):
        seed(conn)
    conn.close()

    # ---- request hooks ----
    @app.before_request
    def capture_language():
        lang = request.args.get("lang")
        if lang and lang in i18n.SUPPORTED_LANGUAGES:
            session["lang"] = lang

    @app.before_request
    def load_user():
        uid = session.get("user_id")
        g.user = U.get_by_id(models.get_db(), uid) if uid else None
        if uid and g.user is None:
            lang = session.get("lang")
            session.clear()
            if lang:
                session["lang"] = lang

    @app.before_request
    def csrf_protect():
        if request.method in ("POST", "PUT", "PATCH", "DELETE") and app.config["CSRF_ENABLED"]:
            json_csrf = ""
            if request.is_json:
                payload = request.get_json(silent=True)
                if isinstance(payload, dict):
                    json_csrf = payload.get("_csrf") or ""
            sent = request.form.get("_csrf") or request.headers.get("X-CSRF-Token") or json_csrf or ""
            if not hmac.compare_digest(sent, session.get("_csrf", "")):
                abort(400, "Your form expired. Go back, refresh the page and try again.")

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return resp

    def csrf_token():
        if "_csrf" not in session:
            session["_csrf"] = secrets.token_urlsafe(32)
        return session["_csrf"]

    # ---- template helpers ----
    app.jinja_env.globals.update(
        csrf_token=csrf_token,
        _=i18n._,
        t=i18n.t,
        current_lang=i18n.get_current_language,
        supported_languages=lambda: i18n.SUPPORTED_LANGUAGES,
        get_js_translations=i18n.get_js_translations_dict
    )
    app.jinja_env.filters.update(
        inr=money.inr,
        per_kg=money.per_kg,
        kg=money.kg,
        t=i18n.t,
        _=i18n._
    )

    HI_MONTHS = {"Jan": "जनवरी", "Feb": "फ़रवरी", "Mar": "मार्च", "Apr": "अप्रैल",
                 "May": "मई", "Jun": "जून", "Jul": "जुलाई", "Aug": "अगस्त",
                 "Sep": "सितंबर", "Oct": "अक्टूबर", "Nov": "नवंबर", "Dec": "दिसंबर"}

    @app.template_filter("fmt_date")
    def fmt_date(value):
        try:
            dt = datetime.fromisoformat(str(value)[:10])
            if i18n.get_current_language() == "hi":
                month_hi = HI_MONTHS.get(dt.strftime("%b"), dt.strftime("%b"))
                return f"{dt.day} {month_hi} {dt.year}"
            return dt.strftime("%d %b %Y")
        except ValueError:
            return str(value)

    @app.template_filter("crop_image")
    def crop_image(listing):
        if listing["image_url"]:
            return listing["image_url"]
        return f"/static/images/crops/{CROP_IMAGES.get(normalize_crop(listing['crop_name']).lower(), 'default')}.svg"

    @app.context_processor
    def inject():
        return {
            "current_user": g.get("user"),
            "demo_password": DEMO_PASSWORD,
            "current_lang": i18n.get_current_language(),
            "supported_languages": i18n.SUPPORTED_LANGUAGES
        }

    # ---- blueprints ----
    from routes import auth, farmer, main, orders, transport
    for bp in (main.bp, auth.bp, farmer.bp, orders.bp, transport.bp):
        app.register_blueprint(bp)

    # ---- errors ----
    def _err(code, title, msg):
        return lambda e: (render_template("error.html", code=code, title=title,
                                          message=getattr(e, "description", msg) or msg), code)
    app.register_error_handler(400, _err(400, "Request could not be completed", "Please go back and try again."))
    app.register_error_handler(403, _err(403, "Not allowed", "Your account does not have access to this page."))
    app.register_error_handler(404, _err(404, "Page not found", "The page or listing you wanted does not exist."))
    app.register_error_handler(413, _err(413, "File too large", "Uploads must be 2 MB or smaller."))
    app.register_error_handler(500, _err(500, "Something went wrong", "An unexpected error occurred."))

    # ---- CLI ----
    @app.cli.command("init-db")
    def init_db_cmd():
        """Create tables (safe to run again)."""
        models.init_db(app.config["DATABASE"])
        click.echo(f"Database ready: {app.config['DATABASE']}")

    @app.cli.command("seed-db")
    @click.option("--reset", is_flag=True, help="Delete ALL data first, then re-seed the demo data.")
    def seed_cmd(reset):
        """Load fictional demonstration data."""
        c = models.connect(app.config["DATABASE"])
        if reset:
            for t in ("order_requests", "crop_listings", "users", "market_references"):
                c.execute(f"DELETE FROM {t}")
            c.execute("DELETE FROM sqlite_sequence")
        pricing_service.seed_market_references(c)
        click.echo("Demo data loaded." if seed(c) else "Database already has users; use --reset to start over.")
        c.close()

    @app.cli.command("import-mandi")
    @click.argument("csv_path", type=click.Path(exists=True, dir_okay=False))
    @click.option("--unit", type=click.Choice(["quintal", "kg"]), default="quintal", show_default=True)
    @click.option("--source", default=None, help="Label stored with the data, e.g. 'AGMARKNET 2025'.")
    def import_cmd(csv_path, unit, source):
        """Import an AGMARKNET / data.gov.in mandi price CSV into price_history (INR/kg)."""
        c = models.connect(app.config["DATABASE"])
        click.echo(pricing_service.import_mandi_csv(c, csv_path, source, unit))
        c.close()

    @app.cli.command("train-model")
    def train_cmd():
        """Train and evaluate the RandomForest price model on price_history."""
        from ml.train_model import InsufficientData, train
        c = models.connect(app.config["DATABASE"])
        srcs = [r[0] for r in c.execute("SELECT DISTINCT source FROM price_history")]
        c.close()
        try:
            meta = train(app.config["DATABASE"], app.config["MODEL_DIR"], srcs)
        except InsufficientData as exc:
            raise click.ClickException(str(exc))
        click.echo(f"Trained. Test MAE = Rs {meta['mae_per_kg']}/kg (last-price baseline "
                   f"Rs {meta['baseline_last_price_mae_per_kg']}/kg) on {meta['test_rows']} hold-out rows.")

    app.wsgi_app = VercelPathMiddleware(app.wsgi_app)
    return app


class VercelPathMiddleware:
    """WSGI Middleware for Vercel deployment of AgriLink AI.

    Normalizes PATH_INFO, SCRIPT_NAME, and QUERY_STRING so Flask routes match accurately
    when Vercel forwards requests through serverless rewrites or proxies.
    """

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        query_string = environ.get("QUERY_STRING", "")
        path_info = environ.get("PATH_INFO", "")

        # 1. Prefer original path captured via rewrite query parameter
        if "__vercel_path__=" in query_string:
            params = parse_qs(query_string, keep_blank_values=True)
            if "__vercel_path__" in params:
                real_paths = params.pop("__vercel_path__")
                if real_paths and real_paths[0]:
                    raw_path = unquote(real_paths[0])
                    if "?" in raw_path:
                        path_part, extra_query = raw_path.split("?", 1)
                        raw_path = path_part
                        if extra_query:
                            extra_params = parse_qs(extra_query, keep_blank_values=True)
                            for k, v in extra_params.items():
                                params.setdefault(k, []).extend(v)
                    if not raw_path.startswith("/"):
                        raw_path = "/" + raw_path
                    path_info = raw_path
                environ["QUERY_STRING"] = urlencode(params, doseq=True)

        # 2. Check headers that Vercel or edge proxies might pass
        elif environ.get("HTTP_X_MATCHED_PATH") and not environ["HTTP_X_MATCHED_PATH"].startswith("/api/index"):
            path_info = unquote(environ["HTTP_X_MATCHED_PATH"].split("?")[0])
        elif environ.get("HTTP_X_FORWARDED_URI"):
            path_info = unquote(environ["HTTP_X_FORWARDED_URI"].split("?")[0])
        elif environ.get("HTTP_X_ORIGINAL_URL"):
            path_info = unquote(environ["HTTP_X_ORIGINAL_URL"].split("?")[0])

        # 3. If path_info still has /api/index prefix (e.g. legacy rewrite or direct function call), strip it
        if path_info.startswith("/api/index.py"):
            path_info = path_info[len("/api/index.py"):] or "/"
        elif path_info.startswith("/api/index"):
            path_info = path_info[len("/api/index"):] or "/"

        # 4. Normalize path_info: ensure leading slash and collapse double slashes
        if not path_info or not path_info.startswith("/"):
            path_info = "/" + (path_info or "")
        while path_info.startswith("//"):
            path_info = path_info[1:]

        environ["PATH_INFO"] = path_info
        environ["SCRIPT_NAME"] = ""

        return self.wsgi_app(environ, start_response)


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=os.environ.get("FLASK_DEBUG") == "1")
