from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as app_module
from app import app


client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_database(tmp_path: Path) -> None:
    app_module.DB_PATH = tmp_path / "test_tasks.db"
    app_module.initialize_database()


def test_root_and_health() -> None:
    assert client.get("/").json()["name"] == "Task API"
    assert client.get("/health").json() == {"status": "ok"}


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
    app_module.initialize_database()
    app_module.initialize_database()
    tasks = client.get("/tasks").json()
    assert len(tasks) == 4
    assert any(task["title"] == "Survive restart" for task in tasks)
