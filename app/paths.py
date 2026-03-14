"""Path utilities: resolve audit data root to a filesystem path."""
from pathlib import Path


def to_container_path(path_str: str) -> Path:
    """Return the filesystem Path for the given audit data root.

    The backend runs natively on the host, so Windows paths are used as-is.
    Raises ValueError if path_str is empty (audit_data_root not configured).
    """
    if not path_str:
        raise ValueError("audit_data_root no está configurado")
    return Path(path_str)
