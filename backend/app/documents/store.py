import hashlib
import os
from pathlib import Path
import uuid


def original_path(root: Path, sha256: str) -> Path:
    return root / "originals" / sha256[:2] / sha256


def crop_path(root: Path, run_id: uuid.UUID, field_path: str) -> Path:
    return root / "crops" / str(run_id) / f"{field_path}.png"


def save_original(root: Path, data: bytes) -> str:
    """Write once by content hash. A leftover file from a failed upload is harmless: same bytes, same name."""
    sha256 = hashlib.sha256(data).hexdigest()
    path = original_path(root, sha256)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(".partial")
        partial.write_bytes(data)
        os.replace(partial, path)  # atomic on the same filesystem
    return sha256
