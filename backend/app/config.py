"""Configuration. All text I/O is UTF-8; see encoding.py for the integrity guarantees."""
import os

class Config:
    # Default points at the docker-compose `db` service; override via env for local runs.
    DATABASE_URL = os.environ.get(
        "DATABASE_URL", "postgresql+psycopg2://loa:loa@localhost:5432/loa"
    )
    # Directory holding an optional CSV/.bcbk export to import. Read-only mount in docker.
    DATA_DIR = os.environ.get("DATA_DIR", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
    MASTER_CSV = os.environ.get("MASTER_CSV", "BookCatalogue.csv")
    BACKUP_BCBK = os.environ.get("BACKUP_BCBK", "BookCatalogue.bcbk")

    DEFAULT_CURRENCY = os.environ.get("DEFAULT_CURRENCY", "GBP")

    # --- auth / sessions ---
    # SECRET_KEY signs session cookies. setup.sh generates a stable one into .env.
    # Without it, sessions reset on restart (a loud warning is logged).
    SECRET_KEY = os.environ.get("SECRET_KEY", "")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # If a reverse proxy terminates TLS, the app itself sees HTTP — Secure is off by default
    # so the session cookie works over both HTTP and the proxied HTTPS URL. Set
    # SESSION_COOKIE_SECURE=true if the app is served directly over HTTPS.
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"
    PERMANENT_SESSION_LIFETIME = int(os.environ.get("SESSION_DAYS", "30")) * 86400

    # Network enrichment is OFF by default. It is never triggered by import; it is an
    # explicit, opt-in operation with dry-run/diff/selective-commit (see enrichment.py).
    ENRICHMENT_ENABLED = os.environ.get("ENRICHMENT_ENABLED", "true").lower() == "true"
    GOOGLE_BOOKS_API_KEY = os.environ.get("GOOGLE_BOOKS_API_KEY", "")
    HTTP_TIMEOUT = float(os.environ.get("HTTP_TIMEOUT", "8"))

    # --- E-book folder scan ---
    # The e-book folder is chosen in the app (Admin → E-book folder) and stored in the DB
    # (settings.py). This env var is only a FALLBACK default if no DB setting is present.
    EBOOKS_DIR = os.environ.get("EBOOKS_DIR", "")

    # Roots the in-app folder browser (and scan/rename) may traverse. Colon-separated.
    # In docker the host media tree is bind-mounted here; everything stays inside these roots.
    BROWSE_ROOTS = [p for p in os.environ.get("BROWSE_ROOTS", "/media").split(":") if p]

    # LibraryThing TALPA token — natural-language "describe a book" discovery (50 req/day).
    # Empty => the Discover feature is disabled. Server-side only (never sent to the browser).
    LIBRARYTHING_TALPA_TOKEN = os.environ.get("LIBRARYTHING_TALPA_TOKEN", "")
