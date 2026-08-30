"""Session authentication for the owner dashboard."""

from __future__ import annotations

import base64
import hmac
import os
import time
from urllib.parse import urlparse

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

auth_bp = Blueprint("auth", __name__)

# In-process brute-force limiter. The security module also tracks lockouts, so
# this cheap limiter keeps repeated requests from doing password work.
_login_attempts: dict[str, list[float]] = {}

_PUBLIC_PATHS = {
    "/login",
    "/logout",
    "/api/health",
    "/api/health/full",
    "/api/health/metrics",
}


def _client_ip() -> str:
    return request.remote_addr or "unknown"


def _check_rate_limit(ip: str) -> bool:
    now = time.time()
    attempts = [timestamp for timestamp in _login_attempts.get(ip, []) if now - timestamp < 60]
    _login_attempts[ip] = attempts
    return len(attempts) < 5


def _record_failure(ip: str) -> None:
    _login_attempts.setdefault(ip, []).append(time.time())
    try:
        import security

        security.record_login_fail(ip)
    except Exception:
        pass


def _record_success(ip: str) -> None:
    _login_attempts.pop(ip, None)
    try:
        import security

        security.record_login_success(ip)
    except Exception:
        pass


def _configured_username() -> str:
    return os.getenv("ADMIN_USERNAME", "admin")


def _configured_password_hash() -> str:
    encoded = os.getenv("ADMIN_PASSWORD_HASH_B64", "")
    if encoded:
        try:
            return base64.b64decode(encoded, validate=True).decode()
        except (ValueError, UnicodeDecodeError):
            return ""
    return os.getenv("ADMIN_PASSWORD_HASH", "")


def _credentials_configured() -> bool:
    return bool(_configured_password_hash() or os.getenv("ADMIN_PASSWORD"))


def _password_matches(password: str) -> bool:
    password_hash = _configured_password_hash()
    if password_hash:
        try:
            return check_password_hash(password_hash, password)
        except (ValueError, TypeError):
            return False

    configured_password = os.getenv("ADMIN_PASSWORD", "")
    return bool(configured_password) and hmac.compare_digest(password, configured_password)


def _request_data() -> tuple[str, str]:
    data = request.get_json(silent=True) if request.is_json else request.form
    return str((data or {}).get("username", "")), str((data or {}).get("password", ""))


def _wants_json() -> bool:
    return request.is_json or request.path.startswith("/api/")


def _safe_next(value: str | None) -> str:
    if not value:
        return "/"
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc or not value.startswith("/") or value.startswith("//"):
        return "/"
    return value


def _login_error(message: str, status: int):
    if _wants_json():
        return jsonify({"ok": False, "error": message}), status
    return render_template("login.html", error=message, next=request.args.get("next")), status


@auth_bp.before_app_request
def require_auth():
    """Keep the dashboard and its APIs private while health stays probeable."""
    path = request.path.rstrip("/") or "/"
    if path in _PUBLIC_PATHS or path.startswith("/static/"):
        return None
    if session.get("authenticated"):
        return None
    if not _credentials_configured():
        return _login_error("Authentication is not configured", 503)
    if _wants_json():
        return jsonify({"ok": False, "error": "Authentication required"}), 401
    return redirect(url_for("auth.login", next=request.full_path))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if session.get("authenticated"):
            return redirect("/")
        return render_template("login.html", next=request.args.get("next"))

    ip = _client_ip()
    if not _check_rate_limit(ip):
        return _login_error("Too many attempts", 429)

    username, password = _request_data()
    username_ok = hmac.compare_digest(username, _configured_username())
    if not _credentials_configured():
        return _login_error("Authentication is not configured", 503)
    if not username_ok or not _password_matches(password):
        _record_failure(ip)
        return _login_error("Invalid username or password", 401)

    _record_success(ip)
    session.clear()
    session["authenticated"] = True
    session["username"] = _configured_username()
    destination = _safe_next(request.args.get("next"))
    if _wants_json():
        return jsonify({"ok": True, "username": session["username"]})
    return redirect(destination)


@auth_bp.route("/logout")
def logout():
    session.clear()
    if _wants_json():
        return jsonify({"ok": True})
    return redirect(url_for("auth.login"))
