"""Session artifact export helpers."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from amble.storage.store import DataStore


def export_session(store: DataStore, session_id: str, destination: str | Path) -> Path:
    """Copy one complete session artifact tree to a new export directory."""
    session = store.session(session_id)
    if not session:
        raise KeyError(session_id)
    target = Path(destination) / session_id
    if target.exists():
        target = Path(destination) / f"{session_id}_export"
    shutil.copytree(session["session_dir"], target)
    return target


__all__ = ["export_session"]
