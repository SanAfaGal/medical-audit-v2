"""Path utilities: resolve audit data root to a filesystem path."""

from pathlib import Path

from app.config import settings


def to_container_path(path_str: str) -> Path:
    """Return the filesystem Path for the given string.

    Kept for backward-compatibility with call sites that still pass a string.
    Prefer using `audit_data_root` directly.
    """
    return Path(path_str)


# Convenience: resolved Path for the configured audit data root.
audit_data_root: Path = Path(settings.audit_data_root)
