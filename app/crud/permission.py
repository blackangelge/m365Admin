from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.features import FEATURE_KEYS
from app.models.domain import Domain
from app.models.permission import Permission
from app.models.user import User


async def list_permissions(db: AsyncSession) -> list[Permission]:
    result = await db.execute(
        select(Permission)
        .options(selectinload(Permission.users), selectinload(Permission.domains))
        .order_by(Permission.name)
    )
    return list(result.scalars().all())


async def get_permission(db: AsyncSession, permission_id: int) -> Permission | None:
    result = await db.execute(
        select(Permission)
        .options(selectinload(Permission.users), selectinload(Permission.domains))
        .where(Permission.id == permission_id)
    )
    return result.scalar_one_or_none()


async def _set_domains(db: AsyncSession, perm: Permission, domain_ids: list[int]) -> None:
    """Replace the domain list on a permission."""
    if not domain_ids:
        perm.domains = []
        return
    result = await db.execute(select(Domain).where(Domain.id.in_(domain_ids)))
    perm.domains = list(result.scalars().all())


async def create_permission(
    db: AsyncSession,
    name: str,
    comment: str = "",
    features: dict[str, bool] | None = None,
    domain_ids: list[int] | None = None,
) -> Permission:
    perm = Permission(name=name.strip(), comment=comment.strip())
    if features:
        for key in FEATURE_KEYS:
            if key in features:
                setattr(perm, f"feat_{key}", features[key])
    db.add(perm)
    await db.flush()  # get perm.id before setting domains
    await _set_domains(db, perm, domain_ids or [])
    await db.commit()
    await db.refresh(perm)
    return perm


async def update_permission(
    db: AsyncSession,
    permission_id: int,
    name: str,
    comment: str = "",
    features: dict[str, bool] | None = None,
    domain_ids: list[int] | None = None,
) -> Permission | None:
    perm = await get_permission(db, permission_id)
    if perm is None:
        return None
    perm.name = name.strip()
    perm.comment = comment.strip()
    if features is not None:
        for key in FEATURE_KEYS:
            setattr(perm, f"feat_{key}", features.get(key, False))
    if domain_ids is not None:
        await _set_domains(db, perm, domain_ids)
    await db.commit()
    await db.refresh(perm)
    return perm


async def delete_permission(db: AsyncSession, permission_id: int) -> bool:
    perm = await get_permission(db, permission_id)
    if perm is None:
        return False
    await db.delete(perm)
    await db.commit()
    return True


async def assign_permission(db: AsyncSession, user: User, perm: Permission) -> None:
    if perm not in user.permissions:
        user.permissions.append(perm)
        await db.commit()


async def remove_permission(db: AsyncSession, user: User, perm: Permission) -> None:
    if perm in user.permissions:
        user.permissions.remove(perm)
        await db.commit()
