"""Business Development Agent (Roadmap Phase 5).

Grants, RFPs, partnerships, proposals, opportunity pipeline.
"""

from __future__ import annotations

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.security.permissions import PermissionLevel


class BusinessDevelopmentAgent(BaseAgent):
    name = "business_development"
    domains = ("business",)
    default_permission_level = PermissionLevel.ask_before_action

    async def handle(self, ctx: AgentContext) -> AgentResult:
        return AgentResult(
            text="Business Development stub. See docs/ROADMAP.md Phase 5.",
            proposed_actions=[],
            memories_to_write=[],
            metadata={"agent": self.name, "stage": "stub"},
        )
