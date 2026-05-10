import logging
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = logging.getLogger(__name__)

async_engine = create_async_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
    echo=settings.app_debug,
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def _get_columns(conn, table: str) -> set[str]:
    result = await conn.execute(text(f"PRAGMA table_info({table})"))
    return {row[1] for row in result}


async def init_db() -> None:
    """Create all tables, run schema migrations, and enable WAL mode."""
    async with async_engine.begin() as conn:
        await conn.execute(text("PRAGMA journal_mode=WAL"))

        # import models so Base.metadata knows about them
        from app.models import user, permission, user_log, app_setting, domain  # noqa: F401
        from app.features import FEATURE_KEYS, FEATURE_SECTIONS  # noqa: F401

        # ── Permissions schema migration ─────────────────────────────────────
        # If the old schema (label/description/code columns) exists, drop and
        # recreate so the new schema (name/comment/feat_*) is used cleanly.
        perm_cols = await _get_columns(conn, "permissions")
        if perm_cols and "label" in perm_cols:
            logger.info("Migrating permissions table to new schema…")
            await conn.execute(text("DROP TABLE IF EXISTS user_permissions"))
            await conn.execute(text("DROP TABLE IF EXISTS permissions"))

        await conn.run_sync(Base.metadata.create_all)

        # Add any missing feature columns (for upgrades that add new features)
        perm_cols = await _get_columns(conn, "permissions")
        for key in FEATURE_KEYS:
            col = f"feat_{key}"
            if col not in perm_cols:
                logger.info("Adding column permissions.%s", col)
                await conn.execute(
                    text(f"ALTER TABLE permissions ADD COLUMN {col} BOOLEAN NOT NULL DEFAULT 0")
                )
