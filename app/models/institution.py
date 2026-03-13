"""ORM models for institutions, admins, contracts, services, and service-type-document mappings."""
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Institution(Base):
    __tablename__ = "institutions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    nit: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    invoice_id_prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    sihos_base_url: Mapped[str | None] = mapped_column(String(500))
    sihos_doc_code: Mapped[str | None] = mapped_column(String(20))
    sihos_user: Mapped[str | None] = mapped_column(String(200))
    sihos_password: Mapped[str | None] = mapped_column(String(200))  # store encrypted via crypto.py
    base_path: Mapped[str | None] = mapped_column(String(500))
    drive_credentials_enc: Mapped[str | None] = mapped_column(String(10000))  # JSON encrypted via crypto.py

    admins: Mapped[list[Admin]] = relationship(back_populates="institution", cascade="all, delete-orphan")
    contracts: Mapped[list[Contract]] = relationship(back_populates="institution", cascade="all, delete-orphan")
    services: Mapped[list[Service]] = relationship(back_populates="institution", cascade="all, delete-orphan")
    periods: Mapped[list[AuditPeriod]] = relationship(back_populates="institution", cascade="all, delete-orphan")
    service_type_documents: Mapped[list[ServiceTypeDocument]] = relationship(back_populates="institution", cascade="all, delete-orphan")


class Admin(Base):
    __tablename__ = "admins"
    __table_args__ = (UniqueConstraint("institution_id", "raw_admin"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id", ondelete="CASCADE"))
    type: Mapped[str | None] = mapped_column(String(20))   # EPS | SOAT | ARL | NULL
    raw_admin: Mapped[str] = mapped_column(String(300), nullable=False)
    canonical_admin: Mapped[str | None] = mapped_column(String(300))

    institution: Mapped[Institution] = relationship(back_populates="admins")


class Contract(Base):
    __tablename__ = "contracts"
    __table_args__ = (UniqueConstraint("institution_id", "raw_contract"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id", ondelete="CASCADE"))
    raw_contract: Mapped[str] = mapped_column(String(300), nullable=False)
    canonical_contract: Mapped[str | None] = mapped_column(String(300))

    institution: Mapped[Institution] = relationship(back_populates="contracts")


class Service(Base):
    """Raw SIHOS service strings mapped to a ServiceType."""
    __tablename__ = "services"
    __table_args__ = (UniqueConstraint("institution_id", "raw_service"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id", ondelete="CASCADE"))
    raw_service: Mapped[str] = mapped_column(String(300), nullable=False)
    service_type_id: Mapped[int | None] = mapped_column(ForeignKey("service_types.id"), nullable=True)

    institution: Mapped[Institution] = relationship(back_populates="services")


class ServiceTypeDocument(Base):
    """Links a service type to a required document type, scoped to an institution."""
    __tablename__ = "service_type_documents"
    __table_args__ = (UniqueConstraint("institution_id", "service_type_id", "doc_type_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id", ondelete="CASCADE"))
    service_type_id: Mapped[int] = mapped_column(ForeignKey("service_types.id"))
    doc_type_id: Mapped[int] = mapped_column(ForeignKey("doc_types.id"))

    institution: Mapped[Institution] = relationship(back_populates="service_type_documents")


# Deferred import to avoid circular reference at module load
from app.models.period import AuditPeriod  # noqa: E402
