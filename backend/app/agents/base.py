"""BaseAgent contract.

Every agent in app/agents/* subclasses this. The contract enforces:
  * declared name, domains, and default permission level
  * action proposals go through the permission engine
  * external calls go through app/integrations/*
  * memory access goes through app/memory/store.py
  * every meaningful step is audited

See docs/AGENTS.md for the human-readable description of each agent.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

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

    user_id: str
    domain: str
    permission_level: PermissionLevel
    request_id: str
    input_text: str
    metadata: dict[str, Any]


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

    async def propose(self, ctx: AgentContext, action: ProposedAction) -> Decision:
        """Run an action through the permission engine and audit the decision."""
        started = time.monotonic()
        decision = decide(ctx.permission_level, action)
        audit.emit(
            agent=self.name,
            domain=ctx.domain,
            action_class=action.action_class.value,
            action_name=action.name,
            target_summary=action.target_summary,
            decision=decision.value,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        return decision

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
