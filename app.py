import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, field_validator, model_validator


app = FastAPI(
    title="Task API",
    version="1.0",
    description="A small in-memory CRUD API for managing a to-do list.",
)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    first_error = exc.errors()[0]
    location = ".".join(str(part) for part in first_error["loc"] if part != "body")
    message = first_error["msg"].removeprefix("Value error, ")
    error = f"{location}: {message}" if location else message
    return JSONResponse(status_code=400, content={"error": error})


@app.exception_handler(HTTPException)
async def http_error_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    if isinstance(detail, dict) and "error" in detail:
        return JSONResponse(status_code=exc.status_code, content=detail)
    return JSONResponse(status_code=exc.status_code, content={"error": str(detail)})


class Task(BaseModel):
    id: int
    title: str
    done: bool


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str

    @field_validator("title")
    @classmethod
    def title_must_not_be_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title must not be empty")
        return value


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    done: bool | None = None

    @field_validator("title")
    @classmethod
    def title_must_not_be_empty(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("title must not be empty")
        return value

    @model_validator(mode="after")
    def body_must_include_a_change(self) -> "TaskUpdate":
        if self.title is None and self.done is None:
            raise ValueError("provide title and/or done")
        return self


INITIAL_TASKS = [
    ("Learn SQLite basics", 1),
    ("Connect the CRUD API", 0),
    ("Test database persistence", 0),
]
DB_PATH = Path(os.getenv("TASK_API_DB", "tasks.db"))


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database() -> None:
    with closing(connect()) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                done INTEGER NOT NULL DEFAULT 0 CHECK (done IN (0, 1))
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_done ON tasks(done)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_title ON tasks(title)"
        )
        count = connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        if count == 0:
            with connection:
                connection.executemany(
                    "INSERT INTO tasks (title, done) VALUES (?, ?)", INITIAL_TASKS
                )


def row_to_task(row: sqlite3.Row) -> Task:
    return Task(id=row["id"], title=row["title"], done=bool(row["done"]))


def find_task(connection: sqlite3.Connection, task_id: int) -> Task:
    row = connection.execute(
        "SELECT id, title, done FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Task not found"},
        )
    return row_to_task(row)


initialize_database()


@app.get("/", summary="Describe the API")
def root() -> dict:
    return {"name": "Task API", "version": "1.0", "endpoints": ["/tasks"]}


@app.get("/health", summary="Check server health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/tasks", response_model=list[Task], summary="List tasks")
def list_tasks(
    done: bool | None = None,
    search: str | None = None,
    limit: Annotated[int | None, Query(ge=1)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Task]:
    conditions: list[str] = []
    parameters: list[object] = []
    if done is not None:
        conditions.append("done = ?")
        parameters.append(int(done))
    if search:
        conditions.append("title LIKE ?")
        parameters.append(f"%{search}%")
    query = "SELECT id, title, done FROM tasks"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY title COLLATE NOCASE"
    if limit is not None:
        query += " LIMIT ? OFFSET ?"
        parameters.extend([limit, offset])
    elif offset:
        query += " LIMIT -1 OFFSET ?"
        parameters.append(offset)
    with closing(connect()) as connection:
        rows = connection.execute(query, parameters).fetchall()
    return [row_to_task(row) for row in rows]


@app.get("/tasks/{task_id}", response_model=Task, summary="Get one task")
def get_task(task_id: int) -> Task:
    with closing(connect()) as connection:
        return find_task(connection, task_id)


@app.post(
    "/tasks",
    response_model=Task,
    status_code=status.HTTP_201_CREATED,
    summary="Create a task",
)
def create_task(body: TaskCreate) -> Task:
    with closing(connect()) as connection:
        cursor = connection.execute(
            "INSERT INTO tasks (title, done) VALUES (?, ?)", (body.title, 0)
        )
        connection.commit()
        return find_task(connection, cursor.lastrowid)


@app.put("/tasks/{task_id}", response_model=Task, summary="Update a task")
def update_task(task_id: int, body: TaskUpdate) -> Task:
    with closing(connect()) as connection:
        current = find_task(connection, task_id)
        title = body.title if body.title is not None else current.title
        done = body.done if body.done is not None else current.done
        connection.execute(
            "UPDATE tasks SET title = ?, done = ? WHERE id = ?",
            (title, int(done), task_id),
        )
        connection.commit()
        return find_task(connection, task_id)


@app.delete(
    "/tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a task",
)
def delete_task(task_id: int) -> Response:
    with closing(connect()) as connection:
        find_task(connection, task_id)
        connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        connection.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/stats", summary="Show task statistics")
def stats() -> dict:
    with closing(connect()) as connection:
        row = connection.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN done = 1 THEN 1 ELSE 0 END) AS done
            FROM tasks
            """
        ).fetchone()
    total = row["total"]
    done_count = row["done"] or 0
    return {"total": total, "done": done_count, "open": total - done_count}


@app.post("/reset", response_model=list[Task], summary="Reset example tasks")
def reset_tasks() -> list[Task]:
    with closing(connect()) as connection:
        with connection:
            connection.execute("DELETE FROM tasks")
            connection.execute("DELETE FROM sqlite_sequence WHERE name = ?", ("tasks",))
            connection.executemany(
                "INSERT INTO tasks (title, done) VALUES (?, ?)", INITIAL_TASKS
            )
    return list_tasks()
