"""
Exchange Web Services (EWS) client via exchangelib.

Erforderliche Azure AD Application-Berechtigung:
  Office 365 Exchange Online → Application → full_access_as_app
  (Admin-Zustimmung erforderlich)

Hinzufügen in Azure AD:
  App-Registrierungen → API-Berechtigungen → Berechtigung hinzufügen
  → APIs, die meine Organisation verwendet → "Office 365 Exchange Online"
  → Anwendungsberechtigungen → full_access_as_app → Admin-Zustimmung erteilen

Dokumentation: https://ecederstrand.github.io/exchangelib/
"""
import asyncio
import logging

from app.config import settings

logger = logging.getLogger(__name__)

# ── Availability guard ─────────────────────────────────────────────────────────

try:
    # Identity is in the main exchangelib namespace (not exchangelib.credentials)
    from exchangelib import (
        Account,
        Configuration,
        Identity,
        IMPERSONATION,
        OAUTH2,
        Mailbox,
        OAuth2Credentials,
    )
    from exchangelib.properties import DelegateUser, DelegatePermissions, UserId as EWSUserId
    from exchangelib.properties import DLMailbox  # mailbox type used by GetDelegate
    from exchangelib.services import GetDelegate  # type: ignore[attr-defined]
    from exchangelib.services.common import EWSAccountService
    from exchangelib.util import MNS, create_element, set_xml_value
    from exchangelib.version import EXCHANGE_2007_SP1

    EXCHANGELIB_AVAILABLE = True
    logger.info("exchangelib loaded successfully")
except ImportError as _import_err:
    logger.warning("exchangelib nicht verfügbar: %s", _import_err)
    EXCHANGELIB_AVAILABLE = False


# ── Custom EWS services missing in exchangelib 4.x ────────────────────────────

if EXCHANGELIB_AVAILABLE:

    class _AddDelegate(EWSAccountService):
        """
        EWS AddDelegate service — not included in exchangelib 4.x, implemented manually.
        Docs: https://docs.microsoft.com/en-us/exchange/client-developer/web-service-reference/adddelegate-operation
        """
        SERVICE_NAME = "AddDelegate"
        ERRORS_TO_CATCH_IN_RESPONSE = ()
        supported_from = EXCHANGE_2007_SP1

        def call(self, delegate_user: "DelegateUser") -> None:
            """Send AddDelegate request; raise on error, return nothing on success."""
            # We consume the generator to trigger request + error-checking
            list(self._get_elements(payload=self.get_payload(delegate_user=delegate_user)))

        def get_payload(self, delegate_user: "DelegateUser"):
            payload = create_element(
                "m:AddDelegate",
                attrs={"DeliverMeetingRequests": "DelegatesAndSendInformationToMe"},
            )
            set_xml_value(
                payload,
                DLMailbox(email_address=self.account.primary_smtp_address),
                version=self.protocol.version,
            )
            delegates_elem = create_element("m:DelegateUsers")
            set_xml_value(delegates_elem, delegate_user, version=self.protocol.version)
            payload.append(delegates_elem)
            return payload

        @classmethod
        def _get_elements_in_container(cls, container):
            # We don't need to parse the returned DelegateUser from the response
            return []

        @classmethod
        def _response_message_tag(cls):
            return f"{{{MNS}}}DelegateUserResponseMessageType"

    class _RemoveDelegate(EWSAccountService):
        """
        EWS RemoveDelegate service — not included in exchangelib 4.x, implemented manually.
        Docs: https://docs.microsoft.com/en-us/exchange/client-developer/web-service-reference/removedelegate-operation
        """
        SERVICE_NAME = "RemoveDelegate"
        ERRORS_TO_CATCH_IN_RESPONSE = ()
        supported_from = EXCHANGE_2007_SP1

        def call(self, delegate_smtp: str) -> None:
            """Send RemoveDelegate request; raise on error."""
            list(self._get_elements(payload=self.get_payload(delegate_smtp=delegate_smtp)))

        def get_payload(self, delegate_smtp: str):
            payload = create_element("m:RemoveDelegate")
            set_xml_value(
                payload,
                DLMailbox(email_address=self.account.primary_smtp_address),
                version=self.protocol.version,
            )
            user_ids_elem = create_element("m:UserIds")
            set_xml_value(
                user_ids_elem,
                EWSUserId(primary_smtp_address=delegate_smtp),
                version=self.protocol.version,
            )
            payload.append(user_ids_elem)
            return payload

        @classmethod
        def _get_elements_in_container(cls, container):
            return []

        @classmethod
        def _response_message_tag(cls):
            return f"{{{MNS}}}DelegateUserResponseMessageType"


# ── Permission level constants ─────────────────────────────────────────────────

PERM_LEVELS = ("None", "Reviewer", "Author", "Editor")
PERM_LABELS: dict[str, str] = {
    "None":     "Kein Zugriff",
    "Reviewer": "Nur lesen",
    "Author":   "Erstellen (Lesen + Erstellen)",
    "Editor":   "Vollzugriff (Lesen, Erstellen, Bearbeiten, Löschen)",
}


class ExchangeError(Exception):
    """Raised when an EWS operation fails."""


# ── Internal helpers ───────────────────────────────────────────────────────────

def _build_account(smtp_address: str) -> "Account":
    """Create an exchangelib Account using OAuth2 client-credentials (app-only)."""
    creds = OAuth2Credentials(
        client_id=settings.azure_client_id,
        client_secret=settings.azure_client_secret,
        tenant_id=settings.azure_tenant_id,
        identity=Identity(primary_smtp_address=smtp_address),
    )
    config = Configuration(
        server="outlook.office365.com",
        credentials=creds,
        auth_type=OAUTH2,
    )
    return Account(
        primary_smtp_address=smtp_address,
        config=config,
        autodiscover=False,
        access_type=IMPERSONATION,
    )


def _perm_level_str(obj) -> str:
    """Safely convert an EWS permission level enum to a string."""
    if obj is None:
        return "None"
    s = str(obj)
    for lvl in PERM_LEVELS:
        if s.lower() == lvl.lower():
            return lvl
    return s


# ── Synchronous EWS operations (run in thread pool via asyncio.to_thread) ──────

def _sync_get_delegates(smtp_address: str) -> list[dict]:
    """Get EWS delegates for a mailbox. Synchronous — use via asyncio.to_thread."""
    account = _build_account(smtp_address)
    try:
        raw = list(
            GetDelegate(account=account).call(
                user_ids=None,
                include_permissions=True,
            )
        )
    except Exception as exc:
        logger.error("GetDelegate fehlgeschlagen für %s: %s", smtp_address, exc)
        raise ExchangeError(f"EWS GetDelegate fehlgeschlagen: {exc}") from exc

    result: list[dict] = []
    for d in raw:
        uid   = getattr(d, "user_id", None)
        perm  = getattr(d, "delegate_permissions", None)
        email = (
            getattr(uid, "primary_smtp_address", None)
            or getattr(uid, "email_address", None)
            or ""
        )
        name = getattr(uid, "display_name", None) or ""
        result.append(
            {
                "email":          email,
                "name":           name,
                "inbox":          _perm_level_str(getattr(perm, "inbox_folder_permission_level", None)),
                "calendar":       _perm_level_str(getattr(perm, "calendar_folder_permission_level", None)),
                "receive_copies": bool(getattr(d, "receive_copies_of_meeting_messages", False)),
                "view_private":   bool(getattr(d, "view_private_items", False)),
            }
        )
    return result


def _sync_add_delegate(
    mailbox_smtp: str,
    delegate_smtp: str,
    inbox_level: str,
    calendar_level: str,
    receive_copies: bool,
) -> None:
    """Add or update an EWS delegate. Synchronous."""
    account = _build_account(mailbox_smtp)

    delegate = DelegateUser(
        user_id=EWSUserId(primary_smtp_address=delegate_smtp),
        delegate_permissions=DelegatePermissions(
            calendar_folder_permission_level=calendar_level,
            inbox_folder_permission_level=inbox_level,
            tasks_folder_permission_level="None",
            contacts_folder_permission_level="None",
            notes_folder_permission_level="None",
            journal_folder_permission_level="None",
        ),
        receive_copies_of_meeting_messages=receive_copies,
        view_private_items=False,
    )

    try:
        _AddDelegate(account=account).call(delegate_user=delegate)
    except Exception as exc:
        logger.error("AddDelegate fehlgeschlagen für %s → %s: %s", delegate_smtp, mailbox_smtp, exc)
        raise ExchangeError(f"EWS AddDelegate fehlgeschlagen: {exc}") from exc


def _sync_remove_delegate(mailbox_smtp: str, delegate_smtp: str) -> None:
    """Remove an EWS delegate. Synchronous."""
    account = _build_account(mailbox_smtp)
    try:
        _RemoveDelegate(account=account).call(delegate_smtp=delegate_smtp)
    except Exception as exc:
        logger.error("RemoveDelegate fehlgeschlagen für %s: %s", delegate_smtp, exc)
        raise ExchangeError(f"EWS RemoveDelegate fehlgeschlagen: {exc}") from exc


# ── Public async API ───────────────────────────────────────────────────────────

async def get_mailbox_delegates(smtp_address: str) -> list[dict]:
    """
    Liefert die aktuellen EWS-Delegierten eines Postfachs.
    Benötigt full_access_as_app in Exchange Online.
    """
    if not EXCHANGELIB_AVAILABLE:
        raise ExchangeError(
            "exchangelib ist nicht installiert oder nicht lauffähig. "
            "Container neu bauen nach 'pip install exchangelib'."
        )
    return await asyncio.to_thread(_sync_get_delegates, smtp_address)


async def add_mailbox_delegate(
    mailbox_smtp: str,
    delegate_smtp: str,
    inbox_level: str = "Editor",
    calendar_level: str = "None",
    receive_copies: bool = False,
) -> None:
    """
    Fügt einen EWS-Delegierten hinzu (oder aktualisiert bestehenden).
    Benötigt full_access_as_app in Exchange Online.
    """
    if not EXCHANGELIB_AVAILABLE:
        raise ExchangeError("exchangelib ist nicht installiert.")
    inbox_level    = inbox_level    if inbox_level    in PERM_LEVELS else "Editor"
    calendar_level = calendar_level if calendar_level in PERM_LEVELS else "None"
    await asyncio.to_thread(
        _sync_add_delegate,
        mailbox_smtp,
        delegate_smtp,
        inbox_level,
        calendar_level,
        receive_copies,
    )


async def remove_mailbox_delegate(mailbox_smtp: str, delegate_smtp: str) -> None:
    """
    Entfernt einen EWS-Delegierten aus einem Postfach.
    Benötigt full_access_as_app in Exchange Online.
    """
    if not EXCHANGELIB_AVAILABLE:
        raise ExchangeError("exchangelib ist nicht installiert.")
    await asyncio.to_thread(_sync_remove_delegate, mailbox_smtp, delegate_smtp)
