"""Backend-neutral orchestration for approved policy conflict analysis."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from reconforge.auth.policy_analysis import PolicyAnalysisRequest, PolicyAnalysisResult, analyze_policy_conflicts


class PolicyAnalysisRepository(Protocol):
    """Load an immutable, tenant-bound policy snapshot for analysis."""

    def load_request(
        self,
        *,
        policy_id: str,
        policy_version: str,
        require_scoped_privileged: bool,
        prepared_by: str,
        prepared_at: datetime,
        approved_by: str,
        approved_at: str,
    ) -> PolicyAnalysisRequest: ...


class PolicyAnalysisApplicationService:
    """Analyze a repository snapshot without mutating authorization state."""

    def __init__(self, repository: PolicyAnalysisRepository) -> None:
        self.repository = repository

    def analyze(
        self,
        *,
        policy_id: str,
        policy_version: str,
        require_scoped_privileged: bool,
        prepared_by: str,
        prepared_at: datetime,
        approved_by: str,
        approved_at: str,
    ) -> PolicyAnalysisResult:
        request = self.repository.load_request(
            policy_id=policy_id,
            policy_version=policy_version,
            require_scoped_privileged=require_scoped_privileged,
            prepared_by=prepared_by,
            prepared_at=prepared_at,
            approved_by=approved_by,
            approved_at=approved_at,
        )
        return analyze_policy_conflicts(request)


__all__ = ["PolicyAnalysisApplicationService", "PolicyAnalysisRepository"]
