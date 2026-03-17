"""Async repository for institutions, administrators, contracts, contract_types, institution_contracts, services."""
from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.institution import (
    Administrator,
    Contract,
    ContractType,
    Institution,
    InstitutionContract,
    Service,
    ServiceTypeDocument,
)


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
    # Administrators (global)
    # ------------------------------------------------------------------

    async def get_all_administrators(self) -> list[Administrator]:
        result = await self.db.execute(select(Administrator).order_by(Administrator.raw_name))
        return list(result.scalars().all())

    async def get_pending_administrators(self) -> list[Administrator]:
        """Return administrators whose canonical_name is NULL (not yet mapped by user)."""
        result = await self.db.execute(
            select(Administrator)
            .where(Administrator.canonical_name.is_(None))
            .order_by(Administrator.raw_name)
        )
        return list(result.scalars().all())

    async def upsert_administrator(self, raw_name: str) -> Administrator:
        """Insert administrator globally if not exists; return existing row if present."""
        stmt = (
            pg_insert(Administrator)
            .values(raw_name=raw_name)
            .on_conflict_do_nothing(index_elements=["raw_name"])
            .returning(Administrator)
        )
        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            result2 = await self.db.execute(
                select(Administrator).where(Administrator.raw_name == raw_name)
            )
            row = result2.scalar_one()
        return row

    async def set_administrator_canonical(self, administrator_id: int, canonical_name: str | None) -> None:
        admin = await self.db.get(Administrator, administrator_id)
        if admin:
            admin.canonical_name = canonical_name
            await self.db.flush()

    async def create_administrator(self, raw_name: str, canonical_name: str | None) -> Administrator:
        admin = Administrator(raw_name=raw_name, canonical_name=canonical_name)
        self.db.add(admin)
        await self.db.flush()
        await self.db.refresh(admin)
        return admin

    async def delete_administrator(self, administrator_id: int) -> bool:
        admin = await self.db.get(Administrator, administrator_id)
        if not admin:
            return False
        await self.db.delete(admin)
        await self.db.flush()
        return True

    # ------------------------------------------------------------------
    # Contracts (global)
    # ------------------------------------------------------------------

    async def get_all_contracts(self) -> list[Contract]:
        result = await self.db.execute(select(Contract).order_by(Contract.raw_name))
        return list(result.scalars().all())

    async def get_pending_contracts(self) -> list[Contract]:
        """Return contracts with NULL canonical_name."""
        result = await self.db.execute(
            select(Contract)
            .where(Contract.canonical_name.is_(None))
            .order_by(Contract.raw_name)
        )
        return list(result.scalars().all())

    async def upsert_contract(self, raw_name: str) -> Contract:
        stmt = (
            pg_insert(Contract)
            .values(raw_name=raw_name)
            .on_conflict_do_nothing(index_elements=["raw_name"])
            .returning(Contract)
        )
        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            result2 = await self.db.execute(
                select(Contract).where(Contract.raw_name == raw_name)
            )
            row = result2.scalar_one()
        return row

    async def set_contract_canonical(self, contract_id: int, canonical_name: str | None) -> None:
        contract = await self.db.get(Contract, contract_id)
        if contract:
            contract.canonical_name = canonical_name
            await self.db.flush()

    async def create_contract(self, raw_name: str, canonical_name: str | None) -> Contract:
        contract = Contract(raw_name=raw_name, canonical_name=canonical_name)
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

    # ------------------------------------------------------------------
    # ContractTypes (global)
    # ------------------------------------------------------------------

    async def get_all_contract_types(self) -> list[ContractType]:
        result = await self.db.execute(select(ContractType).order_by(ContractType.name))
        return list(result.scalars().all())

    async def get_contract_type_by_id(self, ct_id: int) -> ContractType | None:
        return await self.db.get(ContractType, ct_id)

    async def create_contract_type(self, name: str, description: str | None) -> ContractType:
        ct = ContractType(name=name, description=description)
        self.db.add(ct)
        await self.db.flush()
        await self.db.refresh(ct)
        return ct

    async def update_contract_type(self, ct_id: int, name: str | None, description: str | None) -> ContractType | None:
        ct = await self.db.get(ContractType, ct_id)
        if not ct:
            return None
        if name is not None:
            ct.name = name
        if description is not None:
            ct.description = description
        await self.db.flush()
        return ct

    async def delete_contract_type(self, ct_id: int) -> bool:
        ct = await self.db.get(ContractType, ct_id)
        if not ct:
            return False
        await self.db.delete(ct)
        await self.db.flush()
        return True

    # ------------------------------------------------------------------
    # InstitutionContracts
    # ------------------------------------------------------------------

    async def get_institution_contracts(self, institution_id: int) -> list[InstitutionContract]:
        result = await self.db.execute(
            select(InstitutionContract)
            .where(InstitutionContract.institution_id == institution_id)
            .options(
                selectinload(InstitutionContract.administrator),
                selectinload(InstitutionContract.contract),
                selectinload(InstitutionContract.contract_type),
            )
        )
        return list(result.scalars().all())

    async def get_pending_institution_contracts(self, institution_id: int) -> list[InstitutionContract]:
        """Return institution_contracts where contract_type_id is NULL."""
        result = await self.db.execute(
            select(InstitutionContract)
            .where(
                InstitutionContract.institution_id == institution_id,
                InstitutionContract.contract_type_id.is_(None),
            )
            .options(
                selectinload(InstitutionContract.administrator),
                selectinload(InstitutionContract.contract),
            )
        )
        return list(result.scalars().all())

    async def upsert_institution_contract(
        self,
        institution_id: int,
        administrator_id: int,
        contract_id: int,
        contract_type_id: int | None = None,
    ) -> InstitutionContract:
        stmt = (
            pg_insert(InstitutionContract)
            .values(
                institution_id=institution_id,
                administrator_id=administrator_id,
                contract_id=contract_id,
                contract_type_id=contract_type_id,
            )
            .on_conflict_do_nothing(
                index_elements=["institution_id", "administrator_id", "contract_id"]
            )
            .returning(InstitutionContract)
        )
        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            result2 = await self.db.execute(
                select(InstitutionContract).where(
                    InstitutionContract.institution_id == institution_id,
                    InstitutionContract.administrator_id == administrator_id,
                    InstitutionContract.contract_id == contract_id,
                )
            )
            row = result2.scalar_one()
        return row

    async def set_contract_type(self, institution_contract_id: int, contract_type_id: int | None) -> None:
        ic = await self.db.get(InstitutionContract, institution_contract_id)
        if ic:
            ic.contract_type_id = contract_type_id
            await self.db.flush()

    async def create_institution_contract(
        self,
        institution_id: int,
        administrator_id: int,
        contract_id: int,
        contract_type_id: int | None = None,
    ) -> InstitutionContract:
        ic = InstitutionContract(
            institution_id=institution_id,
            administrator_id=administrator_id,
            contract_id=contract_id,
            contract_type_id=contract_type_id,
        )
        self.db.add(ic)
        await self.db.flush()
        await self.db.refresh(ic)
        return ic

    async def delete_institution_contract(self, institution_contract_id: int) -> bool:
        ic = await self.db.get(InstitutionContract, institution_contract_id)
        if not ic:
            return False
        await self.db.delete(ic)
        await self.db.flush()
        return True

    # ------------------------------------------------------------------
    # Services
    # ------------------------------------------------------------------

    async def get_services(self, institution_id: int) -> list[Service]:
        result = await self.db.execute(
            select(Service)
            .where(Service.institution_id == institution_id)
            .order_by(Service.raw_service)
        )
        return list(result.scalars().all())

    async def get_pending_services(self, institution_id: int) -> list[Service]:
        result = await self.db.execute(
            select(Service)
            .where(Service.institution_id == institution_id, Service.service_type_id.is_(None))
            .order_by(Service.raw_service)
        )
        return list(result.scalars().all())

    async def upsert_service(self, institution_id: int, raw_service: str) -> Service:
        stmt = (
            pg_insert(Service)
            .values(institution_id=institution_id, raw_service=raw_service, service_type_id=None)
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

    async def create_service(
        self, institution_id: int, raw_service: str, service_type_id: int | None = None
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
