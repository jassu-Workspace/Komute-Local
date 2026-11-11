"""Path-safe name helper."""
from __future__ import annotations

import re


def sanitize_folder_name(name: str) -> str:
    """Sanitize string to strictly prevent directory traversal, separators, or invalid characters."""
    if not name:
        return "unknown"
    clean = re.sub(r"[\/\\]+", "_", str(name).strip())
    clean = re.sub(r"\.{2,}", "_", clean)
    clean = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", clean)
    clean = clean.strip("._")
    if clean in ("", ".", "..", "unknown"):
        return "unknown"
    return clean[:64]
