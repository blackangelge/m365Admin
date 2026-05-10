from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import Domain


async def list_domains(
    db: AsyncSession, *, include_deleted: bool = False
) -> list[Domain]:
    q = select(Domain).order_by(
        Domain.is_deleted.asc(),
        Domain.is_default.desc(),
        Domain.name.asc(),
    )
    if not include_deleted:
        q = q.where(Domain.is_deleted.is_(False))
    result = await db.execute(q)
    return list(result.scalars().all())


async def list_active_domain_names(db: AsyncSession) -> list[str]:
    """Return sorted list of non-deleted, verified domain names."""
    result = await db.execute(
        select(Domain.name)
        .where(Domain.is_deleted.is_(False), Domain.is_verified.is_(True))
        .order_by(Domain.is_default.desc(), Domain.name)
    )
    return [r[0] for r in result.fetchall()]


async def sync_domains(
    db: AsyncSession, graph_domains: list[dict]
) -> dict[str, int]:
    """
    Upsert domains from Graph API.

    - Domains present in Graph  → create or update (restore if soft-deleted).
    - Domains absent from Graph → soft-delete (is_deleted=True).

    Returns stats dict: added, restored, updated, soft_deleted, total.
    """
    now = datetime.now(UTC)
    graph_map: dict[str, dict] = {d["id"]: d for d in graph_domains}

    # Load all existing domains (incl. soft-deleted)
    result = await db.execute(select(Domain))
    existing: dict[str, Domain] = {d.name: d for d in result.scalars().all()}

    added = restored = updated = soft_deleted = 0

    # Soft-delete domains no longer present in Graph
    for name, domain in existing.items():
        if name not in graph_map and not domain.is_deleted:
            domain.is_deleted = True
            soft_deleted += 1

    # Upsert domains from Graph
    for name, gd in graph_map.items():
        domain = existing.get(name)
        if domain is None:
            domain = Domain(name=name)
            db.add(domain)
            added += 1
        elif domain.is_deleted:
            domain.is_deleted = False
            restored += 1
        else:
            updated += 1

        domain.is_verified         = bool(gd.get("isVerified", False))
        domain.is_default          = bool(gd.get("isDefault", False))
        domain.is_initial          = bool(gd.get("isInitial", False))
        domain.authentication_type = gd.get("authenticationType")
        domain.synced_at           = now

    await db.commit()
    return {
        "added":        added,
        "restored":     restored,
        "updated":      updated,
        "soft_deleted": soft_deleted,
        "total":        len(graph_map),
    }
