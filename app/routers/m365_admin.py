"""M365 Admin Center routes — Microsoft 365 management via Graph API."""
import asyncio
import logging
import secrets
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.database import get_async_db
from app.dependencies import SessionData, get_current_user, require_admin
from app.crud.user_log import log_action
from app.graph.client import GraphError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/m365")
templates = Jinja2Templates(directory="app/templates")


def _tpl(name: str):
    return f"m365/{name}.html"


def _graph_ctx(request, current_user, **extra):
    return {"user": current_user, "msg": request.query_params.get("msg"), **extra}


# ── Aktive User ───────────────────────────────────────────────────────────────

@router.get("/users", response_class=HTMLResponse)
async def m365_users(
    request: Request,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
):
    from app.graph.client import get_users
    from app.crud.domain import list_domains as list_db_domains
    users, graph_error = [], None
    try:
        users = await get_users()
    except GraphError as exc:
        graph_error = str(exc)
    except Exception as exc:
        graph_error = f"Unerwarteter Fehler: {exc}"

    # Domains für den Filter-Dropdown: Admins sehen alle, sonst nur freigegebene
    all_db_domains = await list_db_domains(db, include_deleted=False)
    if current_user.is_admin:
        filter_domains = [d.name for d in all_db_domains if d.is_verified]
    else:
        domain_set: set[str] = set()
        for perm in current_user.permissions:
            for d in perm.domains:
                if d.is_verified:
                    domain_set.add(d.name)
        filter_domains = sorted(domain_set)

    return templates.TemplateResponse(
        request, _tpl("users"),
        _graph_ctx(request, current_user,
                   users=users,
                   graph_error=graph_error,
                   filter_domains=filter_domains),
    )


# ── Statische GET-Routen — MÜSSEN vor /users/{user_id} stehen! ───────────────
# FastAPI matcht Routen in Registrierungsreihenfolge. /users/create käme sonst
# als user_id="create" beim Detail-Handler an.

@router.get("/users/check-email")
async def m365_check_email(
    email: str,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
):
    """Return JSON: {"taken": false} or {"taken": true, "user": "Name", "upn": "..."}"""
    from app.graph.client import find_user_by_proxy_address
    if not email or "@" not in email:
        return JSONResponse({"error": "Ungültige E-Mail-Adresse"}, status_code=400)
    try:
        user = await find_user_by_proxy_address(email.lower().strip())
        if user:
            return JSONResponse({
                "taken": True,
                "user": user.get("displayName") or user.get("userPrincipalName", ""),
                "upn":  user.get("userPrincipalName", ""),
            })
        return JSONResponse({"taken": False})
    except Exception as exc:
        logger.exception("check-email error for %s", email)
        return JSONResponse({"error": str(exc)[:200]}, status_code=500)


@router.get("/users/check-upn")
async def m365_check_upn(
    upn: str,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
):
    """Return JSON: {"available": true|false, "upn": "..."}"""
    from app.graph.client import _graph_get
    if not upn or "@" not in upn:
        return JSONResponse({"error": "Ungültiger UPN"}, status_code=400)
    try:
        await _graph_get(f"/users/{upn}", params={"$select": "id"})
        return JSONResponse({"available": False, "upn": upn})
    except GraphError as exc:
        msg = str(exc)
        if "does not exist" in msg or "Request_ResourceNotFound" in msg or "404" in msg:
            return JSONResponse({"available": True, "upn": upn})
        return JSONResponse({"error": msg}, status_code=400)
    except Exception:
        return JSONResponse({"error": "Prüfung fehlgeschlagen"}, status_code=500)


@router.get("/users/create", response_class=HTMLResponse)
async def m365_users_create_form(
    request: Request,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
):
    from app.graph.client import get_licenses
    from app.crud.domain import list_domains as list_db_domains
    licenses: list[dict] = []
    graph_error: str | None = None

    db_domains = await list_db_domains(db, include_deleted=False)
    custom = [d for d in db_domains if "onmicrosoft.com" not in d.name and d.is_verified]
    domains_obj = custom if custom else [d for d in db_domains if d.is_verified]

    try:
        licenses = await get_licenses()
    except GraphError as exc:
        graph_error = str(exc)
    except Exception as exc:
        graph_error = f"Unerwarteter Fehler: {exc}"

    return templates.TemplateResponse(
        request, _tpl("users_create"),
        _graph_ctx(request, current_user,
                   domains=domains_obj,
                   licenses=licenses,
                   graph_error=graph_error,
                   error=request.query_params.get("error")),
    )


@router.post("/users/create")
async def m365_users_create_submit(
    request: Request,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
):
    from app.graph.client import create_m365_user, assign_user_licenses

    form = await request.form()
    first_name      = (form.get("first_name") or "").strip()
    last_name       = (form.get("last_name") or "").strip()
    display_name    = (form.get("display_name") or "").strip()
    mail_nickname   = (form.get("mail_nickname") or "").strip()
    domain          = (form.get("domain") or "").strip()
    auto_pw         = form.get("auto_password") == "on"
    temp_password   = (form.get("temp_password") or "").strip()
    force_change    = form.get("force_change_password") == "on"
    license_mode    = form.get("license_mode", "assign")
    sku_ids         = list(form.getlist("license_sku_ids"))

    if not display_name:
        display_name = f"{first_name} {last_name}".strip() or mail_nickname

    if not mail_nickname or not domain:
        err = quote_plus("Benutzername und Domain sind Pflichtfelder.")
        return RedirectResponse(url=f"/admin/m365/users/create?error={err}", status_code=303)

    if auto_pw:
        temp_password = secrets.token_urlsafe(12) + "Aa1!"
    elif not temp_password:
        err = quote_plus("Bitte ein temporäres Passwort eingeben oder automatisch generieren lassen.")
        return RedirectResponse(url=f"/admin/m365/users/create?error={err}", status_code=303)

    upn = f"{mail_nickname}@{domain}"
    effective_skus = sku_ids if license_mode == "assign" else []

    try:
        new_user = await create_m365_user(
            display_name=display_name,
            upn=upn,
            mail_nickname=mail_nickname,
            temp_password=temp_password,
            force_change_password=force_change,
        )
        user_id = new_user.get("id")
        if effective_skus and user_id:
            await assign_user_licenses(user_id, effective_skus)

        await log_action(db, current_user.id, "m365_user_created",
                         f"M365-Benutzer '{upn}' erstellt", "")

        if auto_pw:
            msg = quote_plus(f"Benutzer {upn} erstellt. Temporäres Passwort: {temp_password}")
        else:
            msg = quote_plus(f"Benutzer {upn} erfolgreich erstellt.")
        return RedirectResponse(url=f"/admin/m365/users?msg={msg}", status_code=303)

    except GraphError as exc:
        err = quote_plus(str(exc)[:300])
        return RedirectResponse(url=f"/admin/m365/users/create?error={err}", status_code=303)
    except Exception as exc:
        err = quote_plus(f"Unerwarteter Fehler: {str(exc)[:200]}")
        return RedirectResponse(url=f"/admin/m365/users/create?error={err}", status_code=303)


@router.get("/users/offboard", response_class=HTMLResponse)
async def m365_offboard_form(
    request: Request,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
):
    from app.graph.client import get_users
    users, graph_error = [], None
    try:
        users = [u for u in await get_users() if u.get("accountEnabled")]
    except GraphError as exc:
        graph_error = str(exc)
    except Exception as exc:
        graph_error = f"Unerwarteter Fehler: {exc}"
    return templates.TemplateResponse(request, _tpl("users_offboard"),
                                      _graph_ctx(request, current_user,
                                                 users=users, graph_error=graph_error,
                                                 error=request.query_params.get("error")))


@router.get("/users/deleted", response_class=HTMLResponse)
async def m365_users_deleted(
    request: Request,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
):
    from app.graph.client import get_deleted_users
    users, graph_error = [], None
    try:
        users = await get_deleted_users()
    except GraphError as exc:
        graph_error = str(exc)
    except Exception as exc:
        graph_error = f"Unerwarteter Fehler: {exc}"
    return templates.TemplateResponse(request, _tpl("users_deleted"),
                                      _graph_ctx(request, current_user, users=users, graph_error=graph_error))


# ── User Detail — Vollseite (NACH allen statischen Routen!) ──────────────────

@router.get("/users/{user_id}", response_class=HTMLResponse)
async def m365_user_detail_page(
    user_id: str,
    request: Request,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
):
    from app.graph.client import (
        get_user_by_id_full, get_user_memberships, get_user_license_details,
        get_mailbox_settings, get_user_forwarding, get_licenses, get_groups,
    )
    from app.crud.domain import list_domains as list_db_domains
    active_tab = request.query_params.get("tab", "konto")
    graph_error: str | None = None
    profile = memberships = licenses = {}
    mailbox_settings = forwarding = {}
    all_licenses: list[dict] = []
    all_groups: list[dict] = []
    memberships_list: list[dict] = []
    licenses_list: list[dict] = []

    try:
        profile, memberships_list, licenses_list, mailbox_settings, forwarding, all_licenses, all_groups = (
            await asyncio.gather(
                get_user_by_id_full(user_id),
                get_user_memberships(user_id),
                get_user_license_details(user_id),
                get_mailbox_settings(user_id),
                get_user_forwarding(user_id),
                get_licenses(),
                get_groups(),
            )
        )
    except GraphError as exc:
        graph_error = str(exc)
    except Exception as exc:
        logger.exception("Unexpected error loading user detail %s", user_id)
        graph_error = f"Unerwarteter Fehler: {exc}"

    # SKU-IDs already assigned to user
    assigned_sku_ids = {lic["skuId"] for lic in licenses_list}
    # Groups user is already member of
    member_group_ids = {g["id"] for g in memberships_list}
    # DB-synced domains for alias dropdown
    db_domains = await list_db_domains(db)

    # EWS delegates (separate from main gather – can fail without affecting rest of page)
    delegates: list[dict] = []
    delegates_error: str | None = None
    smtp_address = (profile.get("mail") or profile.get("userPrincipalName") or "") if profile else ""
    if smtp_address:
        try:
            from app.exchange.client import get_mailbox_delegates
            delegates = await get_mailbox_delegates(smtp_address)
        except Exception as exc:
            delegates_error = str(exc)

    from app.exchange.client import PERM_LEVELS, PERM_LABELS

    return templates.TemplateResponse(
        request, _tpl("user_detail"),
        {
            "user":            current_user,
            "profile":         profile,
            "mailbox_settings": mailbox_settings,
            "forwarding":      forwarding,
            "licenses":        licenses_list,
            "memberships":     memberships_list,
            "all_licenses":    [l for l in all_licenses if l["skuId"] not in assigned_sku_ids],
            "all_groups":      [g for g in all_groups if g["id"] not in member_group_ids],
            "db_domains":      db_domains,
            "delegates":       delegates,
            "delegates_error": delegates_error,
            "perm_levels":     PERM_LEVELS,
            "perm_labels":     PERM_LABELS,
            "graph_error":     graph_error,
            "active_tab":      active_tab,
            "msg":             request.query_params.get("msg"),
            "error":           request.query_params.get("error"),
        },
    )


@router.post("/users/{user_id}/contact")
async def m365_update_contact(
    user_id: str,
    request: Request,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
):
    from app.graph.client import update_user_contact
    form = await request.form()
    fields = {
        "givenName":       (form.get("givenName") or "").strip(),
        "surname":         (form.get("surname") or "").strip(),
        "displayName":     (form.get("displayName") or "").strip() or None,
        "jobTitle":        (form.get("jobTitle") or "").strip(),
        "department":      (form.get("department") or "").strip(),
        "officeLocation":  (form.get("officeLocation") or "").strip(),
        "mobilePhone":     (form.get("mobilePhone") or "").strip(),
        "businessPhones":  [(form.get("businessPhone") or "").strip()] if (form.get("businessPhone") or "").strip() else [],
        "city":            (form.get("city") or "").strip(),
        "country":         (form.get("country") or "").strip(),
        "usageLocation":   (form.get("usageLocation") or "").strip() or None,
        "companyName":     (form.get("companyName") or "").strip(),
    }
    # Remove None values for businessPhones (list field handled separately)
    if not fields["businessPhones"]:
        fields["businessPhones"] = []
    # Remove displayName=None (keep existing if empty)
    if fields["displayName"] is None:
        del fields["displayName"]
    try:
        await update_user_contact(user_id, fields)
        await log_action(db, current_user.id, "m365_user_contact_updated", f"Kontakt {user_id} aktualisiert", "")
        msg = quote_plus("Kontaktdaten gespeichert.")
        return RedirectResponse(url=f"/admin/m365/users/{user_id}?tab=konto&msg={msg}", status_code=303)
    except GraphError as exc:
        err = quote_plus(str(exc)[:300])
        return RedirectResponse(url=f"/admin/m365/users/{user_id}?tab=konto&error={err}", status_code=303)


@router.post("/users/{user_id}/mailbox-settings")
async def m365_update_mailbox_settings(
    user_id: str,
    request: Request,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
):
    from app.graph.client import update_mailbox_settings
    form = await request.form()
    # Support both naming conventions from template (action= or setting_type=)
    action = form.get("action") or form.get("setting_type", "ooo")

    try:
        if action in ("langtimezone", "lang_tz"):
            locale   = (form.get("locale") or "").strip()
            timezone = (form.get("timeZone") or "").strip()
            settings: dict = {}
            if locale:
                settings["language"] = {"locale": locale}
            if timezone:
                settings["timeZone"] = timezone
            if settings:
                await update_mailbox_settings(user_id, settings)
        else:
            # OOO
            status = form.get("ooo_status", "disabled")
            internal_msg = form.get("internalReplyMessage", "")
            external_msg = form.get("externalReplyMessage", "")
            external_audience = form.get("externalAudience", "all")

            ooo: dict = {
                "automaticRepliesSetting": {
                    "status": status,
                    "internalReplyMessage": internal_msg,
                    "externalReplyMessage": external_msg,
                    "externalAudience": external_audience,
                }
            }
            if status == "scheduled":
                start = form.get("scheduledStartDateTime", "")
                end   = form.get("scheduledEndDateTime", "")
                if start and end:
                    ooo["automaticRepliesSetting"]["scheduledStartDateTime"] = {"dateTime": start, "timeZone": "UTC"}
                    ooo["automaticRepliesSetting"]["scheduledEndDateTime"]   = {"dateTime": end,   "timeZone": "UTC"}
            await update_mailbox_settings(user_id, ooo)

        await log_action(db, current_user.id, "m365_mailbox_settings_updated", f"Postfach {user_id} aktualisiert", "")
        msg = quote_plus("Postfacheinstellungen gespeichert.")
        return RedirectResponse(url=f"/admin/m365/users/{user_id}?tab=postfach&msg={msg}", status_code=303)
    except GraphError as exc:
        err = quote_plus(str(exc)[:300])
        return RedirectResponse(url=f"/admin/m365/users/{user_id}?tab=postfach&error={err}", status_code=303)


@router.post("/users/{user_id}/forwarding")
async def m365_update_forwarding(
    user_id: str,
    request: Request,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
):
    from app.graph.client import update_user_forwarding
    form = await request.form()
    fwd_enabled  = form.get("forwardingEnabled") == "on"
    fwd_address  = (form.get("forwardingSmtpAddress") or "").strip()
    keep_copy    = form.get("deliverToMailboxAndForward") == "on"
    try:
        await update_user_forwarding(
            user_id,
            fwd_address if fwd_enabled and fwd_address else None,
            keep_copy if fwd_enabled else False,
        )
        await log_action(db, current_user.id, "m365_forwarding_updated", f"Weiterleitung {user_id}", "")
        msg = quote_plus("Weiterleitungseinstellungen gespeichert.")
        return RedirectResponse(url=f"/admin/m365/users/{user_id}?tab=postfach&msg={msg}", status_code=303)
    except GraphError as exc:
        err = quote_plus(str(exc)[:300])
        return RedirectResponse(url=f"/admin/m365/users/{user_id}?tab=postfach&error={err}", status_code=303)


@router.post("/users/{user_id}/alias/add")
async def m365_add_alias(
    user_id: str,
    request: Request,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
):
    from app.graph.client import get_user_by_id_full, update_user_proxy_addresses
    form = await request.form()
    # Support both combined email and split username+domain
    alias_combined = (form.get("alias") or "").strip().lower()
    alias_username = (form.get("alias_username") or "").strip().lower()
    alias_domain   = (form.get("alias_domain") or "").strip().lower()
    if alias_username and alias_domain:
        new_alias = f"{alias_username}@{alias_domain}"
    else:
        new_alias = alias_combined
    if not new_alias or "@" not in new_alias:
        err = quote_plus("Ungültige E-Mail-Adresse.")
        return RedirectResponse(url=f"/admin/m365/users/{user_id}?tab=postfach&error={err}", status_code=303)
    try:
        profile = await get_user_by_id_full(user_id)
        proxies: list[str] = list(profile.get("proxyAddresses") or [])
        new_proxy = f"smtp:{new_alias}"
        if new_proxy not in proxies and new_proxy.upper() not in [p.upper() for p in proxies]:
            proxies.append(new_proxy)
            await update_user_proxy_addresses(user_id, proxies)
        await log_action(db, current_user.id, "m365_alias_added", f"Alias {new_alias} für {user_id}", "")
        msg = quote_plus(f"Alias {new_alias} hinzugefügt.")
        return RedirectResponse(url=f"/admin/m365/users/{user_id}?tab=postfach&msg={msg}", status_code=303)
    except GraphError as exc:
        err = quote_plus(str(exc)[:300])
        return RedirectResponse(url=f"/admin/m365/users/{user_id}?tab=postfach&error={err}", status_code=303)


@router.post("/users/{user_id}/alias/remove")
async def m365_remove_alias(
    user_id: str,
    request: Request,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
):
    from app.graph.client import get_user_by_id_full, update_user_proxy_addresses
    form = await request.form()
    alias_to_remove = (form.get("alias") or "").strip()
    try:
        profile = await get_user_by_id_full(user_id)
        proxies: list[str] = list(profile.get("proxyAddresses") or [])
        # Remove the alias (case-insensitive match for smtp:, keep SMTP: primary)
        proxies = [p for p in proxies if p.lower() != f"smtp:{alias_to_remove.lower()}" or p.startswith("SMTP:")]
        await update_user_proxy_addresses(user_id, proxies)
        await log_action(db, current_user.id, "m365_alias_removed", f"Alias {alias_to_remove} entfernt", "")
        msg = quote_plus(f"Alias {alias_to_remove} entfernt.")
        return RedirectResponse(url=f"/admin/m365/users/{user_id}?tab=postfach&msg={msg}", status_code=303)
    except GraphError as exc:
        err = quote_plus(str(exc)[:300])
        return RedirectResponse(url=f"/admin/m365/users/{user_id}?tab=postfach&error={err}", status_code=303)


@router.post("/users/{user_id}/license/add")
async def m365_add_license(
    user_id: str,
    request: Request,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
):
    from app.graph.client import assign_user_licenses
    form = await request.form()
    sku_id = (form.get("sku_id") or "").strip()
    if not sku_id:
        return RedirectResponse(url=f"/admin/m365/users/{user_id}?tab=lizenzen", status_code=303)
    try:
        await assign_user_licenses(user_id, [sku_id])
        await log_action(db, current_user.id, "m365_license_added", f"Lizenz {sku_id} → {user_id}", "")
        msg = quote_plus("Lizenz zugewiesen.")
        return RedirectResponse(url=f"/admin/m365/users/{user_id}?tab=lizenzen&msg={msg}", status_code=303)
    except GraphError as exc:
        err = quote_plus(str(exc)[:300])
        return RedirectResponse(url=f"/admin/m365/users/{user_id}?tab=lizenzen&error={err}", status_code=303)


@router.post("/users/{user_id}/license/remove")
async def m365_remove_license(
    user_id: str,
    request: Request,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
):
    from app.graph.client import remove_user_licenses
    form = await request.form()
    sku_id = (form.get("sku_id") or "").strip()
    if not sku_id:
        return RedirectResponse(url=f"/admin/m365/users/{user_id}?tab=lizenzen", status_code=303)
    try:
        await remove_user_licenses(user_id, [sku_id])
        await log_action(db, current_user.id, "m365_license_removed", f"Lizenz {sku_id} von {user_id} entfernt", "")
        msg = quote_plus("Lizenz entfernt.")
        return RedirectResponse(url=f"/admin/m365/users/{user_id}?tab=lizenzen&msg={msg}", status_code=303)
    except GraphError as exc:
        err = quote_plus(str(exc)[:300])
        return RedirectResponse(url=f"/admin/m365/users/{user_id}?tab=lizenzen&error={err}", status_code=303)


@router.post("/users/{user_id}/group/add")
async def m365_add_to_group(
    user_id: str,
    request: Request,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
):
    from app.graph.client import add_user_to_group
    form = await request.form()
    group_id = (form.get("group_id") or "").strip()
    if not group_id:
        return RedirectResponse(url=f"/admin/m365/users/{user_id}?tab=gruppen", status_code=303)
    try:
        await add_user_to_group(user_id, group_id)
        await log_action(db, current_user.id, "m365_group_member_added", f"User {user_id} → Gruppe {group_id}", "")
        msg = quote_plus("Gruppe hinzugefügt.")
        return RedirectResponse(url=f"/admin/m365/users/{user_id}?tab=gruppen&msg={msg}", status_code=303)
    except GraphError as exc:
        err = quote_plus(str(exc)[:300])
        return RedirectResponse(url=f"/admin/m365/users/{user_id}?tab=gruppen&error={err}", status_code=303)


@router.post("/users/{user_id}/group/remove")
async def m365_remove_from_group(
    user_id: str,
    request: Request,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
):
    from app.graph.client import remove_user_from_group
    form = await request.form()
    group_id = (form.get("group_id") or "").strip()
    if not group_id:
        return RedirectResponse(url=f"/admin/m365/users/{user_id}?tab=gruppen", status_code=303)
    try:
        await remove_user_from_group(user_id, group_id)
        await log_action(db, current_user.id, "m365_group_member_removed", f"User {user_id} aus Gruppe {group_id}", "")
        msg = quote_plus("Aus Gruppe entfernt.")
        return RedirectResponse(url=f"/admin/m365/users/{user_id}?tab=gruppen&msg={msg}", status_code=303)
    except GraphError as exc:
        err = quote_plus(str(exc)[:300])
        return RedirectResponse(url=f"/admin/m365/users/{user_id}?tab=gruppen&error={err}", status_code=303)


# ── EWS Postfach-Freigabe (Delegates via exchangelib) ────────────────────────

@router.post("/users/{user_id}/delegate/add")
async def m365_delegate_add(
    user_id: str,
    request: Request,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
):
    from app.graph.client import get_user_by_id_full
    from app.exchange.client import ExchangeError, add_mailbox_delegate
    form = await request.form()
    delegate_email = (form.get("delegate_email") or "").strip()
    inbox_level    = (form.get("inbox_level") or "Editor").strip()
    cal_level      = (form.get("calendar_level") or "None").strip()
    receive_copies = form.get("receive_copies") == "on"
    if not delegate_email or "@" not in delegate_email:
        err = quote_plus("Ungültige Delegierten-E-Mail-Adresse.")
        return RedirectResponse(url=f"/admin/m365/users/{user_id}?tab=freigabe&error={err}", status_code=303)
    try:
        profile = await get_user_by_id_full(user_id)
        smtp = profile.get("mail") or profile.get("userPrincipalName", "")
        if not smtp:
            raise ExchangeError("Keine primäre E-Mail-Adresse für diesen Benutzer gefunden.")
        await add_mailbox_delegate(smtp, delegate_email, inbox_level, cal_level, receive_copies)
        await log_action(db, current_user.id, "ews_delegate_added",
                         f"Delegierter {delegate_email} → {smtp}", "")
        msg = quote_plus(f"Delegierter {delegate_email} hinzugefügt.")
        return RedirectResponse(url=f"/admin/m365/users/{user_id}?tab=freigabe&msg={msg}", status_code=303)
    except ExchangeError as exc:
        err = quote_plus(str(exc)[:400])
        return RedirectResponse(url=f"/admin/m365/users/{user_id}?tab=freigabe&error={err}", status_code=303)
    except GraphError as exc:
        err = quote_plus(str(exc)[:400])
        return RedirectResponse(url=f"/admin/m365/users/{user_id}?tab=freigabe&error={err}", status_code=303)
    except Exception as exc:
        logger.exception("delegate/add error for user %s", user_id)
        err = quote_plus(f"Unerwarteter Fehler: {exc}"[:300])
        return RedirectResponse(url=f"/admin/m365/users/{user_id}?tab=freigabe&error={err}", status_code=303)


@router.post("/users/{user_id}/delegate/remove")
async def m365_delegate_remove(
    user_id: str,
    request: Request,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
):
    from app.graph.client import get_user_by_id_full
    from app.exchange.client import ExchangeError, remove_mailbox_delegate
    form = await request.form()
    delegate_email = (form.get("delegate_email") or "").strip()
    if not delegate_email:
        return RedirectResponse(url=f"/admin/m365/users/{user_id}?tab=freigabe", status_code=303)
    try:
        profile = await get_user_by_id_full(user_id)
        smtp = profile.get("mail") or profile.get("userPrincipalName", "")
        await remove_mailbox_delegate(smtp, delegate_email)
        await log_action(db, current_user.id, "ews_delegate_removed",
                         f"Delegierter {delegate_email} entfernt von {smtp}", "")
        msg = quote_plus(f"Delegierter {delegate_email} entfernt.")
        return RedirectResponse(url=f"/admin/m365/users/{user_id}?tab=freigabe&msg={msg}", status_code=303)
    except ExchangeError as exc:
        err = quote_plus(str(exc)[:400])
        return RedirectResponse(url=f"/admin/m365/users/{user_id}?tab=freigabe&error={err}", status_code=303)
    except Exception as exc:
        logger.exception("delegate/remove error for user %s", user_id)
        err = quote_plus(f"Unerwarteter Fehler: {exc}"[:300])
        return RedirectResponse(url=f"/admin/m365/users/{user_id}?tab=freigabe&error={err}", status_code=303)


# ── User Detail (JSON, für Offcanvas-Panel) ──────────────────────────────────

@router.get("/users/{user_id}/detail")
async def m365_user_detail(
    user_id: str,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
):
    from app.graph.client import get_user_by_id_full, get_user_memberships, get_user_license_details
    try:
        profile, memberships, licenses = await asyncio.gather(
            get_user_by_id_full(user_id),
            get_user_memberships(user_id),
            get_user_license_details(user_id),
        )
        return JSONResponse({
            "profile": profile,
            "memberships": memberships,
            "licenses": licenses,
        })
    except GraphError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        logger.exception("Unexpected error fetching user detail for %s", user_id)
        return JSONResponse({"error": f"Unerwarteter Fehler: {exc}"}, status_code=500)




@router.post("/users/{user_id}/offboard")
async def m365_offboard_submit(
    user_id: str,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
):
    from app.graph.client import disable_m365_user
    try:
        await disable_m365_user(user_id)
        await log_action(db, current_user.id, "m365_user_offboarded", f"M365-Benutzer {user_id} deaktiviert", "")
        return RedirectResponse(url="/admin/m365/users/offboard?msg=Benutzer+deaktiviert", status_code=303)
    except GraphError as exc:
        return RedirectResponse(url=f"/admin/m365/users/offboard?error={str(exc)[:200]}", status_code=303)


@router.post("/users/{user_id}/restore")
async def m365_restore_user(
    user_id: str,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
):
    from app.graph.client import restore_m365_user
    try:
        await restore_m365_user(user_id)
        await log_action(db, current_user.id, "m365_user_restored", f"M365-Benutzer {user_id} wiederhergestellt", "")
        return RedirectResponse(url="/admin/m365/users/deleted?msg=Benutzer+wiederhergestellt", status_code=303)
    except GraphError as exc:
        return RedirectResponse(url=f"/admin/m365/users/deleted?error={str(exc)[:200]}", status_code=303)


# ── Teams & Gruppen ───────────────────────────────────────────────────────────

@router.get("/groups", response_class=HTMLResponse)
async def m365_groups(
    request: Request,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
):
    from app.graph.client import get_groups
    groups, graph_error = [], None
    try:
        groups = await get_groups()
    except GraphError as exc:
        graph_error = str(exc)
    except Exception as exc:
        graph_error = f"Unerwarteter Fehler: {exc}"
    return templates.TemplateResponse(request, _tpl("groups"),
                                      _graph_ctx(request, current_user, groups=groups, graph_error=graph_error))


@router.get("/groups/deleted", response_class=HTMLResponse)
async def m365_groups_deleted(
    request: Request,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
):
    from app.graph.client import get_deleted_groups
    groups, graph_error = [], None
    try:
        groups = await get_deleted_groups()
    except GraphError as exc:
        graph_error = str(exc)
    except Exception as exc:
        graph_error = f"Unerwarteter Fehler: {exc}"
    return templates.TemplateResponse(request, _tpl("groups_deleted"),
                                      _graph_ctx(request, current_user, groups=groups, graph_error=graph_error))


# ── Freigegebene Postfächer ───────────────────────────────────────────────────

@router.get("/shared-mailboxes", response_class=HTMLResponse)
async def m365_shared_mailboxes(
    request: Request,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
):
    from app.graph.client import get_shared_mailboxes
    mailboxes, graph_error = [], None
    try:
        mailboxes = await get_shared_mailboxes()
    except GraphError as exc:
        graph_error = str(exc)
    except Exception as exc:
        graph_error = f"Unerwarteter Fehler: {exc}"
    return templates.TemplateResponse(request, _tpl("shared_mailboxes"),
                                      _graph_ctx(request, current_user,
                                                 mailboxes=mailboxes,
                                                 graph_error=graph_error,
                                                 error=request.query_params.get("error"),
                                                 action=request.query_params.get("action", "")))


@router.get("/shared-mailboxes/{mailbox_id}/detail", response_class=JSONResponse)
async def m365_shared_mailbox_detail_json(
    mailbox_id: str,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
):
    """JSON endpoint for the flyout — fetched via JS fetch(), no full page reload."""
    from app.graph.client import get_shared_mailbox_full
    try:
        data = await get_shared_mailbox_full(mailbox_id)
        return JSONResponse(data)
    except GraphError as exc:
        logger.error("shared_mailbox_detail_json(%s): %s", mailbox_id, exc)
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        logger.exception("shared_mailbox_detail_json(%s) unexpected", mailbox_id)
        return JSONResponse({"error": f"Unerwarteter Fehler: {exc}"}, status_code=500)


@router.post("/shared-mailboxes/create")
async def m365_shared_mailbox_create(
    request: Request,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
    display_name: str = Form(...),
    mail_nickname: str = Form(...),
    domain: str = Form(...),
):
    from app.graph.client import create_shared_mailbox
    try:
        mb = await create_shared_mailbox(display_name, mail_nickname, domain)
        await log_action(db, current_user.id, "shared_mailbox_create",
                         f"Erstellt: {display_name} ({mail_nickname}@{domain})")
        new_id = mb.get("id", "")
        msg = quote_plus(f"Postfach '{display_name}' wurde erstellt.")
        return RedirectResponse(url=f"/admin/m365/shared-mailboxes?open={new_id}&msg={msg}", status_code=303)
    except GraphError as exc:
        err = quote_plus(str(exc)[:300])
        return RedirectResponse(url=f"/admin/m365/shared-mailboxes?action=create&error={err}", status_code=303)
    except Exception as exc:
        err = quote_plus(f"Unerwarteter Fehler: {exc}"[:300])
        return RedirectResponse(url=f"/admin/m365/shared-mailboxes?action=create&error={err}", status_code=303)


@router.post("/shared-mailboxes/{mailbox_id}/update")
async def m365_shared_mailbox_update(
    mailbox_id: str,
    request: Request,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
    display_name: str = Form(...),
    mail_nickname: str = Form(...),
    show_in_address_list: str = Form("false"),
):
    from app.graph.client import update_shared_mailbox
    try:
        fields = {
            "displayName": display_name,
            "mailNickname": mail_nickname,
            "showInAddressList": show_in_address_list.lower() == "true",
        }
        await update_shared_mailbox(mailbox_id, fields)
        await log_action(db, current_user.id, "shared_mailbox_update",
                         f"Aktualisiert: {mailbox_id} → {display_name}")
        msg = quote_plus("Postfach wurde gespeichert.")
        return RedirectResponse(url=f"/admin/m365/shared-mailboxes?open={mailbox_id}&msg={msg}", status_code=303)
    except GraphError as exc:
        err = quote_plus(str(exc)[:300])
        return RedirectResponse(url=f"/admin/m365/shared-mailboxes?open={mailbox_id}&error={err}", status_code=303)


@router.post("/shared-mailboxes/{mailbox_id}/alias/add")
async def m365_shared_mailbox_alias_add(
    mailbox_id: str,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
    alias: str = Form(...),
):
    from app.graph.client import add_shared_mailbox_alias
    try:
        await add_shared_mailbox_alias(mailbox_id, alias)
        await log_action(db, current_user.id, "shared_mailbox_alias_add",
                         f"Alias hinzugefügt: {alias} → {mailbox_id}")
        msg = quote_plus(f"Alias '{alias}' wurde hinzugefügt.")
        return RedirectResponse(url=f"/admin/m365/shared-mailboxes?open={mailbox_id}&msg={msg}", status_code=303)
    except GraphError as exc:
        err = quote_plus(str(exc)[:300])
        return RedirectResponse(url=f"/admin/m365/shared-mailboxes?open={mailbox_id}&error={err}", status_code=303)


@router.post("/shared-mailboxes/{mailbox_id}/alias/remove")
async def m365_shared_mailbox_alias_remove(
    mailbox_id: str,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
    alias: str = Form(...),
):
    from app.graph.client import remove_shared_mailbox_alias
    try:
        await remove_shared_mailbox_alias(mailbox_id, alias)
        await log_action(db, current_user.id, "shared_mailbox_alias_remove",
                         f"Alias entfernt: {alias} → {mailbox_id}")
        msg = quote_plus(f"Alias '{alias}' wurde entfernt.")
        return RedirectResponse(url=f"/admin/m365/shared-mailboxes?open={mailbox_id}&msg={msg}", status_code=303)
    except GraphError as exc:
        err = quote_plus(str(exc)[:300])
        return RedirectResponse(url=f"/admin/m365/shared-mailboxes?open={mailbox_id}&error={err}", status_code=303)


@router.post("/shared-mailboxes/{mailbox_id}/mailbox-settings")
async def m365_shared_mailbox_settings_update(
    mailbox_id: str,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
    ooo_enabled: str = Form("false"),
    ooo_message: str = Form(""),
    ooo_start: str = Form(""),
    ooo_end: str = Form(""),
):
    from app.graph.client import update_shared_mailbox_settings
    try:
        val = ooo_enabled.lower()
        if val == "scheduled":
            status = "Scheduled"
        elif val == "true":
            status = "AlwaysEnabled"
        else:
            status = "Disabled"
        ms = {
            "automaticRepliesSetting": {
                "status": status,
                "internalReplyMessage": ooo_message,
                "externalReplyMessage": ooo_message,
            }
        }
        if status == "Scheduled":
            if ooo_start:
                ms["automaticRepliesSetting"]["scheduledStartDateTime"] = {
                    "dateTime": f"{ooo_start}T00:00:00", "timeZone": "UTC"
                }
            if ooo_end:
                ms["automaticRepliesSetting"]["scheduledEndDateTime"] = {
                    "dateTime": f"{ooo_end}T23:59:59", "timeZone": "UTC"
                }
        await update_shared_mailbox_settings(mailbox_id, ms)
        await log_action(db, current_user.id, "shared_mailbox_ooo_update",
                         f"Abwesenheit aktualisiert: {mailbox_id}")
        msg = quote_plus("Abwesenheitsnotiz wurde gespeichert.")
        return RedirectResponse(url=f"/admin/m365/shared-mailboxes?open={mailbox_id}&msg={msg}", status_code=303)
    except GraphError as exc:
        err = quote_plus(str(exc)[:300])
        return RedirectResponse(url=f"/admin/m365/shared-mailboxes?open={mailbox_id}&error={err}", status_code=303)


@router.post("/shared-mailboxes/{mailbox_id}/forwarding")
async def m365_shared_mailbox_forwarding(
    mailbox_id: str,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
    forward_to: str = Form(""),
    keep_copy: str = Form("false"),
):
    from app.graph.client import update_shared_mailbox
    try:
        fields: dict = {}
        if forward_to:
            fields["otherMails"] = [forward_to]
        else:
            fields["otherMails"] = []
        await update_shared_mailbox(mailbox_id, fields)
        await log_action(db, current_user.id, "shared_mailbox_fwd_update",
                         f"Weiterleitung gesetzt: {mailbox_id} → {forward_to or 'deaktiviert'}")
        msg = quote_plus("Weiterleitung wurde gespeichert.")
        return RedirectResponse(url=f"/admin/m365/shared-mailboxes?open={mailbox_id}&msg={msg}", status_code=303)
    except GraphError as exc:
        err = quote_plus(str(exc)[:300])
        return RedirectResponse(url=f"/admin/m365/shared-mailboxes?open={mailbox_id}&error={err}", status_code=303)


@router.post("/shared-mailboxes/{mailbox_id}/sent-items")
async def m365_shared_mailbox_sent_items(
    mailbox_id: str,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
    copy_sent_as: str = Form("false"),
    copy_sent_on_behalf: str = Form("false"),
):
    from app.graph.client import update_shared_mailbox_settings
    try:
        ms = {
            "messageCopyForSentAsEnabled": copy_sent_as == "true",
            "messageCopyForSendOnBehalfEnabled": copy_sent_on_behalf == "true",
        }
        await update_shared_mailbox_settings(mailbox_id, ms)
        await log_action(db, current_user.id, "shared_mailbox_sent_items",
                         f"Gesendete Elemente aktualisiert: {mailbox_id}")
        msg = quote_plus("Einstellungen für gesendete Elemente wurden gespeichert.")
        return RedirectResponse(url=f"/admin/m365/shared-mailboxes?open={mailbox_id}&msg={msg}", status_code=303)
    except GraphError as exc:
        err = quote_plus(str(exc)[:300])
        return RedirectResponse(url=f"/admin/m365/shared-mailboxes?open={mailbox_id}&error={err}", status_code=303)


@router.post("/shared-mailboxes/{mailbox_id}/delete")
async def m365_shared_mailbox_delete(
    mailbox_id: str,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
    confirm_name: str = Form(""),
    display_name: str = Form(""),
):
    from app.graph.client import delete_shared_mailbox
    try:
        if confirm_name.strip().lower() != display_name.strip().lower():
            err = quote_plus("Bestätigungsname stimmt nicht überein.")
            return RedirectResponse(url=f"/admin/m365/shared-mailboxes?open={mailbox_id}&error={err}", status_code=303)
        await delete_shared_mailbox(mailbox_id)
        await log_action(db, current_user.id, "shared_mailbox_delete",
                         f"Gelöscht: {mailbox_id} ({display_name})")
        msg = quote_plus(f"Postfach '{display_name}' wurde gelöscht.")
        return RedirectResponse(url=f"/admin/m365/shared-mailboxes?msg={msg}", status_code=303)
    except GraphError as exc:
        err = quote_plus(str(exc)[:300])
        return RedirectResponse(url=f"/admin/m365/shared-mailboxes?open={mailbox_id}&error={err}", status_code=303)


# ── Lizenzen ──────────────────────────────────────────────────────────────────

@router.get("/licenses", response_class=HTMLResponse)
async def m365_licenses(
    request: Request,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
):
    from app.graph.client import get_licenses
    licenses, graph_error = [], None
    try:
        licenses = await get_licenses()
    except GraphError as exc:
        graph_error = str(exc)
    except Exception as exc:
        graph_error = f"Unerwarteter Fehler: {exc}"
    return templates.TemplateResponse(request, _tpl("licenses"),
                                      _graph_ctx(request, current_user,
                                                 licenses=licenses, graph_error=graph_error))
