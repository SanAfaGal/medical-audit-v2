"""ORM models for hospitals, admins, contracts, and raw service strings."""
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Hospital(Base):
    __tablename__ = "hospitals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    nit: Mapped[str] = mapped_column(String(20), nullable=False)
    invoice_prefix: Mapped[str] = mapped_column(String(10), nullable=False)
    sihos_url: Mapped[str | None] = mapped_column(String(500))
    sihos_code: Mapped[str | None] = mapped_column(String(50))
    sihos_user: Mapped[str | None] = mapped_column(String(200))
    sihos_password_enc: Mapped[str | None] = mapped_column(Text)            # Fernet-encrypted
    drive_credentials_json_enc: Mapped[str | None] = mapped_column(Text)   # Fernet-encrypted JSON
    base_path: Mapped[str | None] = mapped_column(String(500))

    admins: Mapped[list[Admin]] = relationship(
        back_populates="hospital", cascade="all, delete-orphan"
    )
    periods: Mapped[list[AuditPeriod]] = relationship(
        back_populates="hospital", cascade="all, delete-orphan"
    )
    services: Mapped[list[Service]] = relationship(
        back_populates="hospital", cascade="all, delete-orphan"
    )


class Admin(Base):
    __tablename__ = "admins"
    __table_args__ = (UniqueConstraint("hospital_id", "raw_value"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hospital_id: Mapped[int] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"))
    raw_value: Mapped[str] = mapped_column(String(200), nullable=False)
    canonical_value: Mapped[str | None] = mapped_column(String(200))  # NULL = unmapped

    hospital: Mapped[Hospital] = relationship(back_populates="admins")
    contracts: Mapped[list[Contract]] = relationship(
        back_populates="admin", cascade="all, delete-orphan"
    )


class Contract(Base):
    __tablename__ = "contracts"
    __table_args__ = (UniqueConstraint("admin_id", "raw_value"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_id: Mapped[int] = mapped_column(ForeignKey("admins.id", ondelete="CASCADE"))
    raw_value: Mapped[str] = mapped_column(String(200), nullable=False)
    canonical_value: Mapped[str | None] = mapped_column(String(200))

    admin: Mapped[Admin] = relationship(back_populates="contracts")


class Service(Base):
    """Raw SIHOS service strings mapped to a ServiceType (user fills in via Settings)."""
    __tablename__ = "services"
    __table_args__ = (UniqueConstraint("hospital_id", "raw_value"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hospital_id: Mapped[int] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"))
    raw_value: Mapped[str] = mapped_column(String(200), nullable=False)
    service_type_id: Mapped[int | None] = mapped_column(ForeignKey("service_types.id"))
    priority: Mapped[int] = mapped_column(Integer, default=0)

    hospital: Mapped[Hospital] = relationship(back_populates="services")


# Deferred import to avoid circular reference at module load
from app.models.period import AuditPeriod  # noqa: E402
