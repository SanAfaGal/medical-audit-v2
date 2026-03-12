"""Run: python seeds/seed_data.py — Populates default service types, doc types, and folder statuses."""
import asyncio
import json
import sys
import os

# Ensure app is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.rules import DocType, FolderStatusDef, ServiceType

DEFAULT_SERVICE_TYPES = [
    {"code": "GENERAL",     "display_name": "General",            "keywords": "[]",                          "required_docs": "[]",                                                                                       "sort_order": 0},
    {"code": "SOAT",        "display_name": "SOAT",               "keywords": '["soat"]',                    "required_docs": "[]",                                                                                       "sort_order": 10},
    {"code": "LABORATORIO", "display_name": "Laboratorio",        "keywords": '["laboratorio clinico"]',     "required_docs": '["FACTURA","RESULTADOS","FIRMA","VALIDACION"]',                                             "sort_order": 20},
    {"code": "ECG",         "display_name": "Electrocardiograma", "keywords": '["electrocard"]',             "required_docs": '["FACTURA","RESULTADOS","FIRMA","VALIDACION"]',                                             "sort_order": 20},
    {"code": "RADIOGRAFIA", "display_name": "Radiografia",        "keywords": '["radiograf"]',               "required_docs": '["FACTURA","RESULTADOS","FIRMA","VALIDACION"]',                                             "sort_order": 20},
    {"code": "ODONTOLOGIA", "display_name": "Odontologia",        "keywords": '["odontolog"]',               "required_docs": '["FACTURA","HISTORIA","FIRMA","VALIDACION"]',                                               "sort_order": 20},
    {"code": "POLICLINICA", "display_name": "Policlinica",        "keywords": '["p909000"]',                 "required_docs": "[]",                                                                                       "sort_order": 20},
    {"code": "URGENCIAS",   "display_name": "Urgencias",          "keywords": '["urgencia"]',                "required_docs": '["FACTURA","HISTORIA","FIRMA","AUTORIZACION"]',                                             "sort_order": 20},
    {"code": "AMBULANCIA",  "display_name": "Ambulancia",         "keywords": '["ambulancia"]',              "required_docs": '["FACTURA","HISTORIA","FIRMA","AUTORIZACION","BITACORA","RESOLUCION"]',                    "sort_order": 30},
]

DEFAULT_DOC_TYPES = [
    {"code": "FACTURA",      "label": "Factura",          "prefixes": '["FEV"]'},
    {"code": "FIRMA",        "label": "Firma",            "prefixes": '["CRC"]'},
    {"code": "HISTORIA",     "label": "Historia clinica", "prefixes": '["EPI","HEV","HAO","HAU"]'},
    {"code": "VALIDACION",   "label": "Validacion",       "prefixes": '["OPF"]'},
    {"code": "RESULTADOS",   "label": "Resultados",       "prefixes": '["PDX"]'},
    {"code": "BITACORA",     "label": "Bitacora",         "prefixes": '["TAP"]'},
    {"code": "RESOLUCION",   "label": "Resolucion",       "prefixes": '["LDP"]'},
    {"code": "MEDICAMENTOS", "label": "Medicamentos",     "prefixes": '["HAM"]'},
    {"code": "AUTORIZACION", "label": "Autorizacion",     "prefixes": '["PDE"]'},
    {"code": "CARPETA",      "label": "Carpeta",          "prefixes": "[]"},
    {"code": "ORDEN",        "label": "Orden medica",     "prefixes": "[]"},
    {"code": "FURIPS",       "label": "FURIPS",           "prefixes": "[]"},
    {"code": "CUFE",         "label": "CUFE",             "prefixes": "[]"},
]

DEFAULT_FOLDER_STATUSES = [
    {"code": "PRESENTE",  "label": "Presente",  "sort_order": 0},
    {"code": "PENDIENTE", "label": "Pendiente", "sort_order": 1},
    {"code": "FALTANTE",  "label": "Faltante",  "sort_order": 2},
    {"code": "AUDITADA",  "label": "Auditada",  "sort_order": 3},
]


async def seed() -> None:
    async with AsyncSessionLocal() as db:
        # Service types
        count = (await db.execute(select(ServiceType))).scalars().first()
        if count is None:
            for st in DEFAULT_SERVICE_TYPES:
                db.add(ServiceType(**st, is_active=True))
            print(f"Seeded {len(DEFAULT_SERVICE_TYPES)} service types.")
        else:
            print("Service types already seeded — skipped.")

        # Doc types
        count = (await db.execute(select(DocType))).scalars().first()
        if count is None:
            for dt in DEFAULT_DOC_TYPES:
                db.add(DocType(**dt, is_active=True))
            print(f"Seeded {len(DEFAULT_DOC_TYPES)} doc types.")
        else:
            print("Doc types already seeded — skipped.")

        # Folder statuses
        count = (await db.execute(select(FolderStatusDef))).scalars().first()
        if count is None:
            for fs in DEFAULT_FOLDER_STATUSES:
                db.add(FolderStatusDef(**fs))
            print(f"Seeded {len(DEFAULT_FOLDER_STATUSES)} folder statuses.")
        else:
            print("Folder statuses already seeded — skipped.")

        await db.commit()
        print("Seed complete.")


if __name__ == "__main__":
    asyncio.run(seed())
