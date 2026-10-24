"""Re-evaluate the saved model on its chronological hold-out (dates >= split_date).

Usage:  python -m ml.evaluate_model
"""
import json
import sys

import pandas as pd
from sklearn.metrics import mean_absolute_error

from .features import FEATURES, build_dataset, load_history
from .predict_price import load_metadata, load_model


def evaluate(db_path, model_dir):
    meta, model = load_metadata(model_dir), load_model(model_dir)
    if meta is None or model is None:
        return None
    data, _, _ = build_dataset(load_history(db_path), meta["commodity_codes"], meta["market_codes"])
    test = data[data.price_date >= pd.Timestamp(meta["split_date"])]
    if test.empty:
        return None
    return {"test_rows": int(len(test)), "split_date": meta["split_date"],
            "mae_per_kg": round(float(mean_absolute_error(test["price"], model.predict(test[FEATURES]))), 4),
            "baseline_last_price_mae_per_kg": round(float(mean_absolute_error(test["price"], test["last_price"])), 4)}


if __name__ == "__main__":
    from config import Config
    result = evaluate(Config.DATABASE, Config.MODEL_DIR)
    if result is None:
        print("No trained model found (or no hold-out rows). Train one first: python -m ml.train_model")
        sys.exit(1)
    print(json.dumps(result, indent=2))
