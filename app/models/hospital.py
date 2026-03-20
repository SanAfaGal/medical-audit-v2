# backward compat shim
from app.models.institution import (  # noqa: F401
    Institution,
    Administrator,
    Contract,
    ContractType,
    Agreement,
    Service,
    ServiceTypeDocument,
)
