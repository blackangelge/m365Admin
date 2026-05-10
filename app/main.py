import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.database import AsyncSessionLocal, init_db
from app.features import FEATURES, user_has_feature

logger = logging.getLogger(__name__)

# ── Timezone cache ────────────────────────────────────────────────────────────
# Loaded from DB on startup, refreshed when settings are saved.
_tz: ZoneInfo = ZoneInfo("Europe/Berlin")


def get_active_tz() -> ZoneInfo:
    return _tz


def set_active_tz(tz_name: str) -> None:
    global _tz
    try:
        _tz = ZoneInfo(tz_name)
    except Exception:
        logger.warning("Unknown timezone %r, keeping current", tz_name)


templates = Jinja2Templates(directory="app/templates")


def _localtime(dt: datetime | None, fmt: str = "%d.%m.%Y %H:%M") -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_tz).strftime(fmt)


templates.env.filters["localtime"] = _localtime
templates.env.globals["features"] = FEATURES
templates.env.globals["user_has_feature"] = user_has_feature


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=logging.DEBUG if settings.app_debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger.info("Starting up — initialising database")
    await init_db()
    logger.info("Database ready")

    # Load persisted timezone
    from app.crud.app_setting import get_setting
    async with AsyncSessionLocal() as db:
        tz_name = await get_setting(db, "timezone")
    set_active_tz(tz_name)
    logger.info("Timezone: %s", _tz)

    yield
    logger.info("Shutting down")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="M365 Admin Dashboard",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = (time.perf_counter() - start) * 1000
    logger.info("%s %s %s %.1fms", request.method, request.url.path, response.status_code, elapsed)
    return response


@app.exception_handler(401)
async def unauthorized_handler(request: Request, exc):
    return templates.TemplateResponse(request, "errors/401.html", status_code=401)


@app.exception_handler(500)
async def internal_error_handler(request: Request, exc):
    logger.exception("Unhandled error: %s", exc)
    return templates.TemplateResponse(request, "errors/500.html", status_code=500)


@app.get("/health", include_in_schema=False)
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


# Router registration
from app.auth.router import router as auth_router              # noqa: E402
from app.routers.dashboard import router as dashboard_router   # noqa: E402
from app.routers.admin import router as admin_router           # noqa: E402
from app.routers.m365_admin import router as m365_admin_router # noqa: E402
from app.routers.me import router as me_router                 # noqa: E402
from app.routers.settings import router as settings_router     # noqa: E402

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth_router, prefix="/auth", tags=["Auth"])
app.include_router(dashboard_router, tags=["Dashboard"])
app.include_router(me_router, tags=["Me"])
app.include_router(admin_router, tags=["Admin"])
app.include_router(m365_admin_router, tags=["M365 Admin"])
app.include_router(settings_router, tags=["Settings"])
