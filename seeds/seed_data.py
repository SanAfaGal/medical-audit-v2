"""Run: python seeds/seed_data.py — Populates default service types, doc types, and folder statuses."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.rules import DocType, FolderStatus, ServiceType

DEFAULT_SERVICE_TYPES = [
    {"code": "GENERAL",     "display_name": "General",            "priority": 0},
    {"code": "SOAT",        "display_name": "SOAT",               "priority": 10},
    {"code": "LABORATORIO", "display_name": "Laboratorio",        "priority": 20},
    {"code": "ECG",         "display_name": "Electrocardiograma", "priority": 20},
    {"code": "RADIOGRAFIA", "display_name": "Radiografía",        "priority": 20},
    {"code": "ODONTOLOGIA", "display_name": "Odontología",        "priority": 20},
    {"code": "POLICLINICA", "display_name": "Policlínica",        "priority": 20},
    {"code": "URGENCIAS",   "display_name": "Urgencias",          "priority": 20},
    {"code": "AMBULANCIA",  "display_name": "Ambulancia",         "priority": 30},
]

DEFAULT_DOC_TYPES = [
    {"code": "FACTURA",      "description": "Factura",           "prefix": "FEV"},
    {"code": "FIRMA",        "description": "Firma",             "prefix": "CRC"},
    {"code": "HISTORIA",     "description": "Historia clínica",  "prefix": "EPI"},
    {"code": "VALIDACION",   "description": "Validación",        "prefix": "OPF"},
    {"code": "RESULTADOS",   "description": "Resultados",        "prefix": "PDX"},
    {"code": "BITACORA",     "description": "Bitácora",          "prefix": "TAP"},
    {"code": "RESOLUCION",   "description": "Resolución",        "prefix": "LDP"},
    {"code": "MEDICAMENTOS", "description": "Medicamentos",      "prefix": "HAM"},
    {"code": "AUTORIZACION", "description": "Autorización",      "prefix": "PDE"},
    {"code": "CARPETA",      "description": "Carpeta",           "prefix": None},
    {"code": "ORDEN",        "description": "Orden médica",      "prefix": None},
    {"code": "FURIPS",       "description": "FURIPS",            "prefix": None},
    {"code": "CUFE",         "description": "CUFE",              "prefix": None},
]

DEFAULT_FOLDER_STATUSES = [
    {"status": "PRESENTE"},
    {"status": "PENDIENTE"},
    {"status": "FALTANTE"},
    {"status": "AUDITADA"},
    {"status": "ANULAR"},
    {"status": "REVISAR"},
]


async def seed() -> None:
    async with AsyncSessionLocal() as db:
        # Service types
        existing = (await db.execute(select(ServiceType))).scalars().first()
        if existing is None:
            for st in DEFAULT_SERVICE_TYPES:
                db.add(ServiceType(**st))
            print(f"Seeded {len(DEFAULT_SERVICE_TYPES)} service types.")
        else:
            print("Service types already seeded — skipped.")

        # Doc types
        existing = (await db.execute(select(DocType))).scalars().first()
        if existing is None:
            for dt in DEFAULT_DOC_TYPES:
                db.add(DocType(**dt))
            print(f"Seeded {len(DEFAULT_DOC_TYPES)} doc types.")
        else:
            print("Doc types already seeded — skipped.")

        # Folder statuses
        existing = (await db.execute(select(FolderStatus))).scalars().first()
        if existing is None:
            for fs in DEFAULT_FOLDER_STATUSES:
                db.add(FolderStatus(**fs))
            print(f"Seeded {len(DEFAULT_FOLDER_STATUSES)} folder statuses.")
        else:
            print("Folder statuses already seeded — skipped.")

        await db.commit()
        print("Seed complete.")


if __name__ == "__main__":
    asyncio.run(seed())
