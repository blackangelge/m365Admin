from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.user_log import UserLog


async def log_action(
    db: AsyncSession,
    user_id: int,
    action: str,
    details: str = "",
    ip_address: str = "",
) -> UserLog:
    entry = UserLog(
        user_id=user_id,
        action=action,
        details=details,
        ip_address=ip_address,
    )
    db.add(entry)
    await db.commit()
    return entry


async def get_user_logs(
    db: AsyncSession, user_id: int, limit: int = 100
) -> list[UserLog]:
    result = await db.execute(
        select(UserLog)
        .where(UserLog.user_id == user_id)
        .order_by(UserLog.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_all_logs(db: AsyncSession, limit: int = 200) -> list[UserLog]:
    result = await db.execute(
        select(UserLog)
        .options(selectinload(UserLog.user))
        .order_by(UserLog.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
