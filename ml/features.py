"""Shared data preparation for the price model (Pandas)."""
import re
import sqlite3

import pandas as pd

FEATURES = ["last_price", "roll7", "roll30", "month", "dayofyear", "commodity_code", "market_code"]

_ALIASES = {
    "tomatoes": "Tomato", "tomato": "Tomato", "potatoes": "Potato", "potato": "Potato",
    "onions": "Onion", "onion": "Onion", "green peas": "Green Peas", "peas(green)": "Green Peas",
    "peas (green)": "Green Peas", "green pea": "Green Peas", "mustard seed": "Mustard",
    "mustard": "Mustard", "cauliflower": "Cauliflower", "wheat": "Wheat", "rice": "Rice",
}


def normalize_name(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().title()


def normalize_crop(value) -> str:
    key = re.sub(r"\s+", " ", str(value or "")).strip().lower()
    return _ALIASES.get(key, normalize_name(value))


def load_history(db_path, commodity=None):
    sql = ("SELECT commodity, market, price_date, modal_price_per_kg AS price FROM price_history")
    params = []
    if commodity:
        sql += " WHERE commodity = ?"
        params.append(commodity)
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(sql, conn, params=params, parse_dates=["price_date"])
    finally:
        conn.close()
    return df


def daily_series(df):
    """One row per commodity/market/day (mean modal price in INR/kg)."""
    return (df.groupby(["commodity", "market", "price_date"], as_index=False)["price"].mean()
              .sort_values(["commodity", "market", "price_date"]))


def build_dataset(df, commodity_codes=None, market_codes=None):
    """Lag features use only PAST observations (shift(1)) so nothing leaks from the target day."""
    daily = daily_series(df)
    commodity_codes = commodity_codes or {c: i for i, c in enumerate(sorted(daily.commodity.unique()))}
    market_codes = market_codes or {m: i for i, m in enumerate(sorted(daily.market.unique()))}
    frames = []
    for _, g in daily.groupby(["commodity", "market"], sort=False):
        g = g.sort_values("price_date").copy()
        past = g["price"].shift(1)
        g["last_price"] = past
        g["roll7"] = past.rolling(7, min_periods=1).mean()
        g["roll30"] = past.rolling(30, min_periods=1).mean()
        frames.append(g)
    out = pd.concat(frames, ignore_index=True).dropna(subset=["last_price"])
    out["month"] = out["price_date"].dt.month
    out["dayofyear"] = (out["price_date"].dt.day_of_year
                        if hasattr(out["price_date"].dt, "day_of_year")
                        else out["price_date"].dt.dayofyear)
    out["commodity_code"] = out["commodity"].map(commodity_codes)
    out["market_code"] = out["market"].map(market_codes)
    return out.dropna(subset=["commodity_code", "market_code"]), commodity_codes, market_codes
