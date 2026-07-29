import os

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row


load_dotenv()
DATABASE_URL = os.environ["DATABASE_URL"]
INITIAL_TASKS = [
    ("Learn PostgreSQL basics", True),
    ("Containerize the CRUD API", False),
    ("Test Docker persistence", False),
]


def connect() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def initialize_database() -> None:
    with connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                done BOOLEAN NOT NULL DEFAULT FALSE
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_done ON tasks(done)"
        )
        count = connection.execute("SELECT COUNT(*) AS total FROM tasks").fetchone()
        if count["total"] == 0:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.executemany(
                        "INSERT INTO tasks (title, done) VALUES (%s, %s)",
                        INITIAL_TASKS,
                    )


def list_tasks(
    done: bool | None = None,
    search: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict]:
    conditions: list[str] = []
    parameters: list[object] = []
    if done is not None:
        conditions.append("done = %s")
        parameters.append(done)
    if search:
        conditions.append("title ILIKE %s")
        parameters.append(f"%{search}%")
    query = "SELECT id, title, done FROM tasks"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY title"
    if limit is not None:
        query += " LIMIT %s OFFSET %s"
        parameters.extend([limit, offset])
    elif offset:
        query += " OFFSET %s"
        parameters.append(offset)
    with connect() as connection:
        return connection.execute(query, parameters).fetchall()


def get_task(task_id: int) -> dict | None:
    with connect() as connection:
        return connection.execute(
            "SELECT id, title, done FROM tasks WHERE id = %s", (task_id,)
        ).fetchone()


def create_task(title: str) -> dict:
    with connect() as connection:
        return connection.execute(
            """
            INSERT INTO tasks (title, done)
            VALUES (%s, %s)
            RETURNING id, title, done
            """,
            (title, False),
        ).fetchone()


def update_task(task_id: int, title: str, done: bool) -> dict | None:
    with connect() as connection:
        return connection.execute(
            """
            UPDATE tasks
            SET title = %s, done = %s
            WHERE id = %s
            RETURNING id, title, done
            """,
            (title, done, task_id),
        ).fetchone()


def delete_task(task_id: int) -> bool:
    with connect() as connection:
        cursor = connection.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
        return cursor.rowcount == 1


def task_stats() -> dict:
    with connect() as connection:
        row = connection.execute(
            """
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE done) AS done
            FROM tasks
            """
        ).fetchone()
    return {"total": row["total"], "done": row["done"], "open": row["total"] - row["done"]}


def reset_tasks() -> list[dict]:
    with connect() as connection:
        with connection.transaction():
            connection.execute("TRUNCATE tasks RESTART IDENTITY")
            with connection.cursor() as cursor:
                cursor.executemany(
                    "INSERT INTO tasks (title, done) VALUES (%s, %s)",
                    INITIAL_TASKS,
                )
    return list_tasks()


def database_is_healthy() -> bool:
    try:
        with connect() as connection:
            return connection.execute("SELECT 1").fetchone() is not None
    except psycopg.Error:
        return False
