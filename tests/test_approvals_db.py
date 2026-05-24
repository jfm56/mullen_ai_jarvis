"""End-to-end approval lifecycle against a real Postgres.

Marked `requires_db` — runs only when JARVIS_TEST_DB_URL is set.
The DB should have the alembic migration applied and pgvector enabled.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.requires_db


@pytest.mark.asyncio
async def test_proposal_require_approval_creates_pending_row(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", os.environ["JARVIS_TEST_DB_URL"])

    # Lazy imports so collection works even when settings can't load a DB URL.
    import uuid

    from app.agents.base import AgentContext, BaseAgent
    from app.security import approvals as approvals_svc
    from app.security.permissions import ActionClass, Decision, PermissionLevel

    class _StubAgent(BaseAgent):
        name = "stub"
        domains = ("personal",)
        default_permission_level = PermissionLevel.ask_before_action

        async def handle(self, ctx):  # pragma: no cover - unused
            raise NotImplementedError

    agent = _StubAgent()
    ctx = AgentContext(
        user_id=uuid.uuid4(),
        domain="personal",
        permission_level=PermissionLevel.ask_before_action,
        request_id="test-req",
        input_text="",
        metadata={},
    )
    action = BaseAgent.action(
        agent="stub",
        domain="personal",
        action_class=ActionClass.action_external_send,
        name="send_email",
        target_summary="reply to alice@example.com",
    )

    outcome = await agent.propose(ctx, action, preview="Hi Alice,\nThanks for...")
    assert outcome.decision is Decision.require_approval
    assert outcome.approval is not None
    assert outcome.approval.status.value == "pending"

    # The pending row is queryable.
    pending = await approvals_svc.list_pending(agent="stub")
    assert any(p.id == outcome.approval.id for p in pending)
