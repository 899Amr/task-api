# Task API

A containerized CRUD API built with Python, FastAPI, PostgreSQL, Docker Compose, and Supabase Auth. It supports account creation, JWT login, reusable route protection, role checks, and token refresh.

## Run it

Requires Docker Desktop or another Docker Compose-compatible engine.

```bash
cp .env.example .env
docker compose up --build
```

Open:

- API: http://localhost:8000/
- Swagger UI: http://localhost:8000/docs
- Health check: http://localhost:8000/health

The Compose stack starts two services: `api` and `db`. The API waits for PostgreSQL to become healthy, creates the `tasks` table and index automatically, then seeds three examples only when the table is empty.

Configuration comes from `.env`. Copy `.env.example`, set the PostgreSQL values, and add the project URL and publishable key from **Supabase → Project Settings → API**. In **Authentication → Sign In / Providers**, keep email/password enabled and turn off **Confirm email** for this exercise. Real credentials belong only in `.env`, which Git and Docker builds ignore.

## Endpoints

| Method | Path | Purpose | Success |
| --- | --- | --- | --- |
| GET | `/` | API information | 200 |
| GET | `/health` | API and database health check | 200 |
| GET | `/tasks` | List alphabetically; optionally filter, search, or paginate | 200 |
| GET | `/tasks/{id}` | Get one task | 200 |
| POST | `/tasks` | Create a task | 201 |
| PUT | `/tasks/{id}` | Update a task's title and/or done state | 200 |
| DELETE | `/tasks/{id}` | Delete a task | 204 |
| GET | `/stats` | Count total, done, and open tasks | 200 |
| POST | `/reset` | Restore example tasks | 200 |
| GET | `/public/info` | Public information; no token needed | 200 |
| POST | `/auth/signup` | Create an email/password account | 201 |
| POST | `/auth/login` | Return access and refresh tokens | 200 |
| POST | `/auth/logout` | Sign out an authenticated user | 204 |
| POST | `/auth/refresh` | Exchange a refresh token for a new session | 200 |
| GET | `/protected/profile` | Return the authenticated user's safe profile | 200 |
| GET | `/protected/dashboard` | Demonstrate reusable route protection | 200 |
| GET | `/protected/admin` | Require `user_metadata.role == "admin"` | 200 |

`GET /tasks` accepts `done`, `search`, `limit`, and `offset` query parameters. Filtering, searching, sorting, and statistics are performed by SQL. Pagination matters in real APIs because returning an unlimited collection becomes slow and expensive as data grows.

## PostgreSQL

The database runs from the official `postgres:17-alpine` image. Its named `taskdata` volume lives outside the container, so tasks survive `docker compose down` followed by `docker compose up`.

```sql
CREATE TABLE tasks (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    done BOOLEAN NOT NULL DEFAULT FALSE
);
```

Inspect the live database:

```bash
docker compose exec db psql -U postgres -d tasks -c "\dt"
docker compose exec db psql -U postgres -d tasks -c "SELECT * FROM tasks;"
```

The repository module uses psycopg `%s` placeholders for all client-provided values. An index on `done` helps PostgreSQL filter tasks efficiently. Seeding and reset operations use transactions so their multi-row changes are all-or-nothing.

![PostgreSQL tasks table](docs/postgres-screenshot.png)

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

## Authentication

Create an account and log in:

```bash
curl -X POST http://localhost:8000/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"email":"student@example.com","password":"strong-password"}'

curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"student@example.com","password":"strong-password"}'
```

Copy the returned `access_token`. In Swagger UI, click **Authorize**, enter the token, and call a protected endpoint. For curl:

```bash
curl http://localhost:8000/protected/profile \
  -H "Authorization: Bearer ACCESS_TOKEN"
```

The reusable `require_user` dependency reads the bearer token and asks Supabase to validate it before returning trusted user data. Missing credentials return `401 Access token required`; malformed, invalid, or expired credentials return `401 Invalid or expired token`. A valid user without the required admin role receives `403 Admin access required`. This is the difference between authentication (“who are you?”) and authorization (“may you do this?”).

Access tokens are short-lived JWTs and can be inspected at [jwt.io](https://jwt.io/) without sharing the token. Typical claims include the user id (`sub`), email, role, issued time (`iat`), and expiry (`exp`). Logout revokes the refresh session, although an already-issued JWT remains valid until its short expiry. `/auth/refresh` rotates a valid refresh token into a new session.

Login failures are limited to five attempts per email within five minutes. Successful login clears the counter.

![Swagger UI authentication routes](docs/auth-swagger-screenshot.png)

## Run the tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

The automated tests cover health, CRUD, validation, persistence, signup, login, bearer-token failures, protected profile/dashboard access, authorization, logout, and refresh. Supabase is replaced with a deterministic test double; PostgreSQL runs as a real service in GitHub Actions.

The same endpoint tests used for the in-memory and SQLite versions still pass. Identical behavior across three storage engines proves that storage is an implementation detail; a later layered-architecture step formalizes that boundary.

The `/health` endpoint runs `SELECT 1` against PostgreSQL. A load balancer can use this signal to stop routing traffic to an instance whose database connection is unhealthy.

Without the named volume, deleting the database container would delete its rows. The `taskdata` volume preserves the database independently from any individual container.
