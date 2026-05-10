import logging

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.auth.msal_client import build_auth_code_flow, exchange_code_for_token
from app.auth.session import (
    clear_flow_cookie,
    clear_session_cookie,
    create_session_cookie,
    read_flow_cookie,
    save_flow_cookie,
)
from app.config import settings
from app.crud.user import get_or_create_user
from app.crud.user_log import log_action
from app.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/login")
async def login(request: Request):
    """Initiate PKCE auth code flow and redirect user to Microsoft login."""
    flow = build_auth_code_flow()
    response = RedirectResponse(url=flow["auth_uri"], status_code=302)
    save_flow_cookie(response, flow)
    return response


@router.get("/callback")
async def auth_callback(request: Request):
    """Handle the redirect from Microsoft after authentication."""
    flow = read_flow_cookie(request)
    if flow is None:
        logger.warning("Auth callback called without a valid flow cookie")
        return RedirectResponse(url="/?error=session_expired", status_code=302)

    auth_response = dict(request.query_params)

    # Microsoft sends 'error' param when the user cancels or auth fails
    if "error" in auth_response:
        logger.warning("Auth error from Microsoft: %s", auth_response.get("error"))
        response = RedirectResponse(url="/?error=auth_cancelled", status_code=302)
        clear_flow_cookie(response)
        return response

    try:
        token_result = exchange_code_for_token(flow, auth_response)
    except ValueError as exc:
        logger.error("Token exchange failed: %s", exc)
        response = RedirectResponse(url="/?error=auth_failed", status_code=302)
        clear_flow_cookie(response)
        return response

    claims = token_result.get("id_token_claims", {})
    oid = claims.get("oid", "")
    email = claims.get("preferred_username") or claims.get("email", "")
    display_name = claims.get("name", email)

    if not oid:
        logger.error("No OID in token claims: %s", claims)
        response = RedirectResponse(url="/?error=auth_failed", status_code=302)
        clear_flow_cookie(response)
        return response

    ip = request.client.host if request.client else ""
    async with AsyncSessionLocal() as db:
        user, created = await get_or_create_user(db, oid, email, display_name)
        await log_action(db, user.id, "login", f"Anmeldung über Azure AD", ip)

    if not user.is_active:
        response = RedirectResponse(url="/?error=account_disabled", status_code=302)
        clear_flow_cookie(response)
        return response

    if created:
        logger.info("New user registered: %s (%s)", display_name, email)

    session_payload = {
        "user_id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "is_admin": user.is_admin,
    }

    response = RedirectResponse(url="/", status_code=302)
    create_session_cookie(response, session_payload)
    clear_flow_cookie(response)
    return response


@router.get("/logout")
async def logout(request: Request):
    """Clear session and redirect to Microsoft logout."""
    logout_url = (
        f"https://login.microsoftonline.com/{settings.azure_tenant_id}"
        "/oauth2/v2.0/logout"
        f"?post_logout_redirect_uri={settings.azure_redirect_uri.rsplit('/auth', 1)[0]}/"
    )
    response = RedirectResponse(url=logout_url, status_code=302)
    clear_session_cookie(response)
    return response
