"""BaseAgent contract.

Every agent in app/agents/* subclasses this. The contract enforces:
  * declared name, domains, and default permission level
  * action proposals go through the permission engine
  * `require_approval` decisions create a pending Approval row
  * every meaningful step is audited
  * external calls go through app/integrations/*
  * memory access goes through app/memory/store.py
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from app.db.models import Approval
from app.security import approvals as approvals_svc
from app.security import audit
from app.security.permissions import (
    ActionClass,
    Decision,
    PermissionLevel,
    ProposedAction,
    decide,
)


@dataclass
class AgentContext:
    """Per-request context handed to an agent."""

    user_id: uuid.UUID
    domain: str
    permission_level: PermissionLevel
    request_id: str
    input_text: str
    metadata: dict[str, Any]


@dataclass
class ProposalOutcome:
    """What `BaseAgent.propose` returns."""

    decision: Decision
    approval: Approval | None  # populated when decision is require_approval


@dataclass
class AgentResult:
    """What an agent returns from `handle`."""

    text: str
    proposed_actions: list[ProposedAction]
    memories_to_write: list[tuple[str, str]]  # (kind, text)
    metadata: dict[str, Any]


class BaseAgent(ABC):
    name: str
    domains: tuple[str, ...]
    default_permission_level: PermissionLevel

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for attr in ("name", "domains", "default_permission_level"):
            if not hasattr(cls, attr):
                raise TypeError(f"{cls.__name__} must declare class attribute '{attr}'")

    @abstractmethod
    async def handle(self, ctx: AgentContext) -> AgentResult:
        ...

    async def propose(
        self,
        ctx: AgentContext,
        action: ProposedAction,
        *,
        preview: str = "",
        payload: dict[str, Any] | None = None,
    ) -> ProposalOutcome:
        """Run an action through the permission engine.

        - `allow` → audit and return; the agent should execute next.
        - `require_approval` → create a pending Approval and return it;
          the agent must NOT execute. The executor runs only after the
          user calls POST /approvals/{id}/decision with approve=true.
        - `deny` → audit and return; the agent must NOT execute.
        """
        started = time.monotonic()
        decision = decide(ctx.permission_level, action)
        latency_ms = int((time.monotonic() - started) * 1000)

        approval: Approval | None = None
        if decision is Decision.require_approval:
            approval = await approvals_svc.create_pending(
                agent=self.name,
                domain=ctx.domain,
                action_class=action.action_class.value,
                action_name=action.name,
                target_summary=action.target_summary,
                preview=preview,
                payload=payload,
                request_id=ctx.request_id,
            )
            # approvals_svc.create_pending already wrote one audit row
            # tagged 'approval_queued'. We don't duplicate it here.
            return ProposalOutcome(decision=decision, approval=approval)

        await audit.emit(
            agent=self.name,
            domain=ctx.domain,
            action_class=action.action_class.value,
            action_name=action.name,
            target_summary=action.target_summary,
            decision=decision.value,
            user_id=ctx.user_id,
            request_id=ctx.request_id,
            latency_ms=latency_ms,
        )
        return ProposalOutcome(decision=decision, approval=None)

    @staticmethod
    def action(
        *,
        agent: str,
        domain: str,
        action_class: ActionClass,
        name: str,
        target_summary: str,
    ) -> ProposedAction:
        return ProposedAction(
            agent=agent,
            domain=domain,
            action_class=action_class,
            name=name,
            target_summary=target_summary,
        )
