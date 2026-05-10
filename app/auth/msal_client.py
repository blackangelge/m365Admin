from msal import ConfidentialClientApplication

from app.config import settings


def _get_msal_app() -> ConfidentialClientApplication:
    return ConfidentialClientApplication(
        client_id=settings.azure_client_id,
        authority=settings.authority,
        client_credential=settings.azure_client_secret or None,
    )


_MSAL_RESERVED = {"openid", "profile", "offline_access"}


def build_auth_code_flow() -> dict:
    """
    Start PKCE auth code flow. Returns the flow dict which contains
    'auth_uri' (redirect the user here) and 'code_verifier' (kept server-side).
    The entire dict must be preserved until the callback arrives.
    """
    scopes = [s for s in settings.scopes_list if s not in _MSAL_RESERVED]
    return _get_msal_app().initiate_auth_code_flow(
        scopes=scopes,
        redirect_uri=settings.azure_redirect_uri,
    )


def exchange_code_for_token(flow: dict, auth_response: dict) -> dict:
    """
    Complete the PKCE flow after the callback. Raises ValueError on failure.
    auth_response is the query-param dict from the callback URL.
    """
    result = _get_msal_app().acquire_token_by_auth_code_flow(flow, auth_response)
    if "error" in result:
        raise ValueError(
            result.get("error_description") or result.get("error", "unknown_error")
        )
    return result
