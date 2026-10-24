"""Database layer supporting both SQLite (local development and testing)
and managed PostgreSQL (production deployment on Vercel via DATABASE_URL or POSTGRES_URL).
"""
import os
import re
import sqlite3
from contextlib import contextmanager

from flask import current_app, g

try:
    import psycopg2
    from psycopg2 import extras as psycopg2_extras
    from psycopg2 import IntegrityError as Psycopg2IntegrityError
except ImportError:
    psycopg2 = None
    psycopg2_extras = None
    Psycopg2IntegrityError = None

CATEGORIES = ["Cereals", "Vegetables", "Pulses", "Oilseeds", "Fruits", "Spices", "Other"]
QUALITIES = ["Premium", "Standard", "Basic"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name     TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    phone         TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('farmer', 'buyer')),
    city          TEXT NOT NULL,
    state         TEXT NOT NULL,
    is_demo       INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS crop_listings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    farmer_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    crop_name    TEXT NOT NULL,
    category     TEXT NOT NULL,
    quantity_kg  REAL NOT NULL CHECK (quantity_kg >= 0),
    price_per_kg REAL NOT NULL CHECK (price_per_kg > 0),     -- always INR per kilogram
    quality      TEXT NOT NULL CHECK (quality IN ('Premium', 'Standard', 'Basic')),
    harvest_date TEXT NOT NULL,
    city         TEXT NOT NULL,
    state        TEXT NOT NULL,
    latitude     REAL CHECK (latitude IS NULL OR latitude BETWEEN -90 AND 90),
    longitude    REAL CHECK (longitude IS NULL OR longitude BETWEEN -180 AND 180),
    description  TEXT,
    image_url    TEXT,
    status       TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'unavailable', 'sold_out')),
    is_demo      INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_listings_crop   ON crop_listings(crop_name);
CREATE INDEX IF NOT EXISTS idx_listings_farmer ON crop_listings(farmer_id);
CREATE INDEX IF NOT EXISTS idx_listings_status ON crop_listings(status);

CREATE TABLE IF NOT EXISTS order_requests (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id          INTEGER REFERENCES crop_listings(id) ON DELETE SET NULL,
    buyer_id            INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    farmer_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    crop_name           TEXT NOT NULL,          -- snapshot, survives listing deletion
    price_per_kg        REAL NOT NULL,          -- snapshot of INR/kg at request time
    quantity_kg         REAL NOT NULL CHECK (quantity_kg > 0),
    product_cost        REAL NOT NULL,          -- quantity_kg * price_per_kg, INR
    delivery_preference TEXT NOT NULL CHECK (delivery_preference IN ('pickup', 'delivery')),
    message             TEXT,
    status              TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'accepted', 'rejected', 'cancelled', 'completed')),
    is_demo             INTEGER NOT NULL DEFAULT 0,
    delivery_address    TEXT,
    delivery_lat        REAL,
    delivery_lng        REAL,
    created_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_orders_buyer  ON order_requests(buyer_id);
CREATE INDEX IF NOT EXISTS idx_orders_farmer ON order_requests(farmer_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON order_requests(status);

CREATE TABLE IF NOT EXISTS price_history (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    commodity          TEXT NOT NULL,
    market             TEXT NOT NULL,
    state              TEXT,
    price_date         TEXT NOT NULL,
    min_price_per_kg   REAL,
    max_price_per_kg   REAL,
    modal_price_per_kg REAL NOT NULL CHECK (modal_price_per_kg > 0),  -- converted from INR/quintal
    source             TEXT NOT NULL,
    UNIQUE (commodity, market, price_date, source)
);
CREATE INDEX IF NOT EXISTS idx_price_history_lookup ON price_history(commodity, market, price_date);

CREATE TABLE IF NOT EXISTS market_references (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    crop_name         TEXT NOT NULL UNIQUE,
    base_price_per_kg REAL NOT NULL,          -- ILLUSTRATIVE demonstration value, INR/kg
    month_factors     TEXT NOT NULL,          -- 12 comma-separated multipliers (Jan..Dec)
    note              TEXT
);

CREATE TABLE IF NOT EXISTS collection_points (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    address         TEXT NOT NULL,
    city            TEXT NOT NULL,
    state           TEXT NOT NULL,
    latitude        REAL NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    longitude       REAL NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    contact_person  TEXT,
    contact_phone   TEXT,
    capacity_kg     REAL DEFAULT 5000,
    operating_hours TEXT DEFAULT '06:00 AM - 08:00 PM',
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_collection_points_city ON collection_points(city);

CREATE TABLE IF NOT EXISTS shared_trips (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_code            TEXT NOT NULL UNIQUE,
    farmer_id            INTEGER REFERENCES users(id) ON DELETE CASCADE,
    collection_point_id  INTEGER REFERENCES collection_points(id) ON DELETE SET NULL,
    origin_name          TEXT NOT NULL,
    origin_lat           REAL NOT NULL,
    origin_lng           REAL NOT NULL,
    destination_area     TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'proposed'
                         CHECK (status IN ('proposed', 'confirmed', 'dispatched', 'completed', 'cancelled')),
    rate_per_km          REAL NOT NULL,
    total_distance_km    REAL NOT NULL,
    separate_total_cost  REAL NOT NULL,
    shared_total_cost    REAL NOT NULL,
    total_savings        REAL NOT NULL,
    savings_percent      REAL NOT NULL,
    allocation_method    TEXT NOT NULL DEFAULT 'proportional_weight',
    notes                TEXT,
    created_at           TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_shared_trips_farmer ON shared_trips(farmer_id);
CREATE INDEX IF NOT EXISTS idx_shared_trips_status ON shared_trips(status);

CREATE TABLE IF NOT EXISTS shared_trip_orders (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id                INTEGER NOT NULL REFERENCES shared_trips(id) ON DELETE CASCADE,
    order_id               INTEGER NOT NULL REFERENCES order_requests(id) ON DELETE CASCADE,
    stop_sequence          INTEGER NOT NULL DEFAULT 1,
    individual_distance_km REAL NOT NULL,
    individual_cost        REAL NOT NULL,
    allocated_cost         REAL NOT NULL,
    savings                REAL NOT NULL,
    savings_percent        REAL NOT NULL,
    UNIQUE (trip_id, order_id)
);
CREATE INDEX IF NOT EXISTS idx_trip_orders_trip ON shared_trip_orders(trip_id);
CREATE INDEX IF NOT EXISTS idx_trip_orders_order ON shared_trip_orders(order_id);

CREATE TABLE IF NOT EXISTS group_order_pools (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    pool_code            TEXT NOT NULL UNIQUE,
    listing_id           INTEGER NOT NULL REFERENCES crop_listings(id) ON DELETE CASCADE,
    farmer_id            INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    crop_name            TEXT NOT NULL,
    price_per_kg         REAL NOT NULL,
    target_delivery_area TEXT NOT NULL,
    target_lat           REAL NOT NULL,
    target_lng           REAL NOT NULL,
    min_total_kg         REAL NOT NULL DEFAULT 50.0,
    current_total_kg     REAL NOT NULL DEFAULT 0.0,
    status               TEXT NOT NULL DEFAULT 'open'
                         CHECK (status IN ('open', 'target_reached', 'confirmed', 'completed', 'cancelled')),
    created_by_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    notes                TEXT,
    created_at           TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_group_pools_listing ON group_order_pools(listing_id);
CREATE INDEX IF NOT EXISTS idx_group_pools_farmer ON group_order_pools(farmer_id);
CREATE INDEX IF NOT EXISTS idx_group_pools_status ON group_order_pools(status);

CREATE TABLE IF NOT EXISTS group_order_members (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    pool_id             INTEGER NOT NULL REFERENCES group_order_pools(id) ON DELETE CASCADE,
    buyer_id            INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    quantity_kg         REAL NOT NULL CHECK (quantity_kg > 0),
    delivery_preference TEXT NOT NULL DEFAULT 'delivery' CHECK (delivery_preference IN ('pickup', 'delivery')),
    delivery_address    TEXT,
    dest_lat            REAL,
    dest_lng            REAL,
    order_id            INTEGER REFERENCES order_requests(id) ON DELETE SET NULL,
    created_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_group_members_pool ON group_order_members(pool_id);
CREATE INDEX IF NOT EXISTS idx_group_members_buyer ON group_order_members(buyer_id);
"""

POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    full_name     TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    phone         TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('farmer', 'buyer')),
    city          TEXT NOT NULL,
    state         TEXT NOT NULL,
    is_demo       INTEGER NOT NULL DEFAULT 0,
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS crop_listings (
    id           SERIAL PRIMARY KEY,
    farmer_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    crop_name    TEXT NOT NULL,
    category     TEXT NOT NULL,
    quantity_kg  DOUBLE PRECISION NOT NULL CHECK (quantity_kg >= 0),
    price_per_kg DOUBLE PRECISION NOT NULL CHECK (price_per_kg > 0),
    quality      TEXT NOT NULL CHECK (quality IN ('Premium', 'Standard', 'Basic')),
    harvest_date TEXT NOT NULL,
    city         TEXT NOT NULL,
    state        TEXT NOT NULL,
    latitude     DOUBLE PRECISION,
    longitude    DOUBLE PRECISION,
    description  TEXT,
    image_url    TEXT,
    status       TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'unavailable', 'sold_out')),
    is_demo      INTEGER NOT NULL DEFAULT 0,
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_listings_crop   ON crop_listings(crop_name);
CREATE INDEX IF NOT EXISTS idx_listings_farmer ON crop_listings(farmer_id);
CREATE INDEX IF NOT EXISTS idx_listings_status ON crop_listings(status);

CREATE TABLE IF NOT EXISTS order_requests (
    id                  SERIAL PRIMARY KEY,
    listing_id          INTEGER REFERENCES crop_listings(id) ON DELETE SET NULL,
    buyer_id            INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    farmer_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    crop_name           TEXT NOT NULL,
    price_per_kg        DOUBLE PRECISION NOT NULL,
    quantity_kg         DOUBLE PRECISION NOT NULL CHECK (quantity_kg > 0),
    product_cost        DOUBLE PRECISION NOT NULL,
    delivery_preference TEXT NOT NULL CHECK (delivery_preference IN ('pickup', 'delivery')),
    message             TEXT,
    status              TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'accepted', 'rejected', 'cancelled', 'completed')),
    is_demo             INTEGER NOT NULL DEFAULT 0,
    delivery_address    TEXT,
    delivery_lat        DOUBLE PRECISION,
    delivery_lng        DOUBLE PRECISION,
    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_orders_buyer  ON order_requests(buyer_id);
CREATE INDEX IF NOT EXISTS idx_orders_farmer ON order_requests(farmer_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON order_requests(status);

CREATE TABLE IF NOT EXISTS price_history (
    id                 SERIAL PRIMARY KEY,
    commodity          TEXT NOT NULL,
    market             TEXT NOT NULL,
    state              TEXT,
    price_date         TEXT NOT NULL,
    min_price_per_kg   DOUBLE PRECISION,
    max_price_per_kg   DOUBLE PRECISION,
    modal_price_per_kg DOUBLE PRECISION NOT NULL CHECK (modal_price_per_kg > 0),
    source             TEXT NOT NULL,
    UNIQUE (commodity, market, price_date, source)
);
CREATE INDEX IF NOT EXISTS idx_price_history_lookup ON price_history(commodity, market, price_date);

CREATE TABLE IF NOT EXISTS market_references (
    id                SERIAL PRIMARY KEY,
    crop_name         TEXT NOT NULL UNIQUE,
    base_price_per_kg DOUBLE PRECISION NOT NULL,
    month_factors     TEXT NOT NULL,
    note              TEXT
);

CREATE TABLE IF NOT EXISTS collection_points (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    address         TEXT NOT NULL,
    city            TEXT NOT NULL,
    state           TEXT NOT NULL,
    latitude        DOUBLE PRECISION NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    longitude       DOUBLE PRECISION NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    contact_person  TEXT,
    contact_phone   TEXT,
    capacity_kg     DOUBLE PRECISION DEFAULT 5000,
    operating_hours TEXT DEFAULT '06:00 AM - 08:00 PM',
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_collection_points_city ON collection_points(city);

CREATE TABLE IF NOT EXISTS shared_trips (
    id                   SERIAL PRIMARY KEY,
    trip_code            TEXT NOT NULL UNIQUE,
    farmer_id            INTEGER REFERENCES users(id) ON DELETE CASCADE,
    collection_point_id  INTEGER REFERENCES collection_points(id) ON DELETE SET NULL,
    origin_name          TEXT NOT NULL,
    origin_lat           DOUBLE PRECISION NOT NULL,
    origin_lng           DOUBLE PRECISION NOT NULL,
    destination_area     TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'proposed'
                         CHECK (status IN ('proposed', 'confirmed', 'dispatched', 'completed', 'cancelled')),
    rate_per_km          DOUBLE PRECISION NOT NULL,
    total_distance_km    DOUBLE PRECISION NOT NULL,
    separate_total_cost  DOUBLE PRECISION NOT NULL,
    shared_total_cost    DOUBLE PRECISION NOT NULL,
    total_savings        DOUBLE PRECISION NOT NULL,
    savings_percent      DOUBLE PRECISION NOT NULL,
    allocation_method    TEXT NOT NULL DEFAULT 'proportional_weight',
    notes                TEXT,
    created_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_shared_trips_farmer ON shared_trips(farmer_id);
CREATE INDEX IF NOT EXISTS idx_shared_trips_status ON shared_trips(status);

CREATE TABLE IF NOT EXISTS shared_trip_orders (
    id                     SERIAL PRIMARY KEY,
    trip_id                INTEGER NOT NULL REFERENCES shared_trips(id) ON DELETE CASCADE,
    order_id               INTEGER NOT NULL REFERENCES order_requests(id) ON DELETE CASCADE,
    stop_sequence          INTEGER NOT NULL DEFAULT 1,
    individual_distance_km DOUBLE PRECISION NOT NULL,
    individual_cost        DOUBLE PRECISION NOT NULL,
    allocated_cost         DOUBLE PRECISION NOT NULL,
    savings                DOUBLE PRECISION NOT NULL,
    savings_percent        DOUBLE PRECISION NOT NULL,
    UNIQUE (trip_id, order_id)
);
CREATE INDEX IF NOT EXISTS idx_trip_orders_trip ON shared_trip_orders(trip_id);
CREATE INDEX IF NOT EXISTS idx_trip_orders_order ON shared_trip_orders(order_id);

CREATE TABLE IF NOT EXISTS group_order_pools (
    id                   SERIAL PRIMARY KEY,
    pool_code            TEXT NOT NULL UNIQUE,
    listing_id           INTEGER NOT NULL REFERENCES crop_listings(id) ON DELETE CASCADE,
    farmer_id            INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    crop_name            TEXT NOT NULL,
    price_per_kg         DOUBLE PRECISION NOT NULL,
    target_delivery_area TEXT NOT NULL,
    target_lat           DOUBLE PRECISION NOT NULL,
    target_lng           DOUBLE PRECISION NOT NULL,
    min_total_kg         DOUBLE PRECISION NOT NULL DEFAULT 50.0,
    current_total_kg     DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    status               TEXT NOT NULL DEFAULT 'open'
                         CHECK (status IN ('open', 'target_reached', 'confirmed', 'completed', 'cancelled')),
    created_by_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    notes                TEXT,
    created_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_group_pools_listing ON group_order_pools(listing_id);
CREATE INDEX IF NOT EXISTS idx_group_pools_farmer ON group_order_pools(farmer_id);
CREATE INDEX IF NOT EXISTS idx_group_pools_status ON group_order_pools(status);

CREATE TABLE IF NOT EXISTS group_order_members (
    id                  SERIAL PRIMARY KEY,
    pool_id             INTEGER NOT NULL REFERENCES group_order_pools(id) ON DELETE CASCADE,
    buyer_id            INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    quantity_kg         DOUBLE PRECISION NOT NULL CHECK (quantity_kg > 0),
    delivery_preference TEXT NOT NULL DEFAULT 'delivery' CHECK (delivery_preference IN ('pickup', 'delivery')),
    delivery_address    TEXT,
    dest_lat            DOUBLE PRECISION,
    dest_lng            DOUBLE PRECISION,
    order_id            INTEGER REFERENCES order_requests(id) ON DELETE SET NULL,
    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_group_members_pool ON group_order_members(pool_id);
CREATE INDEX IF NOT EXISTS idx_group_members_buyer ON group_order_members(buyer_id);
"""


def is_postgres_url(path_or_url: str) -> bool:
    if not isinstance(path_or_url, str):
        return False
    return path_or_url.startswith(("postgres://", "postgresql://"))


def _convert_query(sql: str) -> str:
    """Translate SQLite parameter markers and syntax for PostgreSQL."""
    cleaned = sql.strip()
    # Ignore PRAGMA statements or sqlite_sequence cleanups on Postgres
    if cleaned.upper().startswith("PRAGMA") or "sqlite_sequence" in cleaned.lower():
        return ""
    # Translate INSERT OR IGNORE INTO
    if cleaned.upper().startswith("INSERT OR IGNORE INTO"):
        cleaned = "INSERT INTO" + cleaned[len("INSERT OR IGNORE INTO"):]
        if "ON CONFLICT" not in cleaned.upper():
            cleaned += " ON CONFLICT DO NOTHING"

    # Replace parameter markers (?) with (%s) outside literal quotes
    parts = []
    in_single = False
    in_double = False
    for ch in cleaned:
        if ch == "'" and not in_double:
            in_single = not in_single
            parts.append(ch)
        elif ch == '"' and not in_single:
            in_double = not in_double
            parts.append(ch)
        elif ch == "?" and not in_single and not in_double:
            parts.append("%s")
        else:
            parts.append(ch)
    return "".join(parts)


class PostgresCursorWrapper:
    """Wraps psycopg2 cursor to mirror sqlite3 cursor semantics (lastrowid, fetch, etc.)."""
    def __init__(self, raw_cursor):
        self.cur = raw_cursor
        self.lastrowid = None
        self._returned_row = None

    def execute(self, sql, params=None):
        sql_conv = _convert_query(sql)
        if not sql_conv:
            self.lastrowid = None
            self._returned_row = None
            return self

        stmt_upper = sql_conv.strip().upper()
        if stmt_upper == "BEGIN":
            self.cur.connection.autocommit = False
            return self
        elif stmt_upper == "COMMIT":
            self.cur.connection.commit()
            self.cur.connection.autocommit = True
            return self
        elif stmt_upper == "ROLLBACK":
            self.cur.connection.rollback()
            self.cur.connection.autocommit = True
            return self

        is_insert = sql_conv.strip().upper().startswith("INSERT INTO")
        has_returning = "RETURNING" in sql_conv.upper()
        if is_insert and not has_returning:
            sql_conv = sql_conv.rstrip("; \t\n") + " RETURNING id"

        if params is not None:
            self.cur.execute(sql_conv, params)
        else:
            self.cur.execute(sql_conv)

        if is_insert and not has_returning:
            try:
                row = self.cur.fetchone()
                if row:
                    self.lastrowid = row[0]
                    self._returned_row = row
            except Exception:
                self.lastrowid = None
                self._returned_row = None

        return self

    def executemany(self, sql, seq_of_parameters):
        sql_conv = _convert_query(sql)
        if not sql_conv:
            return self
        self.cur.executemany(sql_conv, seq_of_parameters)
        return self

    def fetchone(self):
        if self._returned_row is not None:
            r = self._returned_row
            self._returned_row = None
            return r
        try:
            return self.cur.fetchone()
        except Exception:
            return None

    def fetchall(self):
        if self._returned_row is not None:
            first = self._returned_row
            self._returned_row = None
            try:
                rest = self.cur.fetchall()
                return [first] + rest
            except Exception:
                return [first]
        try:
            return self.cur.fetchall()
        except Exception:
            return []

    def fetchmany(self, size=None):
        return self.cur.fetchmany(size) if size else self.cur.fetchmany()

    @property
    def rowcount(self):
        return self.cur.rowcount

    @property
    def description(self):
        return self.cur.description

    def close(self):
        self.cur.close()

    def __iter__(self):
        return iter(self.cur)


class PostgresConnectionWrapper:
    """Wraps psycopg2 connection with autocommit and sqlite3-like interface."""
    def __init__(self, raw_conn, uri=""):
        self.conn = raw_conn
        self._uri = uri
        self.conn.autocommit = True

    def cursor(self):
        return PostgresCursorWrapper(self.conn.cursor(cursor_factory=psycopg2_extras.DictCursor))

    def execute(self, sql, params=None):
        cur = self.cursor()
        return cur.execute(sql, params)

    def executemany(self, sql, seq_of_parameters):
        cur = self.cursor()
        return cur.executemany(sql, seq_of_parameters)

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.conn.close()

    def executescript(self, script):
        for stmt in script.split(";"):
            s = stmt.strip()
            if s:
                self.execute(s)


def connect(path_or_url):
    """Establish a connection to SQLite or managed PostgreSQL."""
    if is_postgres_url(path_or_url):
        if psycopg2 is None:
            raise RuntimeError(
                "psycopg2-binary is required to connect to PostgreSQL. "
                "Ensure it is installed from requirements.txt."
            )
        # Normalize postgres:// to postgresql:// if needed
        dsn = path_or_url
        if dsn.startswith("postgres://"):
            dsn = "postgresql://" + dsn[len("postgres://"):]
        raw_conn = psycopg2.connect(dsn)
        return PostgresConnectionWrapper(raw_conn, uri=path_or_url)

    # Standard SQLite connection
    conn = sqlite3.connect(path_or_url, timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(path_or_url):
    """Idempotently initialize tables and indexes."""
    if is_postgres_url(path_or_url):
        conn = connect(path_or_url)
        conn.executescript(POSTGRES_SCHEMA)
        conn.close()
    else:
        conn = connect(path_or_url)
        conn.executescript(SCHEMA)
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(order_requests)").fetchall()]
        if "delivery_address" not in cols:
            conn.execute("ALTER TABLE order_requests ADD COLUMN delivery_address TEXT")
        if "delivery_lat" not in cols:
            conn.execute("ALTER TABLE order_requests ADD COLUMN delivery_lat REAL")
        if "delivery_lng" not in cols:
            conn.execute("ALTER TABLE order_requests ADD COLUMN delivery_lng REAL")
        conn.close()


@contextmanager
def transaction(db):
    """Context manager for atomic write transactions."""
    if isinstance(db, PostgresConnectionWrapper):
        db.conn.autocommit = False
        try:
            yield db
            db.conn.commit()
        except BaseException:
            db.conn.rollback()
            raise
        finally:
            db.conn.autocommit = True
    else:
        db.execute("BEGIN IMMEDIATE")
        try:
            yield db
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise


def init_app(app):
    app.teardown_appcontext(close_db)
