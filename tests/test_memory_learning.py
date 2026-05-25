"""Approval → memory learning hook."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from app.db.models import ApprovalStatus, MemoryKind
from app.memory import learning, store


def _approval(status: ApprovalStatus, *, note: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        status=status,
        decided_by=uuid.uuid4(),
        domain="business",
        agent="lead_generation",
        action_class="action.external_send",
        action_name="send_outreach",
        target_summary="email to alice@example.com",
        decision_note=note,
        request_id="req-1",
    )


@pytest.mark.asyncio
async def test_approved_writes_procedural_memory(monkeypatch) -> None:
    writes: list[dict[str, Any]] = []

    async def fake_write(**kwargs):
        writes.append(kwargs)
        return SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setattr(store, "write", fake_write)
    await learning.write_from_approval(_approval(ApprovalStatus.approved))

    assert len(writes) == 1
    assert writes[0]["kind"] is MemoryKind.procedural
    assert writes[0]["domain"] == "business"
    assert "approved" in writes[0]["text"]
    assert "send_outreach" in writes[0]["text"]


@pytest.mark.asyncio
async def test_rejected_writes_semantic_memory(monkeypatch) -> None:
    writes: list[dict[str, Any]] = []

    async def fake_write(**kwargs):
        writes.append(kwargs)
        return SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setattr(store, "write", fake_write)
    await learning.write_from_approval(_approval(ApprovalStatus.rejected))

    assert len(writes) == 1
    assert writes[0]["kind"] is MemoryKind.semantic
    assert "rejected" in writes[0]["text"]


@pytest.mark.asyncio
async def test_rejected_with_note_writes_two_memories(monkeypatch) -> None:
    writes: list[dict[str, Any]] = []

    async def fake_write(**kwargs):
        writes.append(kwargs)
        return SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setattr(store, "write", fake_write)
    await learning.write_from_approval(
        _approval(ApprovalStatus.rejected, note="don't email leads on weekends")
    )

    assert len(writes) == 2
    second = writes[1]
    assert "user preference" in second["text"]
    assert "weekends" in second["text"]
    assert second["metadata"]["from_rejection"] is True


@pytest.mark.asyncio
async def test_swallows_topic_disabled_silently(monkeypatch, caplog) -> None:
    async def fake_write(**kwargs):
        raise store.TopicDisabledError("blocked")

    monkeypatch.setattr(store, "write", fake_write)
    # Must not raise.
    await learning.write_from_approval(_approval(ApprovalStatus.approved))


@pytest.mark.asyncio
async def test_swallows_unexpected_errors(monkeypatch) -> None:
    async def fake_write(**kwargs):
        raise RuntimeError("db is on fire")

    monkeypatch.setattr(store, "write", fake_write)
    # Best-effort hook: must never propagate.
    await learning.write_from_approval(_approval(ApprovalStatus.approved))


@pytest.mark.asyncio
async def test_no_memory_for_pending_or_expired(monkeypatch) -> None:
    writes: list[Any] = []

    async def fake_write(**kwargs):
        writes.append(kwargs)
        return SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setattr(store, "write", fake_write)
    await learning.write_from_approval(_approval(ApprovalStatus.pending))
    await learning.write_from_approval(_approval(ApprovalStatus.expired))
    await learning.write_from_approval(_approval(ApprovalStatus.executed))
    assert writes == []


# Date proves nothing here, but keeps the file self-describing.
_NOW = datetime.now(timezone.utc)
