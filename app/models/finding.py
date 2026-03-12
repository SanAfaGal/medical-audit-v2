"""ORM model for audit findings (missing documents)."""
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Finding(Base):
    __tablename__ = "findings"
    __table_args__ = (UniqueConstraint("invoice_id", "doc_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"))
    doc_code: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g. "FIRMA"
    comment: Mapped[str] = mapped_column(String(500), default="")

    invoice: Mapped[Invoice] = relationship(back_populates="findings")


from app.models.invoice import Invoice  # noqa: E402
