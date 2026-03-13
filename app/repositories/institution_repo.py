"""Async repository for institutions, admins, contracts, services, and service-type-document mappings."""
from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.institution import Admin, Contract, Institution, Service, ServiceTypeDocument


class InstitutionRepo:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Institutions
    # ------------------------------------------------------------------

    async def get_all(self) -> list[Institution]:
        result = await self.db.execute(select(Institution).order_by(Institution.name))
        return list(result.scalars().all())

    async def get_by_id(self, institution_id: int) -> Institution | None:
        return await self.db.get(Institution, institution_id)

    async def get_by_name(self, name: str) -> Institution | None:
        result = await self.db.execute(select(Institution).where(Institution.name == name))
        return result.scalar_one_or_none()

    async def create(self, data: dict) -> Institution:
        institution = Institution(**data)
        self.db.add(institution)
        await self.db.flush()
        await self.db.refresh(institution)
        return institution

    async def update(self, institution_id: int, data: dict) -> Institution | None:
        institution = await self.db.get(Institution, institution_id)
        if not institution:
            return None
        for key, value in data.items():
            setattr(institution, key, value)
        await self.db.flush()
        return institution

    # ------------------------------------------------------------------
    # Admins
    # ------------------------------------------------------------------

    async def get_admins(self, institution_id: int) -> list[Admin]:
        result = await self.db.execute(
            select(Admin).where(Admin.institution_id == institution_id).order_by(Admin.raw_admin)
        )
        return list(result.scalars().all())

    async def get_pending_admins(self, institution_id: int) -> list[Admin]:
        """Return admins whose canonical_admin is NULL (not yet mapped by user)."""
        result = await self.db.execute(
            select(Admin)
            .where(Admin.institution_id == institution_id, Admin.canonical_admin.is_(None))
            .order_by(Admin.raw_admin)
        )
        return list(result.scalars().all())

    async def upsert_admin(self, institution_id: int, raw_admin: str) -> Admin:
        """Insert admin if not exists; return existing row if already present."""
        stmt = (
            pg_insert(Admin)
            .values(institution_id=institution_id, raw_admin=raw_admin)
            .on_conflict_do_nothing(index_elements=["institution_id", "raw_admin"])
            .returning(Admin)
        )
        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            result2 = await self.db.execute(
                select(Admin).where(
                    Admin.institution_id == institution_id, Admin.raw_admin == raw_admin
                )
            )
            row = result2.scalar_one()
        return row

    async def set_admin_canonical(
        self, admin_id: int, canonical: str | None, type_: str | None = None
    ) -> None:
        admin = await self.db.get(Admin, admin_id)
        if admin:
            admin.canonical_admin = canonical
            if type_ is not None:
                admin.type = type_
            await self.db.flush()

    # ------------------------------------------------------------------
    # Contracts
    # ------------------------------------------------------------------

    async def get_contracts(self, institution_id: int) -> list[Contract]:
        result = await self.db.execute(
            select(Contract)
            .where(Contract.institution_id == institution_id)
            .order_by(Contract.raw_contract)
        )
        return list(result.scalars().all())

    async def get_pending_contracts(self, institution_id: int) -> list[Contract]:
        """Return contracts with NULL canonical_contract for an institution."""
        result = await self.db.execute(
            select(Contract)
            .where(
                Contract.institution_id == institution_id,
                Contract.canonical_contract.is_(None),
            )
            .order_by(Contract.raw_contract)
        )
        return list(result.scalars().all())

    async def upsert_contract(self, institution_id: int, raw_contract: str) -> Contract:
        stmt = (
            pg_insert(Contract)
            .values(institution_id=institution_id, raw_contract=raw_contract)
            .on_conflict_do_nothing(index_elements=["institution_id", "raw_contract"])
            .returning(Contract)
        )
        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            result2 = await self.db.execute(
                select(Contract).where(
                    Contract.institution_id == institution_id,
                    Contract.raw_contract == raw_contract,
                )
            )
            row = result2.scalar_one()
        return row

    async def set_contract_canonical(self, contract_id: int, canonical: str | None) -> None:
        contract = await self.db.get(Contract, contract_id)
        if contract:
            contract.canonical_contract = canonical
            await self.db.flush()

    # ------------------------------------------------------------------
    # Services
    # ------------------------------------------------------------------

    async def get_services(self, institution_id: int) -> list[Service]:
        """Return all services for an institution (service_type_id is always set)."""
        result = await self.db.execute(
            select(Service)
            .where(Service.institution_id == institution_id)
            .order_by(Service.raw_service)
        )
        return list(result.scalars().all())

    async def upsert_service(
        self, institution_id: int, raw_service: str, service_type_id: int
    ) -> Service:
        stmt = (
            pg_insert(Service)
            .values(
                institution_id=institution_id,
                raw_service=raw_service,
                service_type_id=service_type_id,
            )
            .on_conflict_do_nothing(index_elements=["institution_id", "raw_service"])
            .returning(Service)
        )
        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            result2 = await self.db.execute(
                select(Service).where(
                    Service.institution_id == institution_id,
                    Service.raw_service == raw_service,
                )
            )
            row = result2.scalar_one()
        return row

    async def set_service_type(self, service_id: int, service_type_id: int) -> None:
        service = await self.db.get(Service, service_id)
        if service:
            service.service_type_id = service_type_id
            await self.db.flush()

    # ------------------------------------------------------------------
    # ServiceTypeDocuments
    # ------------------------------------------------------------------

    async def get_service_type_documents(self, institution_id: int) -> list[ServiceTypeDocument]:
        result = await self.db.execute(
            select(ServiceTypeDocument)
            .where(ServiceTypeDocument.institution_id == institution_id)
            .order_by(ServiceTypeDocument.service_type_id, ServiceTypeDocument.doc_type_id)
        )
        return list(result.scalars().all())

    async def upsert_service_type_document(
        self, institution_id: int, service_type_id: int, doc_type_id: int
    ) -> ServiceTypeDocument:
        stmt = (
            pg_insert(ServiceTypeDocument)
            .values(
                institution_id=institution_id,
                service_type_id=service_type_id,
                doc_type_id=doc_type_id,
            )
            .on_conflict_do_nothing(
                index_elements=["institution_id", "service_type_id", "doc_type_id"]
            )
            .returning(ServiceTypeDocument)
        )
        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            result2 = await self.db.execute(
                select(ServiceTypeDocument).where(
                    ServiceTypeDocument.institution_id == institution_id,
                    ServiceTypeDocument.service_type_id == service_type_id,
                    ServiceTypeDocument.doc_type_id == doc_type_id,
                )
            )
            row = result2.scalar_one()
        return row

    async def delete_service_type_document(
        self, institution_id: int, service_type_id: int, doc_type_id: int
    ) -> None:
        await self.db.execute(
            delete(ServiceTypeDocument).where(
                ServiceTypeDocument.institution_id == institution_id,
                ServiceTypeDocument.service_type_id == service_type_id,
                ServiceTypeDocument.doc_type_id == doc_type_id,
            )
        )
        await self.db.flush()

    # ------------------------------------------------------------------
    # Create / Delete helpers
    # ------------------------------------------------------------------

    async def create_admin(
        self, institution_id: int, raw_admin: str, canonical_admin: str | None, type_: str | None
    ) -> Admin:
        admin = Admin(
            institution_id=institution_id,
            raw_admin=raw_admin,
            canonical_admin=canonical_admin,
            type=type_,
        )
        self.db.add(admin)
        await self.db.flush()
        await self.db.refresh(admin)
        return admin

    async def delete_admin(self, admin_id: int) -> bool:
        admin = await self.db.get(Admin, admin_id)
        if not admin:
            return False
        await self.db.delete(admin)
        await self.db.flush()
        return True

    async def create_contract(
        self, institution_id: int, raw_contract: str, canonical_contract: str | None
    ) -> Contract:
        contract = Contract(
            institution_id=institution_id,
            raw_contract=raw_contract,
            canonical_contract=canonical_contract,
        )
        self.db.add(contract)
        await self.db.flush()
        await self.db.refresh(contract)
        return contract

    async def delete_contract(self, contract_id: int) -> bool:
        contract = await self.db.get(Contract, contract_id)
        if not contract:
            return False
        await self.db.delete(contract)
        await self.db.flush()
        return True

    async def create_service(
        self, institution_id: int, raw_service: str, service_type_id: int
    ) -> Service:
        service = Service(
            institution_id=institution_id,
            raw_service=raw_service,
            service_type_id=service_type_id,
        )
        self.db.add(service)
        await self.db.flush()
        await self.db.refresh(service)
        return service

    async def delete_service(self, service_id: int) -> bool:
        service = await self.db.get(Service, service_id)
        if not service:
            return False
        await self.db.delete(service)
        await self.db.flush()
        return True

    async def delete_institution(self, institution_id: int) -> bool:
        inst = await self.db.get(Institution, institution_id)
        if not inst:
            return False
        await self.db.delete(inst)
        await self.db.flush()
        return True
