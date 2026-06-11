"""Auth tests: API is gated, login works, roles enforced."""
import pytest

from app import create_app
from app import models as m
from app.auth import hash_password


@pytest.fixture
def client(session):
    app = create_app()
    app.config.update(TESTING=True, SECRET_KEY="test-key")
    return app.test_client()


def _user(session, name, role, pw="secret1"):
    session.add(m.User(username=name, password_hash=hash_password(pw), role=role))
    session.commit()


def test_api_requires_auth(client):
    assert client.get("/api/stats").status_code == 401
    assert client.post("/api/books", json={"title": "X"}).status_code == 401


def test_login_required_then_access(client, session):
    _user(session, "alice", "user")
    assert client.post("/api/auth/login", json={"username": "alice", "password": "nope"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "alice", "password": "secret1"}).status_code == 200
    assert client.get("/api/stats").status_code == 200
    assert client.get("/api/auth/me").get_json()["username"] == "alice"


def test_readonly_blocked_from_writes(client, session):
    _user(session, "bob", "readonly")
    client.post("/api/auth/login", json={"username": "bob", "password": "secret1"})
    assert client.get("/api/stats").status_code == 200            # reads OK
    assert client.post("/api/books", json={"title": "X"}).status_code == 403   # writes blocked


def test_writer_can_write_and_logout(client, session):
    _user(session, "carol", "admin")        # only admins can write now
    client.post("/api/auth/login", json={"username": "carol", "password": "secret1"})
    assert client.post("/api/wishlist", json={"title": "Wanted"}).status_code == 201
    client.post("/api/auth/logout")
    assert client.get("/api/stats").status_code == 401            # session cleared


def test_change_password(client, session):
    _user(session, "dave", "user", pw="secret1")
    client.post("/api/auth/login", json={"username": "dave", "password": "secret1"})
    assert client.post("/api/auth/change-password",
                       json={"current": "secret1", "new": "secret2"}).status_code == 200
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"username": "dave", "password": "secret2"}).status_code == 200
