from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.permission import user_permissions_table


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    azure_oid: Mapped[str] = mapped_column(String(64), nullable=False)
    email: Mapped[str] = mapped_column(String(256), nullable=False)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    permissions: Mapped[list["Permission"]] = relationship(
        "Permission",
        secondary=user_permissions_table,
        back_populates="users",
        lazy="selectin",
    )
    logs: Mapped[list["UserLog"]] = relationship(
        "UserLog", back_populates="user"
    )

    __table_args__ = (UniqueConstraint("azure_oid", name="uq_users_azure_oid"),)

    @property
    def is_invited(self) -> bool:
        return self.azure_oid.startswith("invited:")

    @property
    def has_permissions(self) -> bool:
        return self.is_admin or bool(self.permissions)
