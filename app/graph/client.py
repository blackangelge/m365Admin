"""Microsoft Graph API client (app-only / client-credentials flow)."""
import logging

import httpx
import msal

from app.config import settings

logger = logging.getLogger(__name__)
GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# ── Friendly SKU name mapping ─────────────────────────────────────────────────
# Sources: Microsoft Product Names and Service Plan Identifiers
# https://learn.microsoft.com/en-us/entra/identity/users/licensing-service-plan-reference
_SKU_NAMES: dict[str, str] = {
    # ── Microsoft 365 Business ────────────────────────────────────────────────
    "O365_BUSINESS_ESSENTIALS":         "Microsoft 365 Business Basic",
    "O365_BUSINESS_PREMIUM":            "Microsoft 365 Business Standard",
    "O365_BUSINESS":                    "Microsoft 365 Apps for Business",
    "SMB_BUSINESS":                     "Microsoft 365 Apps for Business",
    "SMB_BUSINESS_ESSENTIALS":          "Microsoft 365 Business Basic",
    "SMB_BUSINESS_PREMIUM":             "Microsoft 365 Business Premium",
    "M365_BUSINESS_BASIC":              "Microsoft 365 Business Basic",
    "M365_BUSINESS_STANDARD":           "Microsoft 365 Business Standard",
    "M365_BUSINESS_PREMIUM":            "Microsoft 365 Business Premium",
    "M365_APPS_FOR_BUSINESS":           "Microsoft 365 Apps for Business",

    # ── Microsoft 365 Enterprise ──────────────────────────────────────────────
    "SPE_E3":                           "Microsoft 365 E3",
    "SPE_E5":                           "Microsoft 365 E5",
    "SPE_E3_USGOV_DOD":                 "Microsoft 365 E3 (US Gov DoD)",
    "SPE_E3_USGOV_GCCHIGH":             "Microsoft 365 E3 (US Gov GCC High)",
    "SPE_E5_COMP":                      "Microsoft 365 E5 Compliance",
    "SPE_F1":                           "Microsoft 365 F1",
    "SPE_F3":                           "Microsoft 365 F3",
    "DEVELOPERPACK_E3":                 "Microsoft 365 E3 Developer",
    "DEVELOPERPACK":                    "Office 365 E3 Developer",

    # ── Office 365 ───────────────────────────────────────────────────────────
    "STANDARDPACK":                     "Office 365 E1",
    "STANDARDWOFFPACK":                 "Office 365 E2",
    "ENTERPRISEPACK":                   "Office 365 E3",
    "ENTERPRISEWITHSCAL":               "Office 365 E4",
    "ENTERPRISEPREMIUM":                "Office 365 E5",
    "ENTERPRISEPREMIUM_NOPSTNCONF":     "Office 365 E5 ohne Audio-Konferenz",
    "DESKLESSPACK":                     "Office 365 F3",
    "MIDSIZEPACK":                      "Office 365 Midsize Business",
    "LITEPACK":                         "Office 365 Small Business",
    "LITEPACK_P2":                      "Office 365 Small Business Premium",

    # ── Microsoft 365 Apps ───────────────────────────────────────────────────
    "OFFICESUBSCRIPTION":               "Microsoft 365 Apps for Enterprise",
    "OFFICESUBSCRIPTION_STUDENT":       "Microsoft 365 Apps for Students",
    "OFFICESUBSCRIPTION_FACULTY":       "Microsoft 365 Apps for Faculty",
    "Office_Stu_Win_RDP":               "Office 365 ProPlus Student Advantage",

    # ── Exchange Online ───────────────────────────────────────────────────────
    "EXCHANGESTANDARD":                 "Exchange Online Plan 1",
    "EXCHANGE_S_STANDARD":              "Exchange Online Plan 1",
    "EXCHANGEENTERPRISE":               "Exchange Online Plan 2",
    "EXCHANGE_S_ENTERPRISE":            "Exchange Online Plan 2",
    "EXCHANGE_S_DESKLESS":              "Exchange Online Kiosk",
    "EXCHANGEARCHIVE_ADDON":            "Exchange Online Archivierung (für Exchange Server)",
    "EXCHANGEARCHIVE":                  "Exchange Online Archivierung (für Exchange Online)",
    "EXCHANGE_S_ESSENTIALS":            "Exchange Online Essentials",
    "EOP_ENTERPRISE":                   "Exchange Online Protection",
    "EOP_ENTERPRISE_PREMIUM":           "Exchange Online Protection Premium",

    # ── SharePoint Online ─────────────────────────────────────────────────────
    "SHAREPOINTSTANDARD":               "SharePoint Online Plan 1",
    "SHAREPOINTENTERPRISE":             "SharePoint Online Plan 2",
    "SHAREPOINT_S_DEVELOPER":           "SharePoint Online Developer",
    "WACONEDRIVESTANDARD":              "OneDrive for Business Plan 1",
    "WACONEDRIVEENTERPRISE":            "OneDrive for Business Plan 2",

    # ── Microsoft Teams ───────────────────────────────────────────────────────
    "TEAMS_FREE":                       "Microsoft Teams (kostenlos)",
    "TEAMS_EXPLORATORY":                "Microsoft Teams Exploratory",
    "TEAMS_COMMERCIAL_TRIAL":           "Microsoft Teams Commercial Cloud Trial",
    "Teams_Room_Standard":              "Microsoft Teams Rooms Standard",
    "Teams_Room_Premium":               "Microsoft Teams Rooms Premium",
    "MCOMEETADV":                       "Microsoft 365 Audio-Konferenz",
    "MCOEV":                            "Microsoft 365 Telefonsystem",
    "MCOEV_VIRTUALUSER":                "Microsoft 365 Telefonsystem – Virtual User",
    "MCOPSTN1":                         "Microsoft 365 Inlandsgesprächsplan",
    "MCOPSTN2":                         "Microsoft 365 Internationaler Gesprächsplan",
    "MCOPSTN_5":                        "Microsoft 365 Inlandsgesprächsplan (120 Min.)",
    "MCOPSTN_6":                        "Microsoft 365 Inlandsgesprächsplan (240 Min.)",
    "MCOIM":                            "Skype for Business Online Plan 1",
    "MCOIMP":                           "Skype for Business Online Plan 1",
    "MCOSTANDARD":                      "Skype for Business Online Plan 2",
    "MCVOICECONF":                      "Skype for Business Online Plan 3",

    # ── Power Platform ────────────────────────────────────────────────────────
    "FLOW_FREE":                        "Power Automate Free",
    "FLOW_P1":                          "Power Automate Plan 1",
    "FLOW_P2":                          "Power Automate Plan 2",
    "FLOW_PER_USER":                    "Power Automate per User",
    "FLOW_PER_USER_DEPT":               "Power Automate per User (Abteilung)",
    "POWERAPPS_VIRAL":                  "Microsoft Power Apps Plan 2 (Test)",
    "POWERAPPS_PER_USER":               "Power Apps per User",
    "POWERAPPS_DEV":                    "Microsoft Power Apps for Developer",
    "POWER_BI_STANDARD":                "Power BI (kostenlos)",
    "POWER_BI_PRO":                     "Power BI Pro",
    "POWER_BI_PREMIUM_PER_USER":        "Power BI Premium per User",
    "POWER_BI_PREMIUM_PER_USER_ADDON":  "Power BI Premium per User Add-On",

    # ── Dynamics 365 ─────────────────────────────────────────────────────────
    "DYN365_ENTERPRISE_PLAN1":          "Dynamics 365 Customer Engagement Plan",
    "DYN365_ENTERPRISE_SALES":          "Dynamics 365 Sales Enterprise",
    "DYN365_ENTERPRISE_CUSTOMER_SERVICE": "Dynamics 365 Customer Service Enterprise",
    "DYN365_ENTERPRISE_FIELD_SERVICE":  "Dynamics 365 Field Service",
    "DYN365_FINANCIALS_BUSINESS_SKU":   "Dynamics 365 Business Central Essentials",
    "DYN365_BUSINESS_PREMIUM":          "Dynamics 365 Business Central Premium",
    "CRMSTANDARD":                      "Dynamics CRM Online Professional",
    "CRMPLAN2":                         "Dynamics CRM Online Basic",
    "CRMSTORAGE":                       "Dynamics CRM Online Additional Storage",
    "FORMS_PRO":                        "Dynamics 365 Customer Voice",

    # ── Security & Compliance ─────────────────────────────────────────────────
    "AAD_PREMIUM":                      "Microsoft Entra ID P1",
    "AAD_PREMIUM_P2":                   "Microsoft Entra ID P2",
    "AAD_BASIC":                        "Microsoft Entra ID Basic",
    "EMS":                              "Enterprise Mobility + Security E3",
    "EMSPREMIUM":                       "Enterprise Mobility + Security E5",
    "INTUNE_A":                         "Microsoft Intune Plan 1",
    "INTUNE_A_D":                       "Microsoft Intune Device",
    "INTUNE_EDU":                       "Intune for Education",
    "RMS_S_ENTERPRISE":                 "Azure Rights Management",
    "RIGHTSMANAGEMENT":                 "Azure Information Protection Plan 1",
    "RIGHTSMANAGEMENT_ADHOC":           "Rights Management Adhoc",
    "ATP_ENTERPRISE":                   "Microsoft Defender for Office 365 Plan 1",
    "THREAT_INTELLIGENCE":              "Microsoft Defender for Office 365 Plan 2",
    "WIN_DEF_ATP":                      "Microsoft Defender for Endpoint P2",
    "MDATP_XPLAT":                      "Microsoft Defender for Endpoint P2",
    "ATA":                              "Microsoft Defender for Identity",
    "ADALLOM_STANDALONE":               "Microsoft Defender for Cloud Apps",
    "LOCKBOX_ENTERPRISE":               "Customer Lockbox",
    "INFORMATION_PROTECTION_COMPLIANCE": "Microsoft 365 E5 Compliance",
    "EQUIVIO_ANALYTICS":                "Microsoft Purview eDiscovery & Audit",

    # ── Viva ──────────────────────────────────────────────────────────────────
    "MYANALYTICS_P2":                   "Microsoft Viva Insights",
    "WORKPLACE_ANALYTICS":              "Microsoft Viva Insights (Advanced)",
    "VIVA_GOALS_PRIMARY":               "Microsoft Viva Goals",
    "VIVA_LEARNING_SEEDED":             "Microsoft Viva Learning",
    "VIVA":                             "Microsoft Viva Suite",

    # ── Project & Visio ───────────────────────────────────────────────────────
    "PROJECTESSENTIALS":                "Project Plan 1",
    "PROJECTPREMIUM":                   "Project Plan 5",
    "PROJECTONLINE_PLAN_1":             "Project Plan 3",
    "PROJECTONLINE_PLAN_2":             "Project Plan 5",
    "PROJECTCLIENT":                    "Project Online Desktop Client",
    "PROJECT_P1":                       "Project Plan 1",
    "VISIOCLIENT":                      "Visio Plan 2",
    "VISIOONLINE_PLAN1":                "Visio Plan 1",
    "VISIO_PLAN1_DEPT":                 "Visio Plan 1 (Abteilung)",
    "VISIO_PLAN2_DEPT":                 "Visio Plan 2 (Abteilung)",

    # ── Windows & Sonstiges ───────────────────────────────────────────────────
    "WIN10_PRO_ENT_SUB":                "Windows 10/11 Enterprise E3",
    "WIN10_ENT_A3_FAC":                 "Windows 10 Enterprise A3 für Schüler/Studenten",
    "WIN_DEF_ATP_E5":                   "Windows Defender Advanced Threat Protection",
    "YAMMER_ENTERPRISE":                "Yammer Enterprise",
    "STREAM":                           "Microsoft Stream Plan 2",
    "STREAM_P2":                        "Microsoft Stream Plan 2",
    "MICROSOFT_BUSINESS_CENTER":        "Microsoft Business Center",
}


def friendly_sku_name(sku_part_number: str) -> str:
    return _SKU_NAMES.get(
        sku_part_number,
        sku_part_number.replace("_", " ").title(),
    )


class GraphError(Exception):
    """Raised when a Graph API call fails."""


# ── Token ──────────────────────────────────────────────────────────────────────

def _acquire_app_token() -> str:
    """Acquire an app-only token via client-credentials flow."""
    app = msal.ConfidentialClientApplication(
        client_id=settings.azure_client_id,
        client_credential=settings.azure_client_secret,
        authority=settings.authority,
    )
    result = app.acquire_token_for_client(
        scopes=["https://graph.microsoft.com/.default"]
    )
    if "access_token" not in result:
        err = result.get("error_description") or result.get("error", "Unbekannter Fehler")
        raise GraphError(f"Token-Fehler: {err}")
    return result["access_token"]


# ── Low-level HTTP helpers ─────────────────────────────────────────────────────

async def _graph_get(path: str, params: dict | None = None) -> dict:
    token = _acquire_app_token()
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(
            f"{GRAPH_BASE}{path}",
            headers={"Authorization": f"Bearer {token}"},
            params=params or {},
        )
        if resp.status_code == 401:
            raise GraphError("Authentifizierung fehlgeschlagen – prüfe Client-ID und Secret in .env.")
        if resp.status_code == 403:
            raise GraphError(
                "Keine Berechtigung. Bitte stelle sicher, dass die App-Registrierung in Azure AD "
                "die erforderlichen Anwendungsberechtigungen besitzt und Admin-Consent erteilt wurde."
            )
        if resp.status_code == 404:
            raise GraphError("Request_ResourceNotFound: 404")
        resp.raise_for_status()
        return resp.json()


async def _graph_post(path: str, payload: dict) -> dict:
    token = _acquire_app_token()
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            f"{GRAPH_BASE}{path}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
        )
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = ""
            try:
                err_data = resp.json()
                body = err_data.get("error", {}).get("message") or resp.text[:300]
            except Exception:
                body = resp.text[:300]
            raise GraphError(f"Graph API Fehler {resp.status_code}: {body}") from exc
        # 204 No Content → empty dict
        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()


async def _graph_patch(path: str, payload: dict) -> None:
    token = _acquire_app_token()
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.patch(
            f"{GRAPH_BASE}{path}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
        )
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = ""
            try:
                err_data = resp.json()
                body = err_data.get("error", {}).get("message") or resp.text[:300]
            except Exception:
                body = resp.text[:300]
            raise GraphError(f"Graph API Fehler {resp.status_code}: {body}") from exc


async def _graph_delete(path: str) -> None:
    """Send a DELETE request to the Graph API."""
    token = _acquire_app_token()
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.delete(
            f"{GRAPH_BASE}{path}",
            headers={"Authorization": f"Bearer {token}"},
        )
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = ""
            try:
                err_data = resp.json()
                body = err_data.get("error", {}).get("message") or resp.text[:300]
            except Exception:
                body = resp.text[:300]
            raise GraphError(f"Graph API Fehler {resp.status_code}: {body}") from exc


async def _graph_batch(requests: list[dict]) -> list[dict]:
    """
    Execute Graph API $batch calls (max 20 per batch).
    Each item in `requests` must have "method" and "url".
    Assigns auto-incrementing "id" fields.
    """
    token = _acquire_app_token()
    responses: list[dict] = []
    for chunk_start in range(0, len(requests), 20):
        chunk = [
            {"id": str(chunk_start + i), **req}
            for i, req in enumerate(requests[chunk_start: chunk_start + 20])
        ]
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{GRAPH_BASE}/$batch",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"requests": chunk},
            )
            resp.raise_for_status()
        responses.extend(resp.json().get("responses", []))
    return responses


# ── Domains ───────────────────────────────────────────────────────────────────

async def get_domains() -> list[dict]:
    """List all domains in the tenant. Requires Domain.Read.All."""
    data = await _graph_get("/domains")
    return data.get("value", [])


# ── Users ─────────────────────────────────────────────────────────────────────

_USER_LIST_SELECT = (
    "id,displayName,userPrincipalName,accountEnabled,createdDateTime,assignedLicenses"
)
_USER_DETAIL_SELECT = (
    "id,displayName,userPrincipalName,mail,accountEnabled,createdDateTime,"
    "givenName,surname,jobTitle,department,officeLocation,mobilePhone,"
    "businessPhones,usageLocation,preferredLanguage,proxyAddresses,assignedLicenses"
)


async def _build_sku_map() -> dict[str, str]:
    """Returns {skuId: friendlyName} using subscribed SKUs."""
    try:
        data = await _graph_get("/subscribedSkus", params={"$select": "skuId,skuPartNumber"})
        return {s["skuId"]: friendly_sku_name(s["skuPartNumber"])
                for s in data.get("value", [])}
    except Exception:
        return {}


async def get_users() -> list[dict]:
    """
    List all users with enriched license names.
    Requires User.Read.All + Organization.Read.All (for SKU mapping).
    """
    sku_map = await _build_sku_map()
    data = await _graph_get("/users", params={
        "$select": _USER_LIST_SELECT, "$top": "999",
    })
    users = data.get("value", [])
    for u in users:
        lics = u.get("assignedLicenses") or []
        u["licenseNames"] = [sku_map.get(l["skuId"], l["skuId"]) for l in lics]
    return sorted(users, key=lambda u: (u.get("displayName") or "").lower())


async def get_user_by_id_full(user_id: str) -> dict:
    """Full user profile. Requires User.Read.All."""
    return await _graph_get(f"/users/{user_id}", params={"$select": _USER_DETAIL_SELECT})


async def get_user_memberships(user_id: str) -> list[dict]:
    """Group memberships. Requires User.Read.All."""
    data = await _graph_get(f"/users/{user_id}/memberOf", params={
        "$select": "id,displayName,groupTypes,mail", "$top": "50",
    })
    return data.get("value", [])


async def get_user_license_details(user_id: str) -> list[dict]:
    """License details with friendly names. Requires User.Read.All."""
    data = await _graph_get(f"/users/{user_id}/licenseDetails",
                            params={"$select": "id,skuId,skuPartNumber"})
    lics = data.get("value", [])
    for lic in lics:
        lic["friendlyName"] = friendly_sku_name(lic.get("skuPartNumber", ""))
    return lics


async def get_deleted_users() -> list[dict]:
    """Soft-deleted users. Requires Directory.Read.All."""
    data = await _graph_get(
        "/directory/deletedItems/microsoft.graph.user",
        params={"$select": "id,displayName,userPrincipalName,deletedDateTime", "$top": "100"},
    )
    return data.get("value", [])


async def create_m365_user(
    display_name: str,
    upn: str,
    mail_nickname: str,
    temp_password: str,
    force_change_password: bool = True,
) -> dict:
    """Create a new M365 user. Requires User.ReadWrite.All."""
    return await _graph_post("/users", {
        "accountEnabled": True,
        "displayName": display_name,
        "mailNickname": mail_nickname,
        "userPrincipalName": upn,
        "passwordProfile": {
            "forceChangePasswordNextSignIn": force_change_password,
            "password": temp_password,
        },
    })


async def assign_user_licenses(user_id: str, sku_ids: list[str]) -> None:
    """Assign licences to a user. Requires User.ReadWrite.All."""
    if not sku_ids:
        return
    await _graph_post(f"/users/{user_id}/assignLicense", {
        "addLicenses": [{"skuId": sid} for sid in sku_ids],
        "removeLicenses": [],
    })


async def disable_m365_user(user_id: str) -> None:
    """Disable (offboard) an M365 user. Requires User.ReadWrite.All."""
    await _graph_patch(f"/users/{user_id}", {"accountEnabled": False})


async def restore_m365_user(user_id: str) -> None:
    """Restore a soft-deleted user. Requires Directory.ReadWrite.All."""
    await _graph_post(f"/directory/deletedItems/{user_id}/restore", {})


# ── Shared Mailboxes ──────────────────────────────────────────────────────────

async def get_shared_mailboxes() -> list[dict]:
    """
    Return only actual Exchange Online shared mailboxes by checking
    mailboxSettings.userPurpose via $batch.

    Required permissions (Application):
      • User.Read.All          — list all users
      • MailboxSettings.Read   — read mailboxSettings per user
    """
    # 1. Get all users
    users_data = await _graph_get("/users", params={
        "$select": "id,displayName,userPrincipalName,mail",
        "$top": "999",
    })
    all_users = users_data.get("value", [])
    if not all_users:
        return []

    # 2. Build index for batch response mapping
    idx_map = {str(i): u for i, u in enumerate(all_users)}
    batch_reqs = [
        {"method": "GET", "url": f"/users/{u['id']}/mailboxSettings"}
        for u in all_users
    ]

    # 3. Execute batch (auto-chunked to 20)
    responses = await _graph_batch(batch_reqs)

    # 4. Collect shared mailboxes
    shared: list[dict] = []
    for resp in responses:
        if resp.get("status") == 200:
            body = resp.get("body", {})
            if body.get("userPurpose") == "shared":
                user = idx_map.get(resp["id"], {}).copy()
                user["mailboxPurpose"] = "shared"
                shared.append(user)

    return sorted(shared, key=lambda u: (u.get("displayName") or "").lower())


# ── Groups / Teams ────────────────────────────────────────────────────────────

_GROUP_SELECT = "id,displayName,description,groupTypes,mail,createdDateTime"


async def get_groups() -> list[dict]:
    """List all groups/teams (sorted client-side). Requires Group.Read.All."""
    data = await _graph_get("/groups", params={"$select": _GROUP_SELECT, "$top": "999"})
    groups = data.get("value", [])
    return sorted(groups, key=lambda g: (g.get("displayName") or "").lower())


async def get_deleted_groups() -> list[dict]:
    """Soft-deleted groups. Requires Directory.Read.All."""
    data = await _graph_get(
        "/directory/deletedItems/microsoft.graph.group",
        params={"$select": "id,displayName,deletedDateTime", "$top": "100"},
    )
    return data.get("value", [])


# ── Licences ──────────────────────────────────────────────────────────────────

async def get_licenses() -> list[dict]:
    """Subscribed licence SKUs with enriched metadata. Requires Organization.Read.All."""
    data = await _graph_get("/subscribedSkus", params={
        "$select": "skuId,skuPartNumber,prepaidUnits,consumedUnits,capabilityStatus"
    })
    result = []
    for lic in data.get("value", []):
        if lic.get("capabilityStatus") == "Deleted":
            continue
        total = (lic.get("prepaidUnits") or {}).get("enabled", 0)
        used  = lic.get("consumedUnits") or 0
        lic["friendlyName"]    = friendly_sku_name(lic.get("skuPartNumber", ""))
        lic["totalUnits"]      = total
        lic["availableUnits"]  = total - used
        result.append(lic)
    return result


# ── User — Write operations ────────────────────────────────────────────────────

async def update_user_contact(user_id: str, fields: dict) -> None:
    """
    Update writable contact/org fields of a user.
    Requires User.ReadWrite.All.
    Pass only non-None, non-empty fields; empty string → None (clears the field).
    """
    payload: dict = {}
    for key, val in fields.items():
        payload[key] = val if val != "" else None
    if payload:
        await _graph_patch(f"/users/{user_id}", payload)


async def remove_user_licenses(user_id: str, sku_ids: list[str]) -> None:
    """Remove licences from a user. Requires User.ReadWrite.All."""
    if not sku_ids:
        return
    await _graph_post(f"/users/{user_id}/assignLicense", {
        "addLicenses": [],
        "removeLicenses": sku_ids,
    })


async def add_user_to_group(user_id: str, group_id: str) -> None:
    """Add a user to a group. Requires GroupMember.ReadWrite.All or Group.ReadWrite.All."""
    await _graph_post(
        f"/groups/{group_id}/members/$ref",
        {"@odata.id": f"https://graph.microsoft.com/v1.0/users/{user_id}"},
    )


async def remove_user_from_group(user_id: str, group_id: str) -> None:
    """Remove a user from a group. Requires GroupMember.ReadWrite.All or Group.ReadWrite.All."""
    await _graph_delete(f"/groups/{group_id}/members/{user_id}/$ref")


# ── Mailbox settings ──────────────────────────────────────────────────────────

async def get_mailbox_settings(user_id: str) -> dict:
    """
    Read mailbox settings (OOO, language, timezone).
    Requires MailboxSettings.Read.
    """
    try:
        return await _graph_get(f"/users/{user_id}/mailboxSettings")
    except GraphError:
        return {}


async def update_mailbox_settings(user_id: str, settings: dict) -> None:
    """
    Update mailbox settings (OOO, language, timezone).
    Requires MailboxSettings.ReadWrite.
    """
    await _graph_patch(f"/users/{user_id}/mailboxSettings", settings)


async def update_user_forwarding(user_id: str, forwarding_address: str | None, deliver_and_forward: bool) -> None:
    """
    Set email forwarding on a user mailbox.
    Requires User.ReadWrite.All + MailboxSettings.ReadWrite.
    forwardingSmtpAddress format: "smtp:target@domain.com" or None to disable.
    """
    payload: dict = {}
    if forwarding_address:
        smtp = forwarding_address if forwarding_address.lower().startswith("smtp:") else f"smtp:{forwarding_address}"
        payload["forwardingSmtpAddress"] = smtp
        payload["deliverToMailboxAndForward"] = deliver_and_forward
    else:
        # Clear forwarding
        payload["forwardingSmtpAddress"] = None
        payload["deliverToMailboxAndForward"] = False
    await _graph_patch(f"/users/{user_id}", payload)


async def update_user_proxy_addresses(user_id: str, proxy_addresses: list[str]) -> None:
    """
    Replace the full proxyAddresses list.
    Requires User.ReadWrite.All or Directory.ReadWrite.All.
    SMTP: (uppercase) = primary, smtp: (lowercase) = alias.
    """
    await _graph_patch(f"/users/{user_id}", {"proxyAddresses": proxy_addresses})


async def get_user_forwarding(user_id: str) -> dict:
    """
    Read forwarding settings. Tries user resource fields.
    Returns dict with 'forwardingSmtpAddress' and 'deliverToMailboxAndForward'.
    """
    try:
        data = await _graph_get(
            f"/users/{user_id}",
            params={"$select": "id,forwardingSmtpAddress,deliverToMailboxAndForward"},
        )
        return {
            "forwardingSmtpAddress":    data.get("forwardingSmtpAddress") or "",
            "deliverToMailboxAndForward": data.get("deliverToMailboxAndForward") or False,
        }
    except GraphError:
        return {"forwardingSmtpAddress": "", "deliverToMailboxAndForward": False}


async def find_user_by_proxy_address(email: str) -> dict | None:
    """
    Search for a user who has the given email as a proxyAddress, primary mail, or UPN.
    Returns the first match or None.
    Requires User.Read.All + ConsistencyLevel: eventual.
    """
    token = _acquire_app_token()
    email_lower = email.lower().strip()
    # Build filter: check smtp alias, primary SMTP, mail and UPN
    filter_expr = (
        f"proxyAddresses/any(x:x eq 'smtp:{email_lower}') "
        f"or proxyAddresses/any(x:x eq 'SMTP:{email_lower}') "
        f"or mail eq '{email_lower}' "
        f"or userPrincipalName eq '{email_lower}'"
    )
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(
            f"{GRAPH_BASE}/users",
            headers={
                "Authorization": f"Bearer {token}",
                "ConsistencyLevel": "eventual",
            },
            params={
                "$filter": filter_expr,
                "$select": "id,displayName,userPrincipalName",
                "$count": "true",
                "$top": "1",
            },
        )
        if resp.status_code in (400, 404):
            return None
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError:
            return None
        data = resp.json()
        users = data.get("value", [])
        return users[0] if users else None
