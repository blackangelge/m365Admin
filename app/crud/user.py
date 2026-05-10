from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.user import User


async def get_user_by_oid(db: AsyncSession, oid: str) -> User | None:
    result = await db.execute(select(User).where(User.azure_oid == oid))
    return result.scalar_one_or_none()


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(
        select(User).where(User.email == email.lower())
    )
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: int) -> User | None:
    result = await db.execute(
        select(User)
        .options(selectinload(User.permissions))
        .where(User.id == user_id)
    )
    return result.scalar_one_or_none()


async def get_or_create_user(
    db: AsyncSession, oid: str, email: str, display_name: str
) -> tuple[User, bool]:
    """Return (user, created). Handles invited users on first real login."""
    user = await get_user_by_oid(db, oid)
    created = False

    if user is None:
        # Check for a pre-registered user (azure_oid starts with "invited:")
        user = await get_user_by_email(db, email.lower())
        if user is not None:
            user.azure_oid = oid  # link real Azure OID
        else:
            user = User(azure_oid=oid, email=email.lower(), display_name=display_name)
            db.add(user)
            created = True

    user.email = email.lower()
    user.display_name = display_name
    user.last_login_at = datetime.now(UTC)
    if settings.admin_email and email.lower() == settings.admin_email.lower():
        user.is_admin = True

    await db.commit()
    await db.refresh(user)
    return user, created


def _derive_display_name(upn: str) -> str:
    """Turn 'max.mustermann@contoso.com' → 'Max Mustermann'."""
    local = upn.split("@")[0]
    return " ".join(
        w.capitalize() for w in local.replace(".", " ").replace("-", " ").split()
    )


async def create_invited_user(
    db: AsyncSession, email: str, display_name: str | None = None
) -> User:
    """Pre-register a user so they can be assigned permissions before first login."""
    existing = await get_user_by_email(db, email.lower())
    if existing:
        raise ValueError("E-Mail-Adresse ist bereits registriert.")
    if not display_name:
        display_name = _derive_display_name(email)
    user = User(
        azure_oid=f"invited:{email.lower()}",
        email=email.lower(),
        display_name=display_name,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def list_users(
    db: AsyncSession, skip: int = 0, limit: int = 200
) -> list[User]:
    result = await db.execute(
        select(User)
        .options(selectinload(User.permissions))
        .order_by(User.display_name)
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def set_user_active(
    db: AsyncSession, user_id: int, active: bool
) -> User | None:
    user = await get_user_by_id(db, user_id)
    if user is None:
        return None
    user.is_active = active
    await db.commit()
    await db.refresh(user)
    return user


async def set_user_admin(
    db: AsyncSession, user_id: int, is_admin: bool
) -> User | None:
    user = await get_user_by_id(db, user_id)
    if user is None:
        return None
    user.is_admin = is_admin
    await db.commit()
    await db.refresh(user)
    return user
