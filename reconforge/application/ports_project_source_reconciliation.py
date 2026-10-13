"""Existing published source pair is queried; there is no write port."""

from typing import Any, Protocol

from reconforge.domain.finance_posting import PostingActor
from reconforge.domain.project_source_reconciliation import ProjectSourceSelection


class ProjectSourceReconciliationRepository(Protocol):
    def report(self, selection: ProjectSourceSelection, *, actor: PostingActor) -> dict[str, Any]: ...
