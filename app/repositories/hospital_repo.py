# backward compat shim — use InstitutionRepo directly in new code
from app.repositories.institution_repo import InstitutionRepo as HospitalRepo  # noqa: F401
