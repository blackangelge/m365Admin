import json

from fastapi import Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import settings

_serializer = URLSafeTimedSerializer(settings.app_secret_key)

SESSION_MAX_AGE = 8 * 3600   # 8 hours
FLOW_MAX_AGE = 10 * 60       # 10 minutes — only for the PKCE flow cookie


# ── Session cookie (authenticated user) ─────────────────────────────────────

def create_session_cookie(response: Response, payload: dict) -> None:
    token = _serializer.dumps(payload, salt="session")
    response.set_cookie(
        key=settings.app_session_cookie_name,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=SESSION_MAX_AGE,
    )


def read_session(request: Request) -> dict | None:
    raw = request.cookies.get(settings.app_session_cookie_name)
    if not raw:
        return None
    try:
        return _serializer.loads(raw, salt="session", max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(settings.app_session_cookie_name)


# ── Flow cookie (transient — between /auth/login and /auth/callback) ─────────

_FLOW_COOKIE = "m365admin_flow"


def save_flow_cookie(response: Response, flow: dict) -> None:
    # flow dict may contain non-string types; serialise via json first
    token = _serializer.dumps(json.dumps(flow), salt="flow")
    response.set_cookie(
        key=_FLOW_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=FLOW_MAX_AGE,
    )


def read_flow_cookie(request: Request) -> dict | None:
    raw = request.cookies.get(_FLOW_COOKIE)
    if not raw:
        return None
    try:
        payload = _serializer.loads(raw, salt="flow", max_age=FLOW_MAX_AGE)
        return json.loads(payload)
    except (BadSignature, SignatureExpired, json.JSONDecodeError):
        return None


def clear_flow_cookie(response: Response) -> None:
    response.delete_cookie(_FLOW_COOKIE)
