from datetime import date

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for

from models import CATEGORIES, QUALITIES, get_db, listing as L, order as O
from services.i18n import _
from services.pricing_service import known_crops
from .helpers import role_required

bp = Blueprint("farmer", __name__, url_prefix="/farmer")


def _form_context(**extra):
    return dict(categories=CATEGORIES, qualities=QUALITIES, today=date.today().isoformat(),
                crops=known_crops(get_db()), **extra)


def _own_listing_or_abort(listing_id):
    listing = L.get_listing(get_db(), listing_id)
    if listing is None:
        abort(404)
    if listing["farmer_id"] != g.user["id"]:
        abort(403)
    return listing


@bp.route("/dashboard")
@role_required("farmer")
def dashboard():
    db = get_db()
    listings = L.farmer_listings(db, g.user["id"])
    value_by_crop = {}
    for l in listings:
        if l["status"] == "active":
            value_by_crop[l["crop_name"]] = value_by_crop.get(l["crop_name"], 0) + l["quantity_kg"] * l["price_per_kg"]
    chart = {"type": "doughnut", "labels": [_(c) for c in value_by_crop], "data": [round(v, 2) for v in value_by_crop.values()],
             "label": _("Value of available stock (₹)")}
    return render_template("farmer_dashboard.html", stats=L.farmer_stats(db, g.user["id"]), listings=listings,
                           pending=O.orders_for(db, g.user["id"], "farmer", "pending"),
                           accepted=O.orders_for(db, g.user["id"], "farmer", "accepted"), chart=chart)


def _handle_form(listing=None):
    clean, errors = L.validate_listing(request.form)
    image_url = clean["image_url"] or (listing["image_url"] if listing and not request.form.get("remove_image") else None)
    try:
        uploaded = L.save_upload(request.files.get("image_file"), current_app.config["UPLOAD_FOLDER"]) \
            if not errors else None
        if uploaded:
            image_url = uploaded
    except ValueError as exc:
        errors["image_file"] = str(exc)
    return clean, errors, image_url


@bp.route("/listings/new", methods=["GET", "POST"])
@role_required("farmer")
def add_listing():
    errors, values = {}, {"city": g.user["city"], "state": g.user["state"], "quality": "Standard"}
    if request.method == "POST":
        clean, errors, image_url = _handle_form()
        values = request.form
        if not errors:
            L.create_listing(get_db(), g.user["id"], clean, image_url)
            flash("Your crop listing is live in the marketplace.", "success")
            return redirect(url_for("farmer.dashboard"))
        flash("Please fix the highlighted fields.", "error")
    return render_template("add_listing.html", errors=errors, values=values, **_form_context())


@bp.route("/listings/<int:listing_id>/edit", methods=["GET", "POST"])
@role_required("farmer")
def edit_listing(listing_id):
    listing = _own_listing_or_abort(listing_id)
    errors, values = {}, dict(listing)
    if request.method == "POST":
        clean, errors, image_url = _handle_form(listing)
        values = request.form
        if not errors:
            L.update_listing(get_db(), listing_id, g.user["id"], clean, image_url)
            flash("Listing updated.", "success")
            return redirect(url_for("farmer.dashboard"))
        flash("Please fix the highlighted fields.", "error")
    return render_template("edit_listing.html", listing=listing, errors=errors, values=values, **_form_context())


@bp.route("/listings/<int:listing_id>/delete", methods=["POST"])
@role_required("farmer")
def delete_listing(listing_id):
    _own_listing_or_abort(listing_id)
    result = L.delete_listing(get_db(), listing_id, g.user["id"])
    if result == "deleted":
        flash("Listing deleted.", "success")
    elif result == "has_open_orders":
        flash("This listing has pending or accepted orders. Resolve them first, or mark it unavailable.", "error")
    else:
        abort(404)
    return redirect(url_for("farmer.dashboard"))


@bp.route("/listings/<int:listing_id>/toggle", methods=["POST"])
@role_required("farmer")
def toggle_listing(listing_id):
    _own_listing_or_abort(listing_id)
    status = L.toggle_availability(get_db(), listing_id, g.user["id"])
    messages = {"active": "Listing is available again.", "unavailable": "Listing marked unavailable.",
                "sold_out": "This listing is sold out. Edit the quantity to restock it."}
    flash(messages.get(status, "Listing updated."), "success" if status != "sold_out" else "info")
    return redirect(url_for("farmer.dashboard"))
