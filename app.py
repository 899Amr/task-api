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
    Task(id=1, title="Learn HTTP basics", done=True),
    Task(id=2, title="Build a CRUD API", done=False),
    Task(id=3, title="Test it in Swagger UI", done=False),
]
tasks: list[Task] = [task.model_copy() for task in INITIAL_TASKS]


def task_index(task_id: int) -> int:
    for index, task in enumerate(tasks):
        if task.id == task_id:
            return index
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": f"Task {task_id} not found"},
    )


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
    result = tasks
    if done is not None:
        result = [task for task in result if task.done is done]
    if search:
        result = [task for task in result if search.casefold() in task.title.casefold()]
    if limit is None:
        return result[offset:]
    return result[offset : offset + limit]


@app.get("/tasks/{task_id}", response_model=Task, summary="Get one task")
def get_task(task_id: int) -> Task:
    return tasks[task_index(task_id)]


@app.post(
    "/tasks",
    response_model=Task,
    status_code=status.HTTP_201_CREATED,
    summary="Create a task",
)
def create_task(body: TaskCreate) -> Task:
    next_id = max((task.id for task in tasks), default=0) + 1
    task = Task(id=next_id, title=body.title, done=False)
    tasks.append(task)
    return task


@app.put("/tasks/{task_id}", response_model=Task, summary="Update a task")
def update_task(task_id: int, body: TaskUpdate) -> Task:
    index = task_index(task_id)
    current = tasks[index]
    updated = current.model_copy(
        update={
            "title": body.title if body.title is not None else current.title,
            "done": body.done if body.done is not None else current.done,
        }
    )
    tasks[index] = updated
    return updated


@app.delete(
    "/tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a task",
)
def delete_task(task_id: int) -> Response:
    tasks.pop(task_index(task_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/stats", summary="Show task statistics")
def stats() -> dict:
    done_count = sum(task.done for task in tasks)
    return {"total": len(tasks), "done": done_count, "open": len(tasks) - done_count}


@app.post("/reset", response_model=list[Task], summary="Reset example tasks")
def reset_tasks() -> list[Task]:
    tasks.clear()
    tasks.extend(task.model_copy() for task in INITIAL_TASKS)
    return tasks
