from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import database
import auth
from app import app


client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_database() -> None:
    database.reset_tasks()


def test_root_and_health() -> None:
    assert client.get("/").json()["name"] == "Task API"
    assert client.get("/health").json() == {"status": "ok", "db": "ok"}


def test_read_and_not_found() -> None:
    assert len(client.get("/tasks").json()) == 3
    assert client.get("/tasks/1").status_code == 200
    response = client.get("/tasks/99")
    assert response.status_code == 404
    assert response.json() == {"error": "Task not found"}


def test_full_crud_cycle() -> None:
    created = client.post("/tasks", json={"title": "Buy milk"})
    assert created.status_code == 201
    task = created.json()
    assert task == {"id": 4, "title": "Buy milk", "done": False}

    updated = client.put(f"/tasks/{task['id']}", json={"done": True})
    assert updated.status_code == 200
    assert updated.json()["done"] is True

    deleted = client.delete(f"/tasks/{task['id']}")
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert client.get(f"/tasks/{task['id']}").status_code == 404


def test_validation() -> None:
    assert client.post("/tasks", json={}).status_code == 400
    assert client.post("/tasks", json={"title": "  "}).status_code == 400
    assert client.put("/tasks/1", json={}).status_code == 400
    assert client.put("/tasks/1", json={"title": ""}).status_code == 400


def test_optional_features() -> None:
    assert len(client.get("/tasks?done=true").json()) == 1
    assert len(client.get("/tasks?search=persistence").json()) == 1
    assert len(client.get("/tasks?limit=2&offset=1").json()) == 2
    assert client.get("/stats").json() == {"total": 3, "done": 1, "open": 2}


def test_database_persists_and_seed_does_not_duplicate() -> None:
    client.post("/tasks", json={"title": "Survive restart"})
    database.initialize_database()
    database.initialize_database()
    tasks = client.get("/tasks").json()
    assert len(tasks) == 4
    assert any(task["title"] == "Survive restart" for task in tasks)


class FakeAuth:
    def __init__(self) -> None:
        self.user = SimpleNamespace(
            id="user-123",
            email="student@example.com",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            user_metadata={},
        )

    def sign_up(self, credentials: dict) -> SimpleNamespace:
        if credentials["email"] == "exists@example.com":
            raise ValueError("User already registered")
        return SimpleNamespace(user=self.user)

    def sign_in_with_password(self, credentials: dict) -> SimpleNamespace:
        if credentials["password"] == "wrong-password":
            raise ValueError("Invalid login")
        session = SimpleNamespace(
            access_token="access.jwt.token",
            refresh_token="refresh-token",
        )
        return SimpleNamespace(session=session)

    def get_user(self, token: str) -> SimpleNamespace:
        if token != "access.jwt.token":
            raise ValueError("Invalid token")
        return SimpleNamespace(user=self.user)

    def refresh_session(self, token: str) -> SimpleNamespace:
        if token != "refresh-token":
            raise ValueError("Invalid refresh token")
        session = SimpleNamespace(
            access_token="new.access.token",
            refresh_token="new-refresh-token",
        )
        return SimpleNamespace(session=session)

    def sign_out(self) -> None:
        return None


@pytest.fixture
def fake_supabase(monkeypatch: pytest.MonkeyPatch) -> FakeAuth:
    fake_auth = FakeAuth()
    monkeypatch.setattr(
        auth,
        "get_supabase",
        lambda: SimpleNamespace(auth=fake_auth),
    )
    monkeypatch.setattr(
        "app.get_supabase",
        lambda: SimpleNamespace(auth=fake_auth),
    )
    auth._failed_logins.clear()
    return fake_auth


def test_public_info_needs_no_token() -> None:
    response = client.get("/public/info")
    assert response.status_code == 200
    assert response.json() == {
        "message": "Welcome stranger! This info is public."
    }


def test_signup_and_login(fake_supabase: FakeAuth) -> None:
    missing = client.post("/auth/signup", json={"email": "student@example.com"})
    assert missing.status_code == 400

    signed_up = client.post(
        "/auth/signup",
        json={"email": "student@example.com", "password": "strong-password"},
    )
    assert signed_up.status_code == 201
    assert signed_up.json()["user"]["email"] == "student@example.com"

    invalid = client.post(
        "/auth/login",
        json={"email": "student@example.com", "password": "wrong-password"},
    )
    assert invalid.status_code == 401

    logged_in = client.post(
        "/auth/login",
        json={"email": "student@example.com", "password": "strong-password"},
    )
    assert logged_in.status_code == 200
    assert logged_in.json()["access_token"] == "access.jwt.token"
    assert logged_in.json()["refresh_token"] == "refresh-token"


def test_protected_routes_and_logout(fake_supabase: FakeAuth) -> None:
    assert client.get("/protected/profile").status_code == 401
    invalid = client.get(
        "/protected/profile",
        headers={"Authorization": "Bearer bad-token"},
    )
    assert invalid.status_code == 401
    assert invalid.json() == {"error": "Invalid or expired token"}

    headers = {"Authorization": "Bearer access.jwt.token"}
    profile = client.get("/protected/profile", headers=headers)
    assert profile.status_code == 200
    assert profile.json()["id"] == "user-123"
    assert "password" not in profile.json()

    assert client.get("/protected/dashboard", headers=headers).status_code == 200
    assert client.get("/protected/admin", headers=headers).status_code == 403
    assert client.post("/auth/logout", headers=headers).status_code == 204


def test_refresh_token(fake_supabase: FakeAuth) -> None:
    response = client.post(
        "/auth/refresh",
        json={"refresh_token": "refresh-token"},
    )
    assert response.status_code == 200
    assert response.json()["access_token"] == "new.access.token"
