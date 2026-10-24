"""Generate a SYNTHETIC AGMARKNET-style CSV (prices in INR/quintal) to test the import/training
pipeline end to end. It is random data with a seasonal pattern - NOT real market prices.

Usage:  python -m ml.make_sample_dataset
"""
import math
import os
import random
import zlib

import pandas as pd

BASE = {"Wheat": 2600, "Rice": 3900, "Tomato": 2200, "Potato": 1800, "Onion": 2400,
        "Mustard": 5800, "Cauliflower": 2800, "Green Peas": 5500}
MARKETS = [("Uttar Pradesh", "Gautam Buddha Nagar", "Dadri"), ("Uttar Pradesh", "Ghaziabad", "Ghaziabad"),
           ("Uttar Pradesh", "Bulandshahr", "Khurja")]


def make(path, seed=7, days=730):
    rng = random.Random(seed)
    rows = []
    end = pd.Timestamp.today().normalize() - pd.Timedelta(days=1)
    for d in pd.date_range(end - pd.Timedelta(days=days), end, freq="D"):
        if d.weekday() == 6:
            continue
        for crop, base in BASE.items():
            for state, district, market in MARKETS:
                doy = d.day_of_year if hasattr(d, "day_of_year") else d.dayofyear
                season = 1 + 0.18 * math.sin(2 * math.pi * (doy / 365) + zlib.crc32(crop.encode()) % 7)
                level = base * season * (1 + 0.03 * (zlib.crc32(market.encode()) % 5 - 2) / 2)
                modal = max(100, level * (1 + rng.gauss(0, 0.04)))
                rows.append([state, district, market, crop, "Other", "FAQ", d.strftime("%d/%m/%Y"),
                             round(modal * 0.92), round(modal * 1.08), round(modal)])
    pd.DataFrame(rows, columns=["State", "District", "Market", "Commodity", "Variety", "Grade",
                                "Arrival_Date", "Min_Price", "Max_Price", "Modal_Price"]).to_csv(path, index=False)
    return len(rows)


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(__file__), "..", "data", "SYNTHETIC_sample_mandi.csv")
    print(make(out), "synthetic rows written to", os.path.abspath(out))
