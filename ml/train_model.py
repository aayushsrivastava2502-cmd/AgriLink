"""Train a RandomForestRegressor on price_history (INR/kg). Only trains when enough data exists.

Usage:  python -m ml.train_model            (uses instance/agrilink.db)
"""
import json
import os
import sys
from datetime import datetime, timezone

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error

from .features import FEATURES, build_dataset, load_history

MIN_ROWS, MIN_DATES, MIN_TEST_ROWS = 300, 60, 50


class InsufficientData(Exception):
    pass


def train(db_path, model_dir, sources=None):
    df = load_history(db_path)
    if df.empty:
        raise InsufficientData("price_history is empty. Import a mandi dataset first "
                               "(flask --app app import-mandi <file.csv>).")
    data, ccodes, mcodes = build_dataset(df)
    n_dates = data["price_date"].nunique()
    if len(data) < MIN_ROWS or n_dates < MIN_DATES:
        raise InsufficientData(f"Not enough data to train: {len(data)} usable rows over {n_dates} "
                               f"dates (need at least {MIN_ROWS} rows and {MIN_DATES} dates).")
    dates = sorted(data["price_date"].unique())
    split_date = pd.Timestamp(dates[int(len(dates) * 0.8)])       # chronological 80/20 split
    train_df, test_df = data[data.price_date < split_date], data[data.price_date >= split_date]
    if len(test_df) < MIN_TEST_ROWS or train_df.empty:
        raise InsufficientData("Not enough rows after the chronological train/test split.")

    model = RandomForestRegressor(n_estimators=100, min_samples_leaf=5, max_features=0.7, random_state=42, n_jobs=-1)
    model.fit(train_df[FEATURES], train_df["price"])
    mae = float(mean_absolute_error(test_df["price"], model.predict(test_df[FEATURES])))
    baseline_mae = float(mean_absolute_error(test_df["price"], test_df["last_price"]))

    meta = {
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "algorithm": "RandomForestRegressor(n_estimators=100, min_samples_leaf=5, max_features=0.7)",
        "target": "modal price, INR per kg (converted from INR per quintal)",
        "features": FEATURES, "train_rows": int(len(train_df)), "test_rows": int(len(test_df)),
        "split_date": split_date.date().isoformat(),
        "data_from": data.price_date.min().date().isoformat(),
        "data_to": data.price_date.max().date().isoformat(),
        "mae_per_kg": round(mae, 4), "baseline_last_price_mae_per_kg": round(baseline_mae, 4),
        "commodities": sorted(ccodes), "markets": sorted(mcodes), "sources": sources or [],
        "commodity_codes": ccodes, "market_codes": mcodes,
    }
    os.makedirs(model_dir, exist_ok=True)
    joblib.dump(model, os.path.join(model_dir, "price_model.joblib"), compress=3)
    with open(os.path.join(model_dir, "metadata.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
    return meta


if __name__ == "__main__":
    from config import Config
    from models import connect
    conn = connect(Config.DATABASE)
    srcs = [r[0] for r in conn.execute("SELECT DISTINCT source FROM price_history")]
    conn.close()
    try:
        info = train(Config.DATABASE, Config.MODEL_DIR, srcs)
    except InsufficientData as exc:
        print("NOT TRAINED:", exc)
        sys.exit(1)
    print(json.dumps({k: v for k, v in info.items() if k not in ("commodity_codes", "market_codes")}, indent=2))
