from __future__ import annotations

import base64
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from fastapi import Request
from fastapi.responses import Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from clerk_backend_api import Clerk
from clerk_backend_api.models import GetUserListRequest
from clerk_backend_api.security.types import AuthenticateRequestOptions

from config.settings import get_settings

logger = logging.getLogger("research-fetcher")

SESSION_COOKIE = "rf_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7
MAX_USERS = 10
_sdk: Optional[Clerk] = None


@dataclass
class ClerkUser:
    id: str
    display_name: str
    is_admin: bool = False
    username: str = ""
    role: str = "user"


def _env(name: str, *aliases: str) -> str:
    settings = get_settings()
    for key in (name, *aliases):
        value = (os.environ.get(key) or settings.get(key) or "").strip().strip('"').strip("'")
        if value:
            os.environ.setdefault(key, value)
            return value
    return ""


def publishable_key() -> str:
    return _env("CLERK_PUBLISHABLE_KEY", "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY")


def secret_key() -> str:
    return _env("CLERK_SECRET_KEY")


def jwt_key() -> str:
    return _env("CLERK_JWT_KEY")


def frontend_host(key: str | None = None) -> str:
    explicit = _env("CLERK_FRONTEND_API", "CLERK_FAPI_URL")
    if explicit:
        return explicit.replace("https://", "").replace("http://", "").strip("/")
    raw = key or publishable_key()
    if not raw or "_" not in raw:
        return ""
    try:
        payload = raw.split("_", 2)[2]
        pad = "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload + pad).decode("utf-8")
        host = decoded[:-1] if decoded.endswith("$") else decoded
        return host.strip()
    except Exception:
        return ""


def admin_user_ids() -> set[str]:
    raw = _env("CLERK_ADMIN_USER_IDS")
    return {part.strip() for part in raw.split(",") if part.strip()}


def _serializer() -> URLSafeTimedSerializer:
    secret = secret_key() or "research-fetcher-dev-session"
    return URLSafeTimedSerializer(secret, salt="research-fetcher-session")


def get_sdk() -> Optional[Clerk]:
    global _sdk
    secret = secret_key()
    if not secret:
        return None
    if _sdk is None:
        _sdk = Clerk(bearer_auth=secret)
    return _sdk


def _metadata_role(payload: dict[str, Any] | None) -> str:
    meta = (payload or {}).get("public_metadata") or (payload or {}).get("pmd") or {}
    if isinstance(meta, dict) and str(meta.get("role") or "").lower() == "admin":
        return "admin"
    return "user"


def user_is_admin(user_id: str, payload: dict[str, Any] | None = None) -> bool:
    if user_id in admin_user_ids():
        return True
    return _metadata_role(payload) == "admin"


def user_from_payload(user_id: str, payload: dict[str, Any] | None = None) -> ClerkUser:
    data = payload or {}
    username = str(data.get("username") or "")
    name = (
        data.get("name")
        or data.get("email")
        or username
        or data.get("display_name")
        or "User"
    )
    role = "admin" if user_is_admin(user_id, data) else "user"
    return ClerkUser(
        id=user_id,
        display_name=str(name),
        is_admin=role == "admin",
        username=username,
        role=role,
    )


def read_session_cookie(request: Request) -> Optional[ClerkUser]:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        data = _serializer().loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    user_id = str((data or {}).get("id") or "")
    if not user_id:
        return None
    return ClerkUser(
        id=user_id,
        display_name=str(data.get("display_name") or "User"),
        is_admin=bool(data.get("is_admin")),
        username=str(data.get("username") or ""),
        role="admin" if data.get("is_admin") else "user",
    )


def set_session_cookie(response: Response, user: ClerkUser) -> None:
    token = _serializer().dumps(
        {
            "id": user.id,
            "display_name": user.display_name,
            "username": user.username,
            "is_admin": user.is_admin,
        }
    )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def authenticate_bearer(request: Request) -> Optional[ClerkUser]:
    """Verify a Clerk session JWT from Authorization only. Used by /api/session."""
    sdk = get_sdk()
    if sdk is None:
        return None
    options = AuthenticateRequestOptions(
        secret_key=secret_key(),
        jwt_key=jwt_key() or None,
        accepts_token=["session_token"],
    )
    try:
        state = sdk.authenticate_request(request, options)
    except Exception:
        logger.exception("Clerk authenticate_request failed")
        return None
    if not getattr(state, "is_signed_in", False):
        return None
    payload = getattr(state, "payload", None) or {}
    user_id = str(payload.get("sub") or "")
    if not user_id:
        return None
    user = user_from_payload(user_id, payload)
    if not user.is_admin:
        user.is_admin = _bootstrap_admin(user_id)
        user.role = "admin" if user.is_admin else "user"
    return user


def authenticate_request(request: Request) -> Optional[ClerkUser]:
    """App identity is the HttpOnly cookie. Clerk leftovers cannot open HTML pages."""
    return read_session_cookie(request)


def _bootstrap_admin(user_id: str) -> bool:
    """Treat the oldest Clerk user as admin when none are marked yet."""
    if user_id in admin_user_ids():
        return True
    try:
        people = list_clerk_users()
    except Exception:
        return False
    if any(person["role"] == "admin" for person in people):
        return False
    oldest = min(people, key=lambda item: item.get("created_at") or "", default=None)
    return bool(oldest and oldest["id"] == user_id)


def _clerk_user_public(raw: Any, *, treat_oldest_as_admin: bool = False, oldest_id: str = "") -> dict:
    user_id = str(getattr(raw, "id", "") or "")
    username = str(getattr(raw, "username", "") or "")
    first = str(getattr(raw, "first_name", "") or "")
    last = str(getattr(raw, "last_name", "") or "")
    display = " ".join(part for part in (first, last) if part).strip() or username or user_id
    meta = getattr(raw, "public_metadata", None) or {}
    role = "admin" if user_is_admin(user_id, {"public_metadata": meta}) else "user"
    if treat_oldest_as_admin and role != "admin" and user_id == oldest_id:
        role = "admin"
    last_login = getattr(raw, "last_sign_in_at", None)
    created = getattr(raw, "created_at", None)

    def _ts(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, (int, float)):
            seconds = value / 1000 if value > 10_000_000_000 else value
            return datetime.fromtimestamp(seconds).isoformat()
        return str(value)

    return {
        "id": user_id,
        "username": username,
        "display_name": display,
        "role": role,
        "created_at": _ts(created) or "",
        "last_login": _ts(last_login),
    }


def _clerk_user_from_raw(raw: Any) -> ClerkUser:
    public = _clerk_user_public(raw)
    user = ClerkUser(
        id=public["id"],
        display_name=public["display_name"],
        is_admin=public["role"] == "admin",
        username=public["username"],
        role=public["role"],
    )
    if not user.is_admin:
        user.is_admin = _bootstrap_admin(user.id)
        user.role = "admin" if user.is_admin else "user"
    return user


def sign_in_with_password(username: str, password: str) -> Optional[ClerkUser]:
    """Verify username/password with Clerk's Backend API (no browser origin required)."""
    sdk = get_sdk()
    if sdk is None:
        return None
    username = (username or "").strip().lower()
    password = password or ""
    if len(username) < 2 or len(password) < 6:
        return None
    try:
        matches = sdk.users.list(request=GetUserListRequest(username=[username], limit=5)) or []
    except Exception:
        logger.exception("Clerk user lookup failed")
        return None
    raw = next(
        (item for item in matches if str(getattr(item, "username", "") or "").lower() == username),
        None,
    )
    if raw is None:
        return None
    user_id = str(getattr(raw, "id", "") or "")
    if not user_id:
        return None
    try:
        result = sdk.users.verify_password(user_id=user_id, password=password)
    except Exception:
        logger.info("Clerk password verification rejected for %s", username)
        return None
    if not getattr(result, "verified", False):
        return None
    return _clerk_user_from_raw(raw)


def list_clerk_users() -> list[dict]:
    sdk = get_sdk()
    if sdk is None:
        return []
    raw_users = sdk.users.list(request=GetUserListRequest(limit=20)) or []
    people = [_clerk_user_public(item) for item in raw_users]
    if not any(person["role"] == "admin" for person in people) and people:
        oldest = min(people, key=lambda item: item.get("created_at") or "")
        oldest["role"] = "admin"
    return people


def create_clerk_user(username: str, password: str, display_name: str, role: str) -> dict:
    sdk = get_sdk()
    if sdk is None:
        raise RuntimeError("Clerk is not configured")
    if len(list_clerk_users()) >= MAX_USERS:
        raise ValueError("max_users")
    username = (username or "").strip().lower()
    if len(username) < 2:
        raise ValueError("invalid_username")
    if len(password or "") < 6:
        raise ValueError("weak_password")
    role = "admin" if role == "admin" else "user"
    name = (display_name or username).strip()
    parts = name.split(None, 1)
    created = sdk.users.create(
        username=username,
        password=password,
        first_name=parts[0],
        last_name=parts[1] if len(parts) > 1 else "",
        public_metadata={"role": role},
        skip_password_checks=True,
    )
    return _clerk_user_public(created)


def delete_clerk_user(user_id: str) -> None:
    sdk = get_sdk()
    if sdk is None:
        raise RuntimeError("Clerk is not configured")
    sdk.users.delete(user_id=user_id)
