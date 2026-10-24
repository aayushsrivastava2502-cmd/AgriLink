from functools import wraps

from flask import abort, flash, g, redirect, request, session, url_for

from services.distance_service import valid_coords


def login_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if g.user is None:
            flash("Please log in to continue.", "info")
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        return view(*a, **kw)
    return wrapped


def role_required(role):
    def deco(view):
        @wraps(view)
        @login_required
        def wrapped(*a, **kw):
            if g.user["role"] != role:
                abort(403)
            return view(*a, **kw)
        return wrapped
    return deco


def safe_next(target):
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return None


def get_location():
    """Buyer's chosen location: (lat, lng, label) from query string (then remembered in session) or None."""
    if request.args.get("clear_loc"):
        session.pop("loc", None)
    lat, lng = request.args.get("lat", "").strip(), request.args.get("lng", "").strip()
    if lat and lng and valid_coords(lat, lng):
        session["loc"] = {"lat": float(lat), "lng": float(lng),
                          "label": (request.args.get("loc_label") or "").strip()[:60]}
    loc = session.get("loc")
    return (loc["lat"], loc["lng"], loc.get("label", "")) if loc else None
