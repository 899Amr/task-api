import os
import time
from collections import defaultdict, deque
from typing import Annotated, Any

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase import Client, create_client


load_dotenv()

security = HTTPBearer(auto_error=False)
_failed_logins: dict[str, deque[float]] = defaultdict(deque)
LOGIN_WINDOW_SECONDS = 300
MAX_LOGIN_ATTEMPTS = 5


def get_supabase() -> Client:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be configured")
    return create_client(url, key)


def require_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> Any:
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not credentials.credentials.strip()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        response = get_supabase().auth.get_user(credentials.credentials)
        if response.user is None:
            raise ValueError("User not found")
        return response.user
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def check_login_rate_limit(email: str) -> None:
    now = time.monotonic()
    attempts = _failed_logins[email]
    while attempts and now - attempts[0] > LOGIN_WINDOW_SECONDS:
        attempts.popleft()
    if len(attempts) >= MAX_LOGIN_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again later.",
        )


def record_failed_login(email: str) -> None:
    _failed_logins[email].append(time.monotonic())


def clear_failed_logins(email: str) -> None:
    _failed_logins.pop(email, None)
