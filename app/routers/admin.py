import logging
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.crud.permission import (
    assign_permission,
    create_permission,
    delete_permission,
    get_permission,
    list_permissions,
    remove_permission,
    update_permission,
)
from app.features import FEATURE_KEYS, FEATURE_SECTIONS
from app.crud.user import (
    create_invited_user,
    get_user_by_id,
    list_users,
    set_user_active,
    set_user_admin,
)
from app.crud.user_log import get_user_logs, log_action
from app.database import get_async_db
from app.dependencies import SessionData, get_current_user, require_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="app/templates")


# ── Mitarbeiterübersicht ──────────────────────────────────────────────────────

@router.get("/users", response_class=HTMLResponse)
async def admin_users(
    request: Request,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
):
    users = await list_users(db)
    return templates.TemplateResponse(
        request,
        "admin/users.html",
        {"user": current_user, "users": users},
    )


# ── Neuer Benutzer ────────────────────────────────────────────────────────────

@router.get("/users/new", response_class=HTMLResponse)
async def admin_users_new_form(
    request: Request,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
):
    return templates.TemplateResponse(
        request,
        "admin/users_new.html",
        {"user": current_user, "error": request.query_params.get("error")},
    )


@router.post("/users/new")
async def admin_users_new_submit(
    request: Request,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
    email: str = Form(...),
):
    try:
        new_user = await create_invited_user(db, email)
        await log_action(
            db, current_user.id, "user_created",
            f"Benutzer ({email}) erstellt", ""
        )
        return RedirectResponse(url=f"/admin/users/{new_user.id}", status_code=303)
    except ValueError as exc:
        return RedirectResponse(
            url=f"/admin/users/new?error={exc}", status_code=303
        )


# ── Benutzer-Detail ───────────────────────────────────────────────────────────

@router.get("/users/{user_id}", response_class=HTMLResponse)
async def admin_user_detail(
    request: Request,
    user_id: int,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
):
    target = await get_user_by_id(db, user_id)
    if target is None:
        return RedirectResponse(url="/admin/users", status_code=302)
    all_perms = await list_permissions(db)
    user_perm_ids = {p.id for p in target.permissions}
    available_perms = [p for p in all_perms if p.id not in user_perm_ids]
    logs = await get_user_logs(db, user_id, limit=50)
    return templates.TemplateResponse(
        request,
        "admin/user_detail.html",
        {
            "user": current_user,
            "target": target,
            "all_perms": all_perms,
            "user_perm_ids": user_perm_ids,
            "available_perms": available_perms,
            "logs": logs,
            "msg": request.query_params.get("msg"),
        },
    )


@router.post("/users/{user_id}/toggle-active")
async def admin_toggle_active(
    user_id: int,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
):
    target = await get_user_by_id(db, user_id)
    if target and target.id != current_user.id:
        new_state = not target.is_active
        await set_user_active(db, user_id, new_state)
        action = "user_activated" if new_state else "user_deactivated"
        await log_action(db, current_user.id, action, f"Benutzer '{target.email}'", "")
    return RedirectResponse(url=f"/admin/users/{user_id}?msg=gespeichert", status_code=303)


@router.post("/users/{user_id}/toggle-admin")
async def admin_toggle_admin(
    user_id: int,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
):
    target = await get_user_by_id(db, user_id)
    if target and target.id != current_user.id:
        new_state = not target.is_admin
        await set_user_admin(db, user_id, new_state)
        action = "admin_granted" if new_state else "admin_revoked"
        await log_action(db, current_user.id, action, f"Benutzer '{target.email}'", "")
    return RedirectResponse(url=f"/admin/users/{user_id}?msg=gespeichert", status_code=303)


@router.post("/users/{user_id}/permissions/add")
async def admin_add_permission(
    user_id: int,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
    permission_id: int = Form(...),
):
    target = await get_user_by_id(db, user_id)
    perm = await get_permission(db, permission_id)
    if target and perm:
        await assign_permission(db, target, perm)
        await log_action(
            db, current_user.id, "permission_assigned",
            f"Recht '{perm.name}' an '{target.email}' vergeben", ""
        )
    return RedirectResponse(url=f"/admin/users/{user_id}?msg=gespeichert", status_code=303)


@router.post("/users/{user_id}/permissions/{perm_id}/remove")
async def admin_remove_permission(
    user_id: int,
    perm_id: int,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
):
    target = await get_user_by_id(db, user_id)
    perm = await get_permission(db, perm_id)
    if target and perm:
        await remove_permission(db, target, perm)
        await log_action(
            db, current_user.id, "permission_removed",
            f"Recht '{perm.name}' von '{target.email}' entfernt", ""
        )
    return RedirectResponse(url=f"/admin/users/{user_id}?msg=gespeichert", status_code=303)


# ── Rechteverwaltung ──────────────────────────────────────────────────────────

@router.get("/permissions", response_class=HTMLResponse)
async def admin_permissions(
    request: Request,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
):
    from app.crud.domain import list_domains
    perms = await list_permissions(db)
    all_domains = await list_domains(db, include_deleted=False)
    return templates.TemplateResponse(
        request,
        "admin/permissions.html",
        {
            "user":           current_user,
            "perms":          perms,
            "all_domains":    all_domains,
            "feature_sections": FEATURE_SECTIONS,
            "msg":            request.query_params.get("msg"),
            "error":          request.query_params.get("error"),
        },
    )


@router.post("/permissions")
async def admin_create_permission(
    request: Request,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
    name: str = Form(...),
    comment: str = Form(""),
):
    form = await request.form()
    feats = {key: (f"feat_{key}" in form) for key in FEATURE_KEYS}
    domain_ids = [int(v) for v in form.getlist("domain_ids") if v.isdigit()]
    perm = await create_permission(db, name=name, comment=comment, features=feats, domain_ids=domain_ids)
    await log_action(db, current_user.id, "permission_created", f"Recht '{perm.name}' erstellt", "")
    return RedirectResponse(url="/admin/permissions?msg=gespeichert", status_code=303)


@router.post("/permissions/{perm_id}/update")
async def admin_update_permission(
    perm_id: int,
    request: Request,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
    name: str = Form(...),
    comment: str = Form(""),
):
    form = await request.form()
    feats = {key: (f"feat_{key}" in form) for key in FEATURE_KEYS}
    domain_ids = [int(v) for v in form.getlist("domain_ids") if v.isdigit()]
    await update_permission(db, perm_id, name=name, comment=comment, features=feats, domain_ids=domain_ids)
    return RedirectResponse(url="/admin/permissions?msg=gespeichert", status_code=303)


@router.post("/permissions/{perm_id}/delete")
async def admin_delete_permission(
    perm_id: int,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
):
    perm = await get_permission(db, perm_id)
    if perm:
        await log_action(db, current_user.id, "permission_deleted", f"Recht '{perm.name}' gelöscht", "")
        await delete_permission(db, perm_id)
    return RedirectResponse(url="/admin/permissions?msg=gelöscht", status_code=303)


# ── Domains (DB-backed, synced from Graph) ────────────────────────────────────

@router.get("/domains", response_class=HTMLResponse)
async def admin_domains(
    request: Request,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
):
    from app.crud.domain import list_domains
    domains = await list_domains(db, include_deleted=True)
    return templates.TemplateResponse(
        request,
        "admin/domains.html",
        {
            "user": current_user,
            "domains": domains,
            "msg": request.query_params.get("msg"),
            "error": request.query_params.get("error"),
        },
    )


@router.post("/domains/refresh")
async def admin_domains_refresh(
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
):
    from app.graph.client import get_domains, GraphError
    from app.crud.domain import sync_domains
    try:
        graph_domains = await get_domains()
        stats = await sync_domains(db, graph_domains)
        msg = quote_plus(
            f"Synchronisiert — {stats['added']} neu, {stats['updated']} aktualisiert, "
            f"{stats['restored']} wiederhergestellt, {stats['soft_deleted']} entfernt "
            f"(Gesamt: {stats['total']} Domains)."
        )
        return RedirectResponse(url=f"/admin/domains?msg={msg}", status_code=303)
    except GraphError as exc:
        err = quote_plus(str(exc)[:300])
        return RedirectResponse(url=f"/admin/domains?error={err}", status_code=303)
    except Exception as exc:
        logger.exception("Unexpected error during domain refresh")
        err = quote_plus(f"Unerwarteter Fehler: {str(exc)[:200]}")
        return RedirectResponse(url=f"/admin/domains?error={err}", status_code=303)


# ── CRUD DB-Browser ───────────────────────────────────────────────────────────

async def _get_valid_tables() -> set[str]:
    from app.database import async_engine
    async with async_engine.connect() as conn:
        result = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
        )
        return {r[0] for r in result.fetchall()}


@router.get("/crud", response_class=HTMLResponse)
async def admin_crud_home(
    request: Request,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
):
    from app.database import async_engine
    valid = await _get_valid_tables()
    tables = []
    async with async_engine.connect() as conn:
        for tbl in sorted(valid):
            cnt = await conn.execute(text(f'SELECT COUNT(*) FROM "{tbl}"'))
            tables.append({"name": tbl, "count": cnt.scalar()})
    return templates.TemplateResponse(
        request, "admin/crud.html",
        {"user": current_user, "tables": tables},
    )


@router.get("/crud/{table_name}", response_class=HTMLResponse)
async def admin_crud_table(
    request: Request,
    table_name: str,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
):
    from app.database import async_engine
    valid = await _get_valid_tables()
    if table_name not in valid:
        return RedirectResponse(url="/admin/crud", status_code=302)

    async with async_engine.connect() as conn:
        schema_res = await conn.execute(text(f'PRAGMA table_info("{table_name}")'))
        columns = schema_res.fetchall()   # (cid, name, type, notnull, dflt, pk)

        data_res = await conn.execute(text(f'SELECT * FROM "{table_name}" LIMIT 500'))
        col_names = list(data_res.keys())
        rows = [list(r) for r in data_res.fetchall()]

    pk_col = next((c[1] for c in columns if c[5] == 1), col_names[0] if col_names else "rowid")

    return templates.TemplateResponse(
        request, "admin/crud_table.html",
        {
            "user": current_user,
            "table_name": table_name,
            "all_tables": sorted(valid),
            "columns": columns,
            "col_names": col_names,
            "rows": rows,
            "pk_col": pk_col,
            "msg": request.query_params.get("msg"),
            "error": request.query_params.get("error"),
        },
    )


@router.post("/crud/{table_name}/update")
async def admin_crud_update(
    request: Request,
    table_name: str,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
):
    from app.database import async_engine
    valid = await _get_valid_tables()
    if table_name not in valid:
        return RedirectResponse(url="/admin/crud", status_code=302)

    form = await request.form()
    pk_col = form.get("__pk_col", "")
    pk_val = form.get("__pk_val", "")
    updates = {k: v for k, v in form.items() if not k.startswith("__")}

    if not pk_col or not updates:
        return RedirectResponse(url=f"/admin/crud/{table_name}?error=Ungültige+Anfrage", status_code=303)

    set_clause = ", ".join(f'"{c}" = :{c}' for c in updates)
    params = {**updates, "_pk": pk_val}
    q = text(f'UPDATE "{table_name}" SET {set_clause} WHERE "{pk_col}" = :_pk')
    try:
        async with async_engine.begin() as conn:
            await conn.execute(q, params)
    except SQLAlchemyError as exc:
        err = str(exc)[:120]
        return RedirectResponse(url=f"/admin/crud/{table_name}?error={err}", status_code=303)
    return RedirectResponse(url=f"/admin/crud/{table_name}?msg=Gespeichert", status_code=303)


@router.post("/crud/{table_name}/delete")
async def admin_crud_delete(
    request: Request,
    table_name: str,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
):
    from app.database import async_engine
    valid = await _get_valid_tables()
    if table_name not in valid:
        return RedirectResponse(url="/admin/crud", status_code=302)

    form = await request.form()
    pk_col = form.get("__pk_col", "")
    pk_val = form.get("__pk_val", "")

    if not pk_col:
        return RedirectResponse(url=f"/admin/crud/{table_name}?error=Ungültige+Anfrage", status_code=303)

    q = text(f'DELETE FROM "{table_name}" WHERE "{pk_col}" = :pk_val')
    try:
        async with async_engine.begin() as conn:
            await conn.execute(q, {"pk_val": pk_val})
    except SQLAlchemyError as exc:
        err = str(exc)[:120]
        return RedirectResponse(url=f"/admin/crud/{table_name}?error={err}", status_code=303)
    return RedirectResponse(url=f"/admin/crud/{table_name}?msg=Zeile+gelöscht", status_code=303)


# ── Admin-Übersicht ────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def admin_index(
    request: Request,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
):
    users = await list_users(db)
    perms = await list_permissions(db)
    return templates.TemplateResponse(
        request,
        "admin/index.html",
        {"user": current_user, "users": users, "perms": perms},
    )
