from datetime import UTC, datetime

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Domain(Base):
    __tablename__ = "domains"

    id:                  Mapped[int]       = mapped_column(primary_key=True)
    name:                Mapped[str]       = mapped_column(String(255), unique=True, index=True)
    is_verified:         Mapped[bool]      = mapped_column(Boolean, default=False)
    is_default:          Mapped[bool]      = mapped_column(Boolean, default=False)
    is_initial:          Mapped[bool]      = mapped_column(Boolean, default=False)
    authentication_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Soft-delete — domains removed from Graph are kept here
    is_deleted:          Mapped[bool]      = mapped_column(Boolean, default=False)
    synced_at:           Mapped[datetime | None] = mapped_column(nullable=True)
    created_at:          Mapped[datetime]  = mapped_column(
        default=lambda: datetime.now(UTC)
    )

    def __repr__(self) -> str:
        return f"<Domain {self.name!r} verified={self.is_verified} deleted={self.is_deleted}>"
