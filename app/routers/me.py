from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.crud.user_log import get_user_logs
from app.database import get_async_db
from app.dependencies import get_current_user

router = APIRouter(prefix="/me")
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
async def me_index(
    request: Request,
    current_user=Depends(get_current_user),
):
    return templates.TemplateResponse(
        request,
        "me/index.html",
        {"user": current_user},
    )


@router.get("/logs", response_class=HTMLResponse)
async def me_logs(
    request: Request,
    current_user=Depends(get_current_user),
    db=Depends(get_async_db),
):
    logs = await get_user_logs(db, current_user.id, limit=100)
    return templates.TemplateResponse(
        request,
        "me/logs.html",
        {"user": current_user, "logs": logs},
    )
