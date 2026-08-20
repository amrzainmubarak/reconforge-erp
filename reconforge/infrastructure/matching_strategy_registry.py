"""Provider-neutral registry for the reviewed matching strategy adapters.

The application contract owns the registry semantics while this infrastructure
factory wires the concrete adapters. Keeping the wiring in one place prevents
callers from silently omitting a strategy family or selecting an unreviewed
implementation by string convention.
"""

from __future__ import annotations

from reconforge.application.matching_strategies import MatchingStrategyRegistry
from reconforge.infrastructure.carry_forward_strategy import CarryForwardFifoStrategy
from reconforge.infrastructure.duplicate_detection_strategy import DuplicateDetectionStrategy
from reconforge.infrastructure.grouped_matching_strategy import GroupedSubsetSumStrategy
from reconforge.infrastructure.indexed_matching_strategy import IndexedOneToOneStrategy
from reconforge.infrastructure.reversal_matching_strategy import ReversalPairingStrategy
from reconforge.platform.matching import MatchingService


def build_matching_strategy_registry(service: MatchingService) -> MatchingStrategyRegistry:
    """Build the complete reviewed strategy registry for one execution.

    ``MatchingService`` is required because the indexed one-to-one adapter
    deliberately depends on the caller's transaction boundary. The other
    adapters are pure and remain bound to the same immutable registry, so a
    request can never fall through to an implicit implementation.
    """

    return MatchingStrategyRegistry(
        (
            IndexedOneToOneStrategy(service),
            GroupedSubsetSumStrategy(),
            DuplicateDetectionStrategy(),
            CarryForwardFifoStrategy(),
            ReversalPairingStrategy(),
        )
    )
