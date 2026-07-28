# Task API

A beginner-friendly CRUD API for an in-memory to-do list, built with Python and FastAPI. It supports creating, reading, updating, and deleting tasks, with interactive Swagger documentation.

## Run it

Requires Python 3.10 or newer.

```bash
python -m venv .venv
.venv\Scripts\activate

pip install -r requirements.txt
uvicorn app:app --reload
```

Open:

- API: http://localhost:8000/
- Swagger UI: http://localhost:8000/docs
- Health check: http://localhost:8000/health

The server uses an in-memory list. Any changes disappear when the process restarts because nothing is saved to a database or file. `POST /reset` also restores the three example tasks.

## Endpoints

| Method | Path | Purpose | Success |
| --- | --- | --- | --- |
| GET | `/` | API information | 200 |
| GET | `/health` | Health check | 200 |
| GET | `/tasks` | List tasks; optionally filter, search, or paginate | 200 |
| GET | `/tasks/{id}` | Get one task | 200 |
| POST | `/tasks` | Create a task | 201 |
| PUT | `/tasks/{id}` | Update a task's title and/or done state | 200 |
| DELETE | `/tasks/{id}` | Delete a task | 204 |
| GET | `/stats` | Count total, done, and open tasks | 200 |
| POST | `/reset` | Restore example tasks | 200 |

`GET /tasks` accepts `done`, `search`, `limit`, and `offset` query parameters. Pagination matters in real APIs because returning an unlimited collection becomes slow and expensive as data grows.

## Example

```console
$ curl -i -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{"title":"Buy milk"}'
HTTP/1.1 201 Created
content-type: application/json

{"id":4,"title":"Buy milk","done":false}
```

Then try the full CRUD cycle in Swagger UI at `/docs`.

## Run the tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

The automated tests cover root and health endpoints, successful CRUD, 404 responses, validation, filtering, search, pagination, statistics, and reset.
