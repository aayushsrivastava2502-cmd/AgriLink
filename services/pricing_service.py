"""Smart Price Estimator: dataset import, reference-price lookup and comparison.

Order of preference (always labelled in the result so nothing is passed off as something it is not):
  1. 'model'    - RandomForestRegressor trained AND evaluated on imported mandi data
  2. 'history'  - mean of the most recent imported mandi observations (no model needed)
  3. 'demo'     - illustrative demonstration value from market_references (NOT real market data)
"""
import re
from datetime import date
from decimal import Decimal

import pandas as pd

from ml.features import normalize_crop, normalize_name
from ml import predict_price
from .money import q2, quintal_to_kg, to_decimal

SEASONS = {12: "Winter", 1: "Winter", 2: "Winter", 3: "Summer", 4: "Summer", 5: "Summer", 6: "Summer",
           7: "Monsoon", 8: "Monsoon", 9: "Monsoon", 10: "Post-monsoon", 11: "Post-monsoon"}
QUALITY_FACTOR = {"Premium": Decimal("1.08"), "Standard": Decimal("1.00"), "Basic": Decimal("0.92")}

# Illustrative demonstration references (INR/kg) + Jan..Dec seasonal multipliers. NOT real prices.
DEMO_REFERENCES = {
    "Wheat": (26, "1.00,1.00,0.98,0.95,0.97,1.00,1.02,1.03,1.03,1.02,1.01,1.00"),
    "Rice": (38, "1.00,1.00,1.00,1.00,1.00,1.01,1.02,1.03,1.03,1.00,0.97,0.98"),
    "Tomato": (22, "0.95,0.90,0.85,0.90,1.00,1.20,1.45,1.35,1.15,1.00,0.95,0.95"),
    "Potato": (18, "0.90,0.88,0.90,0.95,1.05,1.12,1.15,1.12,1.08,1.00,0.95,0.92"),
    "Onion": (24, "0.95,0.92,0.90,0.92,1.00,1.08,1.15,1.20,1.18,1.10,1.00,0.97"),
    "Mustard": (58, "0.98,0.96,0.94,0.95,0.98,1.00,1.02,1.03,1.04,1.04,1.02,1.00"),
    "Cauliflower": (28, "0.85,0.85,0.95,1.10,1.25,1.30,1.25,1.15,1.05,0.95,0.88,0.85"),
    "Green Peas": (55, "0.85,0.88,0.95,1.10,1.25,1.30,1.30,1.25,1.15,1.05,0.92,0.85"),
}

_COLS = {"state": ["state"], "market": ["market"], "commodity": ["commodity"],
         "date": ["arrivaldate", "pricedate", "date"],
         "min": ["minprice", "min"], "max": ["maxprice", "max"], "modal": ["modalprice", "modal"]}


def seed_market_references(db):
    for crop, (base, factors) in DEMO_REFERENCES.items():
        db.execute("INSERT OR IGNORE INTO market_references (crop_name, base_price_per_kg, month_factors, note)"
                   " VALUES (?,?,?,?)", (crop, base, factors, "Illustrative demonstration value, not a market price"))


def _find_columns(columns):
    norm = {c: re.sub(r"[^a-z0-9]", "", str(c).lower()) for c in columns}
    found = {}
    for key, cands in _COLS.items():
        for c, n in norm.items():
            if any(n == cand or n.startswith(cand) for cand in cands):
                found.setdefault(key, c)
                break
    missing = [k for k in ("market", "commodity", "date", "modal") if k not in found]
    if missing:
        raise ValueError("CSV is missing required columns: " + ", ".join(missing) +
                         ". Expected AGMARKNET/data.gov.in columns such as Market, Commodity, "
                         "Arrival_Date, Modal_Price.")
    return found


def import_mandi_csv(db, path, source=None, unit="quintal"):
    """Clean an AGMARKNET/data.gov.in CSV and store it in price_history as INR/kg.

    unit='quintal' (default, as published) divides prices by 100; unit='kg' stores them unchanged.
    """
    if unit not in ("quintal", "kg"):
        raise ValueError("unit must be 'quintal' or 'kg'")
    df = pd.read_csv(path)
    cols = _find_columns(df.columns)
    read = len(df)
    out = pd.DataFrame({
        "commodity": df[cols["commodity"]].map(normalize_crop),
        "market": df[cols["market"]].map(normalize_name),
        "state": df[cols["state"]].map(normalize_name) if "state" in cols else None,
        "price_date": pd.to_datetime(df[cols["date"]], dayfirst=True, errors="coerce"),
        "modal": pd.to_numeric(df[cols["modal"]], errors="coerce"),
        "min": pd.to_numeric(df[cols["min"]], errors="coerce") if "min" in cols else float("nan"),
        "max": pd.to_numeric(df[cols["max"]], errors="coerce") if "max" in cols else float("nan"),
    })
    out = out.dropna(subset=["commodity", "market", "price_date", "modal"])
    out = out[(out.modal > 0) & (out.commodity != "") & (out.market != "")]
    divisor = Decimal(100) if unit == "quintal" else Decimal(1)
    src = source or re.sub(r".*[\\/]", "", str(path))
    rows = []
    for r in out.itertuples(index=False):
        conv = lambda v: None if pd.isna(v) or v <= 0 else float(q2(to_decimal(v) / divisor))
        modal = conv(r.modal)
        if modal:
            rows.append((r.commodity, r.market, r.state if isinstance(r.state, str) else None,
                         r.price_date.date().isoformat(), conv(r.min), conv(r.max), modal, src))
    before = db.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
    db.execute("BEGIN")
    db.executemany("INSERT OR IGNORE INTO price_history (commodity, market, state, price_date,"
                   " min_price_per_kg, max_price_per_kg, modal_price_per_kg, source) VALUES (?,?,?,?,?,?,?,?)", rows)
    db.execute("COMMIT")
    imported = db.execute("SELECT COUNT(*) FROM price_history").fetchone()[0] - before
    return {"source": src, "rows_read": read, "rows_valid": len(rows), "rows_imported": imported,
            "rows_dropped": read - len(rows), "unit": unit}


def _compare(reference, asking):
    if reference is None or asking is None:
        return {}
    ref, ask = q2(reference), q2(asking)
    diff = q2(ask - ref)
    pct = q2(diff / ref * 100) if ref > 0 else None
    if pct is None:
        verdict = "unknown"
    elif abs(pct) <= 10:
        verdict = "close"
    else:
        verdict = "above" if pct > 0 else "below"
    return {"asking": ask, "difference": diff, "percent": pct, "verdict": verdict}


def _sources(db, commodity):
    return [r[0] for r in db.execute("SELECT DISTINCT source FROM price_history WHERE commodity=?", (commodity,))]


def estimate(db, db_path, model_dir, crop, market, target_date=None, quantity=None, quality=None, asking=None):
    target_date = target_date or date.today()
    commodity = normalize_crop(crop)
    market_n = normalize_name(market)
    res = {"crop": commodity, "market": market_n or None, "date": target_date, "quantity": quantity,
           "quality": quality, "season": SEASONS[target_date.month], "mode": None, "reference": None,
           "ref_date": None, "source": None, "explanation": "", "warnings": [], "metrics": None}
    meta = predict_price.load_metadata(model_dir)
    pred = None
    try:
        pred = predict_price.predict(db_path, model_dir, commodity, market_n, target_date)
    except Exception as exc:  # a broken model file must not break the page
        res["warnings"].append(f"The trained model could not be used ({type(exc).__name__}).")

    if pred:
        res.update(mode="model", reference=q2(pred["price"]), ref_date=pred["last_observation"],
                   market=pred["market_used"], source=", ".join(_sources(db, commodity)),
                   metrics={k: meta[k] for k in ("mae_per_kg", "baseline_last_price_mae_per_kg", "test_rows",
                                                 "split_date", "data_from", "data_to", "trained_at")})
        res["explanation"] = (f"A RandomForestRegressor trained on imported mandi history predicted the modal "
                              f"price for {commodity} at {pred['market_used']} for {target_date:%d %b %Y}, using "
                              f"the latest observed prices ({pred['observations']} observations) and the month.")
        if pred["market_fallback"]:
            res["warnings"].append(f"'{market_n or 'Your market'}' is not in the dataset, so "
                                   f"{pred['market_used']} was used instead.")
        if pred["staleness_days"] > 30:
            res["warnings"].append(f"The newest observation is {pred['staleness_days']} days old; "
                                   "accuracy drops as data gets stale.")
        if "synthetic" in (res["source"] or "").lower():
            res["warnings"].append("This model was trained on SYNTHETIC test data, so the number is not a real "
                                   "market price.")
        res["warnings"].append("Quality and quantity are not model inputs; the estimate is a modal market price.")
    else:
        hist = db.execute(
            "SELECT price_date, modal_price_per_kg, market FROM price_history WHERE commodity=?"
            " AND price_date<=? ORDER BY price_date DESC LIMIT 400", (commodity, target_date.isoformat())).fetchall()
        mrows = [h for h in hist if h["market"] == market_n][:30] or hist[:30]
        if mrows:
            avg = sum(to_decimal(h["modal_price_per_kg"]) for h in mrows) / len(mrows)
            res.update(mode="history", reference=q2(avg), ref_date=mrows[0]["price_date"],
                       source=", ".join(_sources(db, commodity)))
            res["explanation"] = (f"Average of the {len(mrows)} most recent imported mandi observations for "
                                  f"{commodity}. No model has been trained, so this is a simple average, not a prediction.")
            res["warnings"].append("No trained model is available for this crop; showing a recent average instead.")
            if "synthetic" in res["source"].lower():
                res["warnings"].append("The data is SYNTHETIC test data, not real market prices.")
        else:
            ref = db.execute("SELECT * FROM market_references WHERE crop_name=?", (commodity,)).fetchone()
            if ref:
                factor = Decimal(ref["month_factors"].split(",")[target_date.month - 1])
                qf = QUALITY_FACTOR.get(quality or "", Decimal(1))
                res.update(mode="demo", reference=q2(to_decimal(ref["base_price_per_kg"]) * factor * qf),
                           source="Built-in illustrative values (demonstration mode)")
                res["explanation"] = (f"Base illustrative price × {factor} seasonal factor ({res['season']}) × {qf} "
                                      "quality factor. No mandi dataset has been imported.")
                res["warnings"].append("DEMONSTRATION MODE: illustrative values, not real or current market prices. "
                                       "No machine-learning model was used.")
                res["warnings"].append("Import AGMARKNET / data.gov.in data and train the model to get a data-based estimate.")
            else:
                res["explanation"] = f"There is no reference data for '{commodity}'."
                res["warnings"].append("Try one of the supported crops, or import mandi data that includes this crop.")
    res.update(_compare(res["reference"], asking))
    return res


def model_status(model_dir):
    return predict_price.load_metadata(model_dir)


def known_crops(db):
    names = {r[0] for r in db.execute("SELECT crop_name FROM market_references")}
    names |= {r[0] for r in db.execute("SELECT DISTINCT commodity FROM price_history")}
    names |= {r[0] for r in db.execute("SELECT DISTINCT crop_name FROM crop_listings")}
    return sorted(names)


def known_markets(db):
    return sorted({r[0] for r in db.execute("SELECT DISTINCT market FROM price_history")}
                  | {r[0] for r in db.execute("SELECT DISTINCT city FROM crop_listings")})
