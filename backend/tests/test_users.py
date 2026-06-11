"""User-management tests (admin-only endpoints + safeguards)."""
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


def _login(client, name, pw="secret1"):
    return client.post("/api/auth/login", json={"username": name, "password": pw})


def _id_of(client, name):
    return next(u["id"] for u in client.get("/api/users").get_json()["users"] if u["username"] == name)


def test_non_admin_cannot_manage(client, session):
    _user(session, "u", "user")
    _login(client, "u")
    assert client.get("/api/users").status_code == 403
    assert client.post("/api/users", json={"username": "x", "password": "secret1"}).status_code == 403


def test_admin_create_list_update_delete(client, session):
    _user(session, "boss", "admin")
    _login(client, "boss")
    r = client.post("/api/users", json={"username": "alice", "password": "secret1", "role": "user"})
    assert r.status_code == 201
    uid = r.get_json()["id"]
    assert "alice" in [u["username"] for u in client.get("/api/users").get_json()["users"]]
    assert client.post(f"/api/users/{uid}", json={"role": "readonly"}).status_code == 200
    assert client.post(f"/api/users/{uid}", json={"password": "newpass"}).status_code == 200
    client.post("/api/auth/logout")
    assert _login(client, "alice", "newpass").status_code == 200       # reset worked
    client.post("/api/auth/logout"); _login(client, "boss")
    assert client.delete(f"/api/users/{uid}").status_code == 200


def test_duplicate_and_weak_password_rejected(client, session):
    _user(session, "boss", "admin")
    _login(client, "boss")
    client.post("/api/users", json={"username": "alice", "password": "secret1", "role": "user"})
    assert client.post("/api/users", json={"username": "alice", "password": "secret1"}).status_code == 409
    assert client.post("/api/users", json={"username": "bob", "password": "123"}).status_code == 400


def test_cannot_delete_self_or_demote_last_admin(client, session):
    _user(session, "only", "admin")
    _login(client, "only")
    me = _id_of(client, "only")
    assert client.delete(f"/api/users/{me}").status_code == 400          # own account
    assert client.post(f"/api/users/{me}", json={"role": "user"}).status_code == 400  # last admin
