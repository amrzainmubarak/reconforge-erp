"""Compatibility facade for the governed deterministic matching boundary."""

from __future__ import annotations

import sqlite3
from typing import cast

from reconforge.application.matching import (
    LEGACY_RECORD_IDENTITY_POLICY,
    DeterministicMatchOutput,
    MatchingApplicationService,
    MatchRunResult,
    ReferenceNormalizationRules,
)
from reconforge.infrastructure.sqlite_matching import (
    MATCHING_CANDIDATE_POLICY,
    MAX_CANDIDATES_PER_LEFT_RECORD,
    MAX_TOTAL_CANDIDATE_EVALUATIONS,
    SQLiteMatchingRepository,
)
from reconforge.infrastructure.sqlite_matching import (
    _AmountRangePartition as _SQLiteAmountRangePartition,
)
from reconforge.infrastructure.sqlite_matching import (
    _decimal_range_bounds as _sqlite_decimal_range_bounds,
)

_AmountRangePartition = _SQLiteAmountRangePartition
_decimal_range_bounds = _sqlite_decimal_range_bounds


class MatchingService(MatchingApplicationService):
    """Preserve the historical SQLite constructor while delegating via the port."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        super().__init__(SQLiteMatchingRepository(connection))

    @property
    def connection(self) -> sqlite3.Connection:
        """Retain the historical read-only test and integration seam."""

        repository = cast(SQLiteMatchingRepository, self.repository)
        return repository.connection


__all__ = [
    "LEGACY_RECORD_IDENTITY_POLICY",
    "MATCHING_CANDIDATE_POLICY",
    "MAX_CANDIDATES_PER_LEFT_RECORD",
    "MAX_TOTAL_CANDIDATE_EVALUATIONS",
    "DeterministicMatchOutput",
    "MatchRunResult",
    "MatchingService",
    "ReferenceNormalizationRules",
]
