"""Enrichment sources management (admin) tests."""
import pytest

from app import create_app
from app import models as m
from app.auth import hash_password


@pytest.fixture
def client(session):
    app = create_app()
    app.config.update(TESTING=True, SECRET_KEY="test-key")
    return app.test_client()


def _login_admin(client, session):
    session.add(m.User(username="boss", password_hash=hash_password("secret1"), role="admin"))
    session.commit()
    client.post("/api/auth/login", json={"username": "boss", "password": "secret1"})


def test_sources_seed_and_toggle(client, session):
    _login_admin(client, session)
    d = client.get("/api/enrichment/sources").get_json()
    keys = {s["key"] for s in d["sources"]}
    assert {"openlibrary", "google"} <= keys                 # seeded defaults
    assert "openlibrary" in d["available"]
    gid = next(s["id"] for s in d["sources"] if s["key"] == "google")
    assert client.post(f"/api/enrichment/sources/{gid}", json={"enabled": False}).status_code == 200
    d2 = client.get("/api/enrichment/sources").get_json()
    assert next(s for s in d2["sources"] if s["key"] == "google")["enabled"] is False


def test_non_admin_blocked(client, session):
    session.add(m.User(username="ro", password_hash=hash_password("secret1"), role="readonly"))
    session.commit()
    client.post("/api/auth/login", json={"username": "ro", "password": "secret1"})
    assert client.get("/api/enrichment/sources").status_code == 403
