"""ORM model for invoices (facturas)."""
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (UniqueConstraint("period_id", "factura"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("audit_periods.id", ondelete="CASCADE"))
    factura: Mapped[str] = mapped_column(String(50), nullable=False)
    fecha: Mapped[str | None] = mapped_column(String(20))
    documento: Mapped[str | None] = mapped_column(String(50))
    numero: Mapped[str | None] = mapped_column(String(50))
    paciente: Mapped[str | None] = mapped_column(String(300))
    administradora: Mapped[str | None] = mapped_column(String(200))
    contrato: Mapped[str | None] = mapped_column(String(200))
    operario: Mapped[str | None] = mapped_column(String(200))
    ruta: Mapped[str | None] = mapped_column(String(500))
    folder_status: Mapped[str] = mapped_column(String(20), default="PRESENTE")
    nota: Mapped[str] = mapped_column(Text, default="")
    service_type_id: Mapped[int | None] = mapped_column(ForeignKey("service_types.id"))

    period: Mapped[AuditPeriod] = relationship(back_populates="invoices")
    findings: Mapped[list[Finding]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )
    service_type: Mapped[ServiceType | None] = relationship()


from app.models.period import AuditPeriod   # noqa: E402
from app.models.finding import Finding      # noqa: E402
from app.models.rules import ServiceType    # noqa: E402
