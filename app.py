from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

import database
from auth import (
    check_login_rate_limit,
    clear_failed_logins,
    get_supabase,
    record_failed_login,
    require_user,
)


app = FastAPI(
    title="Task API",
    version="2.0",
    description="A PostgreSQL-backed task API with Supabase authentication.",
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


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    password: str

    @field_validator("email", "password")
    @classmethod
    def required_value(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str

    @field_validator("refresh_token")
    @classmethod
    def required_token(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


def safe_user(user: Any) -> dict:
    return {
        "id": str(user.id),
        "email": user.email,
        "created_at": user.created_at.isoformat()
        if hasattr(user.created_at, "isoformat")
        else str(user.created_at),
    }


def task_or_404(task_id: int) -> Task:
    task = database.get_task(task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Task not found"},
        )
    return Task(**task)


database.initialize_database()


@app.get("/", summary="Describe the API")
def root() -> dict:
    return {
        "name": "Task API",
        "version": "2.0",
        "endpoints": ["/tasks", "/auth/signup", "/auth/login", "/protected/profile"],
    }


@app.get("/public/info", summary="Read public information")
def public_info() -> dict:
    return {"message": "Welcome stranger! This info is public."}


@app.post(
    "/auth/signup",
    status_code=status.HTTP_201_CREATED,
    summary="Create a Supabase account",
)
def signup(body: Credentials) -> dict:
    try:
        response = get_supabase().auth.sign_up(
            {"email": body.email, "password": body.password}
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if response.user is None:
        raise HTTPException(status_code=400, detail="Unable to create account")
    return {"user": safe_user(response.user)}


@app.post("/auth/login", summary="Log in and receive JWT tokens")
def login(body: Credentials) -> dict:
    email = body.email.lower()
    check_login_rate_limit(email)
    try:
        response = get_supabase().auth.sign_in_with_password(
            {"email": body.email, "password": body.password}
        )
    except Exception as exc:
        record_failed_login(email)
        raise HTTPException(status_code=401, detail="Invalid email or password") from exc
    if response.session is None:
        record_failed_login(email)
        raise HTTPException(status_code=401, detail="Invalid email or password")
    clear_failed_logins(email)
    return {
        "access_token": response.session.access_token,
        "refresh_token": response.session.refresh_token,
        "token_type": "bearer",
    }


@app.post("/auth/refresh", summary="Refresh an access token")
def refresh(body: RefreshRequest) -> dict:
    try:
        response = get_supabase().auth.refresh_session(body.refresh_token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid refresh token") from exc
    if response.session is None:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    return {
        "access_token": response.session.access_token,
        "refresh_token": response.session.refresh_token,
        "token_type": "bearer",
    }


@app.post(
    "/auth/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Log out the current user",
)
def logout(
    user: Any = Depends(require_user),
) -> Response:
    del user
    try:
        get_supabase().auth.sign_out()
    except Exception:
        pass
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/protected/profile", summary="Read the authenticated profile")
def protected_profile(user: Any = Depends(require_user)) -> dict:
    return safe_user(user)


@app.get("/protected/dashboard", summary="Read the protected dashboard")
def protected_dashboard(user: Any = Depends(require_user)) -> dict:
    return {"message": f"Welcome to your dashboard, {user.email}."}


@app.get("/protected/admin", summary="Read admin-only information")
def protected_admin(user: Any = Depends(require_user)) -> dict:
    metadata = getattr(user, "user_metadata", None) or {}
    if metadata.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return {"message": "Welcome, administrator."}


@app.get("/health", summary="Check server health")
def health() -> dict:
    if not database.database_is_healthy():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "Database unavailable"},
        )
    return {"status": "ok", "db": "ok"}


@app.get("/tasks", response_model=list[Task], summary="List tasks")
def list_tasks(
    done: bool | None = None,
    search: str | None = None,
    limit: Annotated[int | None, Query(ge=1)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Task]:
    return [
        Task(**task)
        for task in database.list_tasks(done, search, limit, offset)
    ]


@app.get("/tasks/{task_id}", response_model=Task, summary="Get one task")
def get_task(task_id: int) -> Task:
    return task_or_404(task_id)


@app.post(
    "/tasks",
    response_model=Task,
    status_code=status.HTTP_201_CREATED,
    summary="Create a task",
)
def create_task(body: TaskCreate) -> Task:
    return Task(**database.create_task(body.title))


@app.put("/tasks/{task_id}", response_model=Task, summary="Update a task")
def update_task(task_id: int, body: TaskUpdate) -> Task:
    current = task_or_404(task_id)
    title = body.title if body.title is not None else current.title
    done = body.done if body.done is not None else current.done
    updated = database.update_task(task_id, title, done)
    return Task(**updated)


@app.delete(
    "/tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a task",
)
def delete_task(task_id: int) -> Response:
    if not database.delete_task(task_id):
        task_or_404(task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/stats", summary="Show task statistics")
def stats() -> dict:
    return database.task_stats()


@app.post("/reset", response_model=list[Task], summary="Reset example tasks")
def reset_tasks() -> list[Task]:
    return [Task(**task) for task in database.reset_tasks()]
