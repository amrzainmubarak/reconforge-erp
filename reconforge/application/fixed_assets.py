"""Fixed asset commands compose the existing native finance transaction owner."""

from typing import Any, Protocol

from reconforge.domain.finance_posting import PostingActor
from reconforge.domain.fixed_assets import AssetAcquisition


class FixedAssetsRepositoryProtocol(Protocol):
    def acquire(self, request: AssetAcquisition, *, command_id: str, actor: PostingActor) -> dict[str, Any]: ...
    def prepare(self, asset_id: str, *, kind: str, period_id: str, posting_date: str, reason: str,
                command_id: str, actor: PostingActor, through_month: str = "", proceeds_minor: int = 0) -> dict[str, Any]: ...
    def review(self, plan_id: str, *, expected_plan_digest: str, command_id: str, reason: str,
               actor: PostingActor) -> dict[str, Any]: ...
    def post(self, plan_id: str, *, expected_plan_digest: str, command_id: str, reason: str,
             actor: PostingActor) -> dict[str, Any]: ...
    def get(self, asset_id: str, *, actor: PostingActor) -> dict[str, Any]: ...
