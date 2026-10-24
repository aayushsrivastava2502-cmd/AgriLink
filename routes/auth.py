from flask import Blueprint, flash, redirect, render_template, request, session, url_for, g

from models import get_db, user as U
from .helpers import safe_next

bp = Blueprint("auth", __name__)


def _home_for(role):
    return url_for("farmer.dashboard" if role == "farmer" else "orders.buyer_dashboard")


@bp.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(_home_for(g.user["role"]))
    errors, values = {}, {}
    if request.method == "POST":
        clean, password, errors = U.validate_registration(request.form)
        values = clean
        if not errors:
            uid = U.create_user(get_db(), clean, password)
            if uid is None:
                errors["email"] = "An account with this email already exists. Try logging in."
            else:
                lang = session.get("lang")
                session.clear()
                if lang:
                    session["lang"] = lang
                session["user_id"] = uid
                session.permanent = True
                flash(f"Welcome to AgriLink AI, {clean['full_name'].split()[0]}!", "success")
                return redirect(_home_for(clean["role"]))
        flash("Please fix the highlighted fields.", "error")
    else:
        values = {"role": request.args.get("role", "buyer")}
    return render_template("register.html", errors=errors, values=values)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(_home_for(g.user["role"]))
    if request.method == "POST":
        user = U.authenticate(get_db(), request.form.get("email"), request.form.get("password"))
        if user is None:
            flash("Incorrect email or password.", "error")
            return render_template("login.html", email=request.form.get("email", "")), 401
        lang = session.get("lang")
        session.clear()
        if lang:
            session["lang"] = lang
        session["user_id"] = user["id"]
        session.permanent = True
        flash("You are logged in.", "success")
        return redirect(safe_next(request.args.get("next")) or _home_for(user["role"]))
    return render_template("login.html", email="")


@bp.route("/logout", methods=["POST"])
def logout():
    lang = session.get("lang")
    session.clear()
    if lang:
        session["lang"] = lang
    flash("You have been logged out.", "info")
    return redirect(url_for("main.index"))
