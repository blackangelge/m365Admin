from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting

DEFAULTS: dict[str, str] = {
    "timezone": "Europe/Berlin",
}


async def get_setting(db: AsyncSession, key: str) -> str:
    result = await db.execute(select(AppSetting).where(AppSetting.key == key))
    row = result.scalar_one_or_none()
    if row is None:
        return DEFAULTS.get(key, "")
    return row.value


async def set_setting(db: AsyncSession, key: str, value: str) -> None:
    stmt = insert(AppSetting).values(
        key=key, value=value, updated_at=datetime.now(UTC)
    ).on_conflict_do_update(
        index_elements=["key"],
        set_={"value": value, "updated_at": datetime.now(UTC)},
    )
    await db.execute(stmt)
    await db.commit()


async def get_all_settings(db: AsyncSession) -> dict[str, str]:
    result = await db.execute(select(AppSetting))
    rows = result.scalars().all()
    settings = dict(DEFAULTS)
    for row in rows:
        settings[row.key] = row.value
    return settings
