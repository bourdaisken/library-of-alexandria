"""
Authentication: multi-user accounts with session-cookie login and roles.

Roles:
  admin     full access + (future) user management
  user      read + write the catalog/wishlist
  readonly  read only — blocked from any non-GET request

The api blueprint guards every /api/* route via `require_auth` (registered in __init__):
unauthenticated -> 401; readonly attempting a write -> 403.
"""
from __future__ import annotations

import re
import time

from flask import Blueprint, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from .db import Session
from . import models as m

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

# Only admins may write. Everyone else (consumer) is search + read-only.
WRITE_ROLES = {"admin"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# --- simple in-memory login rate limiting (per client IP) ---
_LOGIN_WINDOW = 300      # seconds
_LOGIN_MAX_FAILS = 10    # failures allowed within the window before a temporary block
_login_fails: dict[str, list[float]] = {}


def _recent_fails(ip):
    now = time.monotonic()
    arr = [t for t in _login_fails.get(ip, []) if now - t < _LOGIN_WINDOW]
    _login_fails[ip] = arr
    return arr


def _rate_limited(ip):
    return len(_recent_fails(ip)) >= _LOGIN_MAX_FAILS


def _record_fail(ip):
    _login_fails.setdefault(ip, []).append(time.monotonic())


def hash_password(pw: str) -> str:
    return generate_password_hash(pw)


def is_admin() -> bool:
    return session.get("role") == "admin"


def _consumer_may_write():
    """Consumers can manage the (shared) wishlist + wishlist collections — nothing else."""
    p, meth = request.path, request.method
    if p == "/api/wishlist" and meth == "POST":
        return True
    if p.startswith("/api/wishlist/"):              # assign/remove a wishlist item
        return True
    if p == "/api/collections" and meth == "POST":
        return (request.get_json(silent=True) or {}).get("kind") == "wishlist"
    if re.match(r"^/api/collections/[^/]+$", p) and meth == "DELETE":
        from .db import Session
        from . import models as m
        col = Session().get(m.Collection, p.rsplit("/", 1)[1])
        return bool(col and col.kind == "wishlist")
    return False


def require_auth():
    """before_request guard for the api blueprint. Returns a response to short-circuit."""
    if not session.get("uid"):
        return jsonify(error="authentication required"), 401
    if request.method not in SAFE_METHODS and session.get("role") not in WRITE_ROLES:
        if not _consumer_may_write():
            return jsonify(error="read-only account — only admins can change the library"), 403
    return None


@auth_bp.post("/login")
def login():
    ip = request.remote_addr or "?"
    if _rate_limited(ip):
        return jsonify(error="too many failed attempts — wait a few minutes and try again"), 429
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    s = Session()
    user = s.query(m.User).filter(m.User.username == username).first()
    if not user or not check_password_hash(user.password_hash, password):
        _record_fail(ip)
        return jsonify(error="invalid username or password"), 401
    _login_fails.pop(ip, None)            # clear on success
    session.permanent = True
    session["uid"] = user.id
    session["username"] = user.username
    session["role"] = user.role
    return jsonify(username=user.username, role=user.role)


@auth_bp.post("/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@auth_bp.get("/me")
def me():
    if not session.get("uid"):
        return jsonify(authenticated=False), 401
    return jsonify(authenticated=True, username=session.get("username"), role=session.get("role"))


@auth_bp.post("/change-password")
def change_password():
    if not session.get("uid"):
        return jsonify(error="authentication required"), 401
    data = request.get_json(silent=True) or {}
    s = Session()
    user = s.get(m.User, session["uid"])
    if not user or not check_password_hash(user.password_hash, data.get("current") or ""):
        return jsonify(error="current password is wrong"), 403
    new = data.get("new") or ""
    if len(new) < 6:
        return jsonify(error="new password must be at least 6 characters"), 400
    user.password_hash = hash_password(new)
    s.commit()
    return jsonify(ok=True)
