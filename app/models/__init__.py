"""Import all ORM models so Alembic autogenerate can detect them."""
from app.models.base import Base  # noqa: F401
from app.models.rules import ServiceType, DocType, FolderStatusDef  # noqa: F401
from app.models.hospital import Hospital, Admin, Contract, Service  # noqa: F401
from app.models.period import AuditPeriod  # noqa: F401
from app.models.invoice import Invoice  # noqa: F401
from app.models.finding import Finding  # noqa: F401
