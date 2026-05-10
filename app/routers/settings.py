from zoneinfo import available_timezones

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.crud.app_setting import get_all_settings, set_setting
from app.database import get_async_db
from app.dependencies import SessionData, get_current_user, require_admin

router = APIRouter(prefix="/settings")
templates = Jinja2Templates(directory="app/templates")

# Pre-sorted list of common/relevant timezones shown first, then all others
_PRIORITY = [
    "Europe/Berlin", "Europe/Vienna", "Europe/Zurich", "Europe/London",
    "Europe/Paris", "Europe/Amsterdam", "Europe/Brussels", "Europe/Warsaw",
    "Europe/Stockholm", "UTC",
    "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
    "Asia/Tokyo", "Asia/Shanghai", "Asia/Dubai", "Australia/Sydney",
]


def _timezone_list() -> list[str]:
    all_tz = sorted(available_timezones())
    priority = [tz for tz in _PRIORITY if tz in all_tz]
    rest = [tz for tz in all_tz if tz not in set(priority)]
    return priority + rest


@router.get("", response_class=HTMLResponse)
async def settings_index(
    request: Request,
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
):
    settings = await get_all_settings(db)
    return templates.TemplateResponse(
        request,
        "settings/index.html",
        {
            "user": current_user,
            "settings": settings,
            "timezones": _timezone_list(),
            "msg": request.query_params.get("msg"),
        },
    )


@router.post("")
async def settings_update(
    current_user=Depends(get_current_user),
    _: SessionData = Depends(require_admin),
    db=Depends(get_async_db),
    timezone: str = Form(...),
):
    if timezone in available_timezones():
        await set_setting(db, "timezone", timezone)
        from app.main import set_active_tz
        set_active_tz(timezone)
    return RedirectResponse(url="/settings?msg=Einstellungen+gespeichert", status_code=303)
