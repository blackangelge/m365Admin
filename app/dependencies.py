from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.session import read_session
from app.database import get_async_db


@dataclass
class SessionData:
    user_id: int
    email: str
    display_name: str
    is_admin: bool


async def require_auth(request: Request) -> SessionData:
    """Dependency for all protected routes. Redirects to login if not authenticated."""
    data = read_session(request)
    if data is None:
        raise HTTPException(
            status_code=302,
            headers={"Location": "/auth/login"},
        )
    return SessionData(**data)


async def get_current_user(
    session: SessionData = Depends(require_auth),
    db: AsyncSession = Depends(get_async_db),
):
    """Load the full User ORM object from DB (includes permissions via selectin)."""
    from app.crud.user import get_user_by_id
    user = await get_user_by_id(db, session.user_id)
    if user is None:
        raise HTTPException(status_code=302, headers={"Location": "/auth/logout"})
    if not user.is_active:
        raise HTTPException(status_code=302, headers={"Location": "/auth/logout"})
    return user


async def require_admin(
    session: SessionData = Depends(require_auth),
) -> SessionData:
    """Additional guard: user must be an admin."""
    if not session.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return session
