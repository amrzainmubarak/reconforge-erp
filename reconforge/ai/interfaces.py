"""Interfaces for future AI explanation providers."""

from __future__ import annotations

from typing import Protocol


class ExceptionExplainer(Protocol):
    """Protocol for exception explanation providers."""

    def explain(self, exception: dict[str, object]) -> str:
        """Explain an exception."""
