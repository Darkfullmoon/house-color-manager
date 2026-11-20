"""Accounts: login, roles (admin / user), CSRF and the guard that protects every route.

ADM is the only administrator; its password comes from ADMIN_PASSWORD in the
environment. Other users start with DEFAULT_PASSWORD and must set their own.
"""
import hmac
import re
import secrets

from flask import (abort, current_app, g, jsonify, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from models import User, ValidationError, db

USERNAME_RE = re.compile(r"^[A-Z]{3}$")
OPEN_ENDPOINTS = {"login", "static", "health"}
# Endpoints only the administrator may call; everything else is open to any logged-in user.
ADMIN_ENDPOINTS = {"manufacturers_page", "create_manufacturer", "delete_manufacturer"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def password_problems(password, default_password):
    """Rules a new password breaks, as short phrases. Empty list = acceptable."""
    password = password or ""
    problems = []
    if len(password) < 8:
        problems.append("at least 8 characters")
    if not re.search(r"[A-Z]", password):
        problems.append("at least one uppercase letter (A–Z)")
    if not re.search(r"[0-9]", password):
        problems.append("at least one digit (0–9)")
    if not re.search(r"[^A-Za-z0-9]", password):
        problems.append("at least one special character (e.g. ! @ # * _)")
    if password and password == default_password:
        problems.append("must be different from the default password")
    return problems


def current_user():
    return getattr(g, "user", None)


def csrf_token():
    token = session.get("_csrf")
    if not token:
        token = session["_csrf"] = secrets.token_urlsafe(32)
    return token


def _wants_json():
    return request.path.startswith(("/api/", "/uploads/"))


def _safe_next(target):
    """Only follow ?next= to a path on this site."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return url_for("dashboard")


def register_auth(app):
    app.jinja_env.globals.update(current_user=current_user, csrf_token=csrf_token)

    @app.before_request
    def guard():
        g.user = None
        uid = session.get("uid")
        if uid is not None:
            user = db.session.get(User, uid)
            if user is not None and user.active:
                g.user = user
            else:  # deleted or disabled while logged in
                session.clear()

        endpoint = request.endpoint
        is_open = endpoint is None or endpoint in OPEN_ENDPOINTS
        # Not logged in comes first: a page left open until the session expired should
        # lead back to the login page, not to a CSRF error.
        if g.user is None and not is_open:
            if _wants_json():
                return jsonify({"error": "Please log in."}), 401
            nxt = request.full_path.rstrip("?") if request.method == "GET" else None
            return redirect(url_for("login", next=nxt))

        if app.config["CSRF_ENABLED"] and request.method not in SAFE_METHODS:
            sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or ""
            if not sent or not hmac.compare_digest(sent, session.get("_csrf", "")):
                abort(400, description="Invalid or missing CSRF token. Reload the page and try again.")

        if is_open:
            return None
        if g.user.must_change_password and endpoint not in ("change_password", "logout"):
            if _wants_json():
                return jsonify({"error": "Set a new password first."}), 403
            return redirect(url_for("change_password"))
        if endpoint in ADMIN_ENDPOINTS and not g.user.is_admin:
            abort(403, description="Admins only.")
        return None

    # ---- Login / logout ---------------------------------------------------- #
    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user():
            return redirect(url_for("dashboard"))
        error = None
        username = ""
        if request.method == "POST":
            username = (request.form.get("username") or "").strip().upper()
            password = request.form.get("password") or ""
            user = User.query.filter_by(username=username).first()
            ok = False
            if user is not None and user.active:
                if user.is_admin:
                    ok = hmac.compare_digest(password.encode(), app.config["ADMIN_PASSWORD"].encode())
                else:
                    ok = check_password_hash(user.password_hash, password)
            if ok:
                session.clear()
                session.permanent = True
                session["uid"] = user.id
                csrf_token()
                if user.must_change_password:
                    return redirect(url_for("change_password"))
                return redirect(_safe_next(request.args.get("next")))
            error = "Incorrect username or password."
        return render_template("login.html", error=error, username=username, bare=True)

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/change-password", methods=["GET", "POST"])
    def change_password():
        user = current_user()
        if user.is_admin:  # ADM's password lives in .env
            return redirect(url_for("dashboard"))
        errors = []
        if request.method == "POST":
            current = request.form.get("current") or ""
            new = request.form.get("new") or ""
            confirm = request.form.get("confirm") or ""
            if not check_password_hash(user.password_hash, current):
                errors.append("Current password is incorrect.")
            if new != confirm:
                errors.append("The two new passwords do not match.")
            errors += [f"New password needs {p}." if not p.startswith("must") else f"New password {p}."
                       for p in password_problems(new, app.config["DEFAULT_PASSWORD"])]
            if not errors:
                user.password_hash = generate_password_hash(new)
                user.must_change_password = False
                db.session.commit()
                return redirect(url_for("dashboard"))
        return render_template("change_password.html", errors=errors,
                               first=user.must_change_password, bare=user.must_change_password)

    # ---- User management (administrator only) ------------------------------ #
    def managed_users():
        return User.query.filter(User.role != "admin").order_by(User.username)

    def get_managed_user(user_id):
        user = db.session.get(User, user_id)
        if user is None or user.is_admin:  # ADM is configured in .env, never through the API
            abort(404, description="User not found.")
        return user

    def body():
        data = request.get_json(silent=True)
        return data if isinstance(data, dict) else {}

    def clean_full_name(value, errors):
        name = (value or "").strip() if isinstance(value, str) else ""
        if not name:
            errors["full_name"] = "Full name is required."
        elif len(name) > 120:
            errors["full_name"] = "Full name must be at most 120 characters."
        return name

    @app.get("/users")
    def users_page():
        return render_template("users.html", users=[u.to_dict() for u in managed_users()],
                               default_password=app.config["DEFAULT_PASSWORD"])

    @app.get("/api/users")
    def list_users():
        return jsonify([u.to_dict() for u in managed_users()])

    @app.post("/api/users")
    def create_user():
        data = body()
        errors = {}
        raw = data.get("username")
        username = raw.strip().upper() if isinstance(raw, str) else ""
        if not USERNAME_RE.match(username):
            errors["username"] = "Username must be 3 uppercase English letters (e.g. ABC)."
        elif username == app.config["ADMIN_USERNAME"]:
            errors["username"] = f"{username} is reserved for the administrator."
        elif User.query.filter_by(username=username).first():
            errors["username"] = f"Username {username} already exists."
        full_name = clean_full_name(data.get("full_name"), errors)
        if errors:
            raise ValidationError(errors)
        user = User(username=username, full_name=full_name, role="user", must_change_password=True,
                    password_hash=generate_password_hash(app.config["DEFAULT_PASSWORD"]))
        db.session.add(user)
        db.session.commit()
        return jsonify(user.to_dict()), 201

    @app.put("/api/users/<int:user_id>")
    def update_user(user_id):
        user = get_managed_user(user_id)
        data = body()
        errors = {}
        if "full_name" in data:
            name = clean_full_name(data.get("full_name"), errors)
            if not errors:
                user.full_name = name
        if "active" in data:
            if isinstance(data["active"], bool):
                user.active = data["active"]
            else:
                errors["active"] = "Active must be true or false."
        if errors:
            db.session.rollback()
            raise ValidationError(errors)
        db.session.commit()
        return jsonify(user.to_dict())

    @app.post("/api/users/<int:user_id>/reset-password")
    def reset_user_password(user_id):
        user = get_managed_user(user_id)
        user.password_hash = generate_password_hash(app.config["DEFAULT_PASSWORD"])
        user.must_change_password = True
        db.session.commit()
        return jsonify(user.to_dict())

    ADMIN_ENDPOINTS.update({"users_page", "list_users", "create_user", "update_user",
                            "reset_user_password"})
