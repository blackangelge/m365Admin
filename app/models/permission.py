from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# ── User ↔ Permission (M2M) ───────────────────────────────────────────────────
user_permissions_table = Table(
    "user_permissions",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", Integer, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)

# ── Permission ↔ Domain (M2M) ─────────────────────────────────────────────────
permission_domains_table = Table(
    "permission_domains",
    Base.metadata,
    Column("permission_id", Integer, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
    Column("domain_id", Integer, ForeignKey("domains.id", ondelete="CASCADE"), primary_key=True),
)


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    comment: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    # ── Feature-Flags (dynamically extended via migration in database.py) ──────
    feat_mitarbeiter_ansehen:   Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    feat_mitarbeiter_verwalten: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    feat_logs_einsehen:         Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    feat_einstellungen:         Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # ── Relationships ─────────────────────────────────────────────────────────
    users: Mapped[list["User"]] = relationship(
        "User", secondary=user_permissions_table, back_populates="permissions"
    )
    domains: Mapped[list["Domain"]] = relationship(
        "Domain", secondary=permission_domains_table, lazy="selectin"
    )

    def has_feature(self, key: str) -> bool:
        return bool(getattr(self, f"feat_{key}", False))

    @property
    def domain_names(self) -> list[str]:
        return [d.name for d in self.domains]
