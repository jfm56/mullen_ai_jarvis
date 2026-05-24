"""Lead Generation Agent (Roadmap Phase 6).

Research prospects, score leads, draft outreach, track pipeline.
Never contacts a lead directly — drafts and queues for approval.
"""

from __future__ import annotations

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.security.permissions import PermissionLevel


class LeadGenerationAgent(BaseAgent):
    name = "lead_generation"
    domains = ("business",)
    default_permission_level = PermissionLevel.ask_before_action

    async def handle(self, ctx: AgentContext) -> AgentResult:
        return AgentResult(
            text="Lead Generation stub. See docs/ROADMAP.md Phase 6.",
            proposed_actions=[],
            memories_to_write=[],
            metadata={"agent": self.name, "stage": "stub"},
        )
