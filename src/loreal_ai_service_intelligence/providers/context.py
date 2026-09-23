from __future__ import annotations

from typing import Protocol

from loreal_ai_service_intelligence.domain.competition import P0ContextSnapshot


class ContextDataProvider(Protocol):
    """Read-only boundary for chat, product, order, ticket, and knowledge snapshots."""

    def load_context(
        self, conversation_id: str, cutoff_message_seq: int | None = None
    ) -> P0ContextSnapshot | None: ...


class UnconfiguredContextDataProvider:
    """Explicit placeholder used until official data adapters are supplied."""

    def load_context(
        self, conversation_id: str, cutoff_message_seq: int | None = None
    ) -> P0ContextSnapshot | None:
        del conversation_id, cutoff_message_seq
        raise RuntimeError("context data provider is not configured")


class InMemoryContextDataProvider:
    """Deterministic provider for Mock integration and acceptance tests."""

    def __init__(self, snapshots: list[P0ContextSnapshot] | None = None) -> None:
        self._snapshots = {item.conversation_id: item for item in snapshots or []}

    def put(self, snapshot: P0ContextSnapshot) -> None:
        self._snapshots[snapshot.conversation_id] = snapshot.model_copy(deep=True)

    def load_context(
        self, conversation_id: str, cutoff_message_seq: int | None = None
    ) -> P0ContextSnapshot | None:
        snapshot = self._snapshots.get(conversation_id)
        if snapshot is None:
            return None
        if cutoff_message_seq is not None and snapshot.cutoff_message_seq != cutoff_message_seq:
            return None
        return snapshot.model_copy(deep=True)
