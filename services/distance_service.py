"""Distance and transport-cost estimates. Straight-line (Haversine) distance only."""
import math
from decimal import Decimal

from .money import q2, to_decimal

EARTH_RADIUS_KM = 6371.0088


def valid_coords(lat, lng) -> bool:
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError):
        return False
    return (math.isfinite(lat) and math.isfinite(lng)
            and -90 <= lat <= 90 and -180 <= lng <= 180)


def haversine_km(lat1, lng1, lat2, lng2):
    """Great-circle distance in km, or None if either point is invalid."""
    if not (valid_coords(lat1, lng1) and valid_coords(lat2, lng2)):
        return None
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dphi = p2 - p1
    dlmb = math.radians(float(lng2) - float(lng1))
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def transport_cost(distance_km, rate_per_km) -> Decimal:
    """Estimated transport cost = distance (km) x rate (INR/km). An estimate, not a quote."""
    return q2(to_decimal(round(distance_km, 2)) * to_decimal(rate_per_km))


def delivered_cost(product_cost, transport) -> Decimal:
    return q2(to_decimal(product_cost) + to_decimal(transport))


# Approximate centre points (rounded) of towns around Greater Noida, for manual location entry.
PRESET_LOCATIONS = [
    ("Greater Noida (Pari Chowk area)", 28.4744, 77.5040),
    ("Noida (Sector 62 area)", 28.6270, 77.3650),
    ("Dadri", 28.5530, 77.5540),
    ("Surajpur", 28.5133, 77.5177),
    ("Dankaur", 28.3600, 77.5530),
    ("Jewar", 28.1270, 77.5570),
    ("Ghaziabad (centre)", 28.6692, 77.4538),
]
