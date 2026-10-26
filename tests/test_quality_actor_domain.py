"""NCR review authority requires known, distinct stable identities."""

import pytest

from reconforge.domain.manufacturing_quality_rework import (
    QualityReworkError,
    require_independent_quality_actor,
)


@pytest.mark.parametrize("creator,reviewer,code", [
    (None, "reviewer-id", "quality_actor_authority_missing"),
    ("stable-owner", "stable-owner", "quality_self_disposition_denied"),
])
def test_quality_review_refuses_unknown_or_self_identity(creator: str | None, reviewer: str, code: str) -> None:
    with pytest.raises(QualityReworkError) as failure:
        require_independent_quality_actor(creator, reviewer)
    assert failure.value.code == code


def test_independent_stable_identity_is_allowed_without_using_display_aliases() -> None:
    require_independent_quality_actor("original-owner-id", "different-owner-id")
