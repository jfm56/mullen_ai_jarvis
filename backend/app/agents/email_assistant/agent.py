"""Email Assistant Agent (Roadmap Phase 4).

Inbox triage, summaries, draft replies, scam detection. Never sends.
"""

from __future__ import annotations

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.security.permissions import PermissionLevel


class EmailAssistantAgent(BaseAgent):
    name = "email_assistant"
    domains = ("personal", "business")
    default_permission_level = PermissionLevel.draft_only

    async def handle(self, ctx: AgentContext) -> AgentResult:
        return AgentResult(
            text="Email Assistant stub. See docs/ROADMAP.md Phase 4.",
            proposed_actions=[],
            memories_to_write=[],
            metadata={"agent": self.name, "stage": "stub"},
        )
