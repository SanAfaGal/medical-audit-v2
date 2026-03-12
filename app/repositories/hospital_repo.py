"""Async repository for hospitals, admins, contracts, and service mappings."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.hospital import Admin, Contract, Hospital, Service


class HospitalRepo:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Hospitals
    # ------------------------------------------------------------------

    async def get_all(self) -> list[Hospital]:
        result = await self.db.execute(select(Hospital).order_by(Hospital.name))
        return list(result.scalars().all())

    async def get_by_key(self, key: str) -> Hospital | None:
        result = await self.db.execute(select(Hospital).where(Hospital.key == key))
        return result.scalar_one_or_none()

    async def get_by_id(self, hospital_id: int) -> Hospital | None:
        return await self.db.get(Hospital, hospital_id)

    async def create(self, data: dict) -> Hospital:
        hospital = Hospital(**data)
        self.db.add(hospital)
        await self.db.flush()
        await self.db.refresh(hospital)
        return hospital

    async def update(self, hospital_id: int, data: dict) -> Hospital | None:
        hospital = await self.db.get(Hospital, hospital_id)
        if not hospital:
            return None
        for key, value in data.items():
            setattr(hospital, key, value)
        await self.db.flush()
        return hospital

    # ------------------------------------------------------------------
    # Admins
    # ------------------------------------------------------------------

    async def get_admins(self, hospital_id: int) -> list[Admin]:
        result = await self.db.execute(
            select(Admin).where(Admin.hospital_id == hospital_id).order_by(Admin.raw_value)
        )
        return list(result.scalars().all())

    async def get_pending_admins(self, hospital_id: int) -> list[Admin]:
        """Return admins whose canonical_value is NULL (not yet mapped by user)."""
        result = await self.db.execute(
            select(Admin)
            .where(Admin.hospital_id == hospital_id, Admin.canonical_value.is_(None))
            .order_by(Admin.raw_value)
        )
        return list(result.scalars().all())

    async def upsert_admin(self, hospital_id: int, raw_value: str) -> Admin:
        """Insert admin if not exists; return existing row if already present."""
        stmt = (
            pg_insert(Admin)
            .values(hospital_id=hospital_id, raw_value=raw_value)
            .on_conflict_do_nothing(index_elements=["hospital_id", "raw_value"])
            .returning(Admin)
        )
        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            # Already existed — fetch it
            result2 = await self.db.execute(
                select(Admin).where(Admin.hospital_id == hospital_id, Admin.raw_value == raw_value)
            )
            row = result2.scalar_one()
        return row

    async def set_admin_canonical(self, admin_id: int, canonical: str | None) -> None:
        admin = await self.db.get(Admin, admin_id)
        if admin:
            admin.canonical_value = canonical
            await self.db.flush()

    # ------------------------------------------------------------------
    # Contracts
    # ------------------------------------------------------------------

    async def get_contracts(self, admin_id: int) -> list[Contract]:
        result = await self.db.execute(
            select(Contract).where(Contract.admin_id == admin_id).order_by(Contract.raw_value)
        )
        return list(result.scalars().all())

    async def get_pending_contracts(self, hospital_id: int) -> list[Contract]:
        """Return contracts with NULL canonical_value for a hospital (via admin join)."""
        result = await self.db.execute(
            select(Contract)
            .join(Admin, Contract.admin_id == Admin.id)
            .where(Admin.hospital_id == hospital_id, Contract.canonical_value.is_(None))
            .order_by(Admin.raw_value, Contract.raw_value)
        )
        return list(result.scalars().all())

    async def upsert_contract(self, admin_id: int, raw_value: str) -> Contract:
        stmt = (
            pg_insert(Contract)
            .values(admin_id=admin_id, raw_value=raw_value)
            .on_conflict_do_nothing(index_elements=["admin_id", "raw_value"])
            .returning(Contract)
        )
        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            result2 = await self.db.execute(
                select(Contract).where(Contract.admin_id == admin_id, Contract.raw_value == raw_value)
            )
            row = result2.scalar_one()
        return row

    async def set_contract_canonical(self, contract_id: int, canonical: str | None) -> None:
        contract = await self.db.get(Contract, contract_id)
        if contract:
            contract.canonical_value = canonical
            await self.db.flush()

    # ------------------------------------------------------------------
    # Services (raw SIHOS service string → service_type)
    # ------------------------------------------------------------------

    async def get_service(self, hospital_id: int, raw_value: str) -> Service | None:
        result = await self.db.execute(
            select(Service).where(Service.hospital_id == hospital_id, Service.raw_value == raw_value)
        )
        return result.scalar_one_or_none()

    async def upsert_service(self, hospital_id: int, raw_value: str) -> Service:
        stmt = (
            pg_insert(Service)
            .values(hospital_id=hospital_id, raw_value=raw_value)
            .on_conflict_do_nothing(index_elements=["hospital_id", "raw_value"])
            .returning(Service)
        )
        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            result2 = await self.db.execute(
                select(Service).where(
                    Service.hospital_id == hospital_id, Service.raw_value == raw_value
                )
            )
            row = result2.scalar_one()
        return row

    async def get_pending_services(self, hospital_id: int) -> list[Service]:
        """Return services with no service_type assigned."""
        result = await self.db.execute(
            select(Service)
            .where(Service.hospital_id == hospital_id, Service.service_type_id.is_(None))
            .order_by(Service.raw_value)
        )
        return list(result.scalars().all())

    async def set_service_type(self, service_id: int, service_type_id: int | None) -> None:
        service = await self.db.get(Service, service_id)
        if service:
            service.service_type_id = service_type_id
            await self.db.flush()
