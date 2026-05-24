"""Marketing Agent (Roadmap Phase 6).

Social drafts for healthcare, EMS, fire/public safety, drone analytics,
and AI consulting verticals. Draft-only by default — never auto-posts.
"""

from __future__ import annotations

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.security.permissions import PermissionLevel


class MarketingAgent(BaseAgent):
    name = "marketing"
    domains = ("business", "public")
    default_permission_level = PermissionLevel.draft_only

    async def handle(self, ctx: AgentContext) -> AgentResult:
        return AgentResult(
            text="Marketing stub. See docs/ROADMAP.md Phase 6.",
            proposed_actions=[],
            memories_to_write=[],
            metadata={"agent": self.name, "stage": "stub"},
        )
