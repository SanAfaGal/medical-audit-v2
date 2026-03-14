"""Path utilities: container mount point for audit data.

The host audit folder is mounted at /audit_data via docker-compose
using the AUDIT_HOST_PATH variable defined in .env.
"""
from pathlib import Path

AUDIT_DATA_MOUNT = Path("/audit_data")
