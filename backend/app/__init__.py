"""Flask application factory. JSON is emitted as UTF-8 (ensure_ascii disabled) so Greek
and all scripts round-trip intact through the API. Also serves the PWA frontend."""
import logging
import secrets

from flask import Flask, jsonify, render_template, send_from_directory

from .config import Config
from .db import Session


def create_app():
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config.from_object(Config)
    # CORE encoding guarantee at the API layer: never escape non-ASCII to \uXXXX.
    app.json.ensure_ascii = False
    app.config["JSON_AS_ASCII"] = False

    # Session signing key. A stable key (set by setup.sh into .env) keeps logins across
    # restarts; without one we generate an ephemeral key and warn loudly.
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = secrets.token_hex(32)
        logging.getLogger(__name__).warning(
            "SECRET_KEY not set — using an ephemeral key; logins will reset on restart. "
            "Run setup.sh or set SECRET_KEY in .env."
        )

    from .api import bp as api_bp   # api_bp guards itself at import time (see api.py)
    from .auth import auth_bp
    from .bookren import bp as bookren_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(bookren_bp)

    # The "E-book Metadata Quality" tab embeds this self-contained UI.
    @app.get("/bookren")
    def bookren_ui():
        return send_from_directory(app.static_folder, "bookren/index.html")

    # --- PWA frontend ---
    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/manifest.json")
    def manifest():
        return send_from_directory(app.static_folder, "manifest.json",
                                   mimetype="application/manifest+json")

    @app.get("/sw.js")
    def service_worker():
        # served from root so its scope covers the whole app
        resp = send_from_directory(app.static_folder, "sw.js", mimetype="application/javascript")
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    @app.get("/healthz")
    def healthz():
        return jsonify(status="ok")

    @app.teardown_appcontext
    def remove_session(exc=None):
        Session.remove()

    return app
