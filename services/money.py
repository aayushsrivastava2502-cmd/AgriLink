"""Rupee helpers. All money maths uses Decimal; amounts are INR, prices are INR per kg."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

TWO = Decimal("0.01")


def to_decimal(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def q2(value) -> Decimal:
    return to_decimal(value).quantize(TWO, rounding=ROUND_HALF_UP)


def inr(value, force_decimals=False) -> str:
    """Indian digit grouping: 125000 -> ₹1,25,000 ; 24.5 -> ₹24.50"""
    if value is None:
        return "—"
    d = q2(value)
    sign = "-" if d < 0 else ""
    whole, frac = f"{abs(d):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    if frac == "00" and not force_decimals:
        return f"{sign}₹{whole}"
    return f"{sign}₹{whole}.{frac}"


def per_kg(value) -> str:
    return f"{inr(value)}/kg"


def kg(value) -> str:
    if value is None:
        return "—"
    d = to_decimal(value).quantize(TWO)
    text = f"{d:f}".rstrip("0").rstrip(".")
    return f"{text} kg"


def quintal_to_kg(price_per_quintal) -> Decimal:
    """1 quintal = 100 kg, so Rs/kg = Rs/quintal / 100."""
    return to_decimal(price_per_quintal) / Decimal(100)


def parse_decimal(raw, label, *, minimum=None, maximum=None, inclusive_min=False,
                  places=2, required=True):
    """Parse user input into a Decimal or raise ValueError with a readable message."""
    raw = (raw or "").strip().replace(",", "")
    if not raw:
        if required:
            raise ValueError(f"{label} is required.")
        return None
    try:
        d = Decimal(raw)
    except InvalidOperation:
        raise ValueError(f"{label} must be a number.")
    if not d.is_finite():
        raise ValueError(f"{label} must be a number.")
    if -d.as_tuple().exponent > places:
        raise ValueError(f"{label} can have at most {places} decimal places.")
    if minimum is not None:
        if d < minimum or (d == minimum and not inclusive_min):
            word = "at least" if inclusive_min else "greater than"
            raise ValueError(f"{label} must be {word} {minimum}.")
    if maximum is not None and d > maximum:
        raise ValueError(f"{label} must not exceed {maximum}.")
    return d
