"""Compatibility facade for the backend-neutral evidence registry."""

from __future__ import annotations

import sqlite3

from reconforge.application.evidence import (
    LOCAL_STORAGE_BACKEND,
    OBJECT_STORAGE_BACKEND,
    EvidenceObjectStore,
    EvidenceRegistryApplicationService,
    EvidenceVerification,
)
from reconforge.infrastructure.sqlite_evidence import SQLiteEvidenceRegistryRepository


class EvidenceRegistryService(EvidenceRegistryApplicationService):
    """Preserve the historical connection-based constructor."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        super().__init__(SQLiteEvidenceRegistryRepository(connection))


__all__ = [
    "LOCAL_STORAGE_BACKEND",
    "OBJECT_STORAGE_BACKEND",
    "EvidenceObjectStore",
    "EvidenceRegistryService",
    "EvidenceVerification",
]
