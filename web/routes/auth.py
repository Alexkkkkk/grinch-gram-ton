"""Auth blueprint — login/logout."""
from flask import Blueprint, request, session

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    # TODO: integrate with real auth
    return {"ok": True}


@auth_bp.route("/logout")
def logout():
    session.clear()
    return {"ok": True}
