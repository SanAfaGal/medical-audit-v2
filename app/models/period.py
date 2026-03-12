"""ORM model for audit periods."""
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class AuditPeriod(Base):
    __tablename__ = "audit_periods"
    __table_args__ = (UniqueConstraint("hospital_id", "code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hospital_id: Mapped[int] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(20), nullable=False)  # e.g. "22-28"

    hospital: Mapped[Hospital] = relationship(back_populates="periods")
    invoices: Mapped[list[Invoice]] = relationship(
        back_populates="period", cascade="all, delete-orphan"
    )


from app.models.hospital import Hospital  # noqa: E402
from app.models.invoice import Invoice    # noqa: E402
