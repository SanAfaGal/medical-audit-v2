"""Path utilities: normalize Windows paths to Docker-accessible Linux paths.

Inside the Docker container, Windows drives are mounted at /mnt/<letter>:
  C:\\Users\\Maria\\Desktop  →  /mnt/c/Users/Maria/Desktop
  C:/Users/Maria/Desktop     →  /mnt/c/Users/Maria/Desktop

Paths that are already Linux-style (starting with /) are returned as-is.
"""
from __future__ import annotations

import re
from pathlib import Path


def to_container_path(path_str: str) -> Path:
    """Convert a user-supplied path (Windows or Linux) to a Path usable inside Docker."""
    if not path_str:
        return Path("/mnt/c")
    m = re.match(r"^([A-Za-z])[:/\\](.*)", path_str)
    if m:
        drive = m.group(1).lower()
        rest = m.group(2).replace("\\", "/").strip("/")
        return Path(f"/mnt/{drive}/{rest}") if rest else Path(f"/mnt/{drive}")
    return Path(path_str)
