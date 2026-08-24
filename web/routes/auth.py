"""Auth blueprint — login/logout with rate limiting."""
import time
from flask import Blueprint, request, session, jsonify

auth_bp = Blueprint("auth", __name__)

# Simple in-memory rate limiter
_login_attempts = {}


def _check_rate_limit(ip: str) -> bool:
    now = time.time()
    attempts = _login_attempts.get(ip, [])
    # Keep only last minute
    attempts = [t for t in attempts if now - t < 60]
    _login_attempts[ip] = attempts
    return len(attempts) < 5


@auth_bp.route("/login", methods=["POST"])
def login():
    ip = request.remote_addr or "unknown"
    if not _check_rate_limit(ip):
        return jsonify({"ok": False, "error": "Too many attempts"}), 429

    data = request.get_json(silent=True) or {}
    # TODO: integrate with real auth
    _login_attempts.setdefault(ip, []).append(time.time())
    return jsonify({"ok": True})


@auth_bp.route("/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})
