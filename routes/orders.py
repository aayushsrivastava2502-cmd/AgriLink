from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for

from models import get_db, order as O
from services.i18n import _
from .helpers import login_required, role_required, safe_next

bp = Blueprint("orders", __name__)

STATUSES = ("pending", "accepted", "completed", "rejected", "cancelled")


@bp.route("/buyer/dashboard")
@role_required("buyer")
def buyer_dashboard():
    db = get_db()
    stats = O.buyer_stats(db, g.user["id"])
    chart = {"type": "bar", "labels": [_(s) for s in STATUSES], "data": [stats["counts"].get(s, 0) for s in STATUSES],
             "label": _("My order requests")}
    return render_template("buyer_dashboard.html", stats=stats, orders=O.orders_for(db, g.user["id"], "buyer", limit=6),
                           chart=chart)


@bp.route("/orders")
@login_required
def list_orders():
    status = request.args.get("status") if request.args.get("status") in STATUSES else None
    rows = O.orders_for(get_db(), g.user["id"], g.user["role"], status)
    return render_template("orders.html", orders=rows, status=status, statuses=STATUSES)


@bp.route("/listing/<int:listing_id>/order", methods=["POST"])
@role_required("buyer")
def create(listing_id):
    clean, errors = O.validate_order_input(request.form)
    if clean.get("delivery_preference") == "delivery" and not clean.get("delivery_lat"):
        loc = session.get("loc")
        if loc and loc.get("lat") and loc.get("lng"):
            clean["delivery_lat"] = loc["lat"]
            clean["delivery_lng"] = loc["lng"]
            if not clean.get("delivery_address"):
                clean["delivery_address"] = loc.get("label") or f"{g.user['city']}, {g.user['state']}"
        elif not clean.get("delivery_address"):
            clean["delivery_address"] = f"{g.user['city']}, {g.user['state']}"
    if errors:
        flash(" ".join(errors.values()), "error")
        return redirect(url_for("main.product_detail", listing_id=listing_id) + "#order")
    try:
        O.create_order(get_db(), g.user["id"], listing_id, clean)
    except O.OrderError as exc:
        flash(str(exc), "error")
        return redirect(url_for("main.product_detail", listing_id=listing_id) + "#order")
    flash("Order request sent. The farmer will accept or reject it; no payment is taken in this prototype.", "success")
    return redirect(url_for("orders.list_orders"))


def _transition(action, role):
    @role_required(role)
    def view(order_id):
        try:
            getattr(O, action)(get_db(), order_id, g.user["id"])
            flash({"accept": "Order accepted and stock reserved.", "reject": "Order rejected.",
                   "complete": "Order marked as completed.", "cancel": "Order request cancelled."}[action], "success")
        except O.OrderError as exc:
            flash(str(exc), "error")
        return redirect(safe_next(request.form.get("back")) or url_for("orders.list_orders"))
    view.__name__ = f"{action}_order"
    bp.add_url_rule(f"/orders/<int:order_id>/{action}", view_func=view, methods=["POST"])


for _action, _role in (("accept", "farmer"), ("reject", "farmer"), ("complete", "farmer"), ("cancel", "buyer")):
    _transition(_action, _role)
