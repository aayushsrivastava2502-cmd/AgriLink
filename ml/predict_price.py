"""Load the trained model (if any) and predict a reference price in INR/kg."""
import json
import os

import joblib
import pandas as pd

from .features import FEATURES, daily_series, load_history, normalize_name


def load_metadata(model_dir):
    path = os.path.join(model_dir, "metadata.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_model(model_dir):
    path = os.path.join(model_dir, "price_model.joblib")
    return joblib.load(path) if os.path.exists(path) else None


def predict(db_path, model_dir, commodity, market, target_date):
    """Returns a dict, or None when the model/history cannot support this crop."""
    meta, model = load_metadata(model_dir), load_model(model_dir)
    if meta is None or model is None or commodity not in meta["commodity_codes"]:
        return None
    hist = daily_series(load_history(db_path, commodity))
    hist = hist[hist.price_date < pd.Timestamp(target_date)]
    if hist.empty:
        return None
    market = normalize_name(market)
    fallback = False
    known = [m for m in hist.market.unique() if m in meta["market_codes"]]
    if not known:
        return None
    if market not in known:
        market = hist[hist.market.isin(known)].market.value_counts().idxmax()
        fallback = True
    series = hist[hist.market == market].sort_values("price_date")["price"]
    last_date = hist[hist.market == market].price_date.max()
    row = pd.DataFrame([{
        "last_price": series.iloc[-1], "roll7": series.tail(7).mean(), "roll30": series.tail(30).mean(),
        "month": target_date.month, "dayofyear": target_date.timetuple().tm_yday,
        "commodity_code": meta["commodity_codes"][commodity], "market_code": meta["market_codes"][market],
    }])[FEATURES]
    return {"price": float(model.predict(row)[0]), "market_used": market, "market_fallback": fallback,
            "last_observation": last_date.date().isoformat(),
            "staleness_days": (pd.Timestamp(target_date) - last_date).days, "observations": int(len(series))}
