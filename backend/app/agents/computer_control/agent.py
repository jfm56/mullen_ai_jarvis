"""Computer Control Agent (Roadmap Phase 7 — gated on solid Phases 1+2).

Allow-listed apps, file ops, approved scripts, Playwright sessions.
Default read-only. Destructive ops always require typed confirmation.
"""

from __future__ import annotations

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.security.permissions import PermissionLevel


class ComputerControlAgent(BaseAgent):
    name = "computer_control"
    domains = ("personal", "business")
    default_permission_level = PermissionLevel.read_only

    async def handle(self, ctx: AgentContext) -> AgentResult:
        return AgentResult(
            text="Computer Control stub. See docs/ROADMAP.md Phase 7.",
            proposed_actions=[],
            memories_to_write=[],
            metadata={"agent": self.name, "stage": "stub"},
        )
