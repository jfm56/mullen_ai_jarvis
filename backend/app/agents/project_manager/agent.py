"""Project Manager Agent (Roadmap Phase 5).

Tracks active projects across business/school/grant/drone/EMS/healthcare/AI.
"""

from __future__ import annotations

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.security.permissions import PermissionLevel


class ProjectManagerAgent(BaseAgent):
    name = "project_manager"
    domains = ("business",)
    default_permission_level = PermissionLevel.ask_before_action

    async def handle(self, ctx: AgentContext) -> AgentResult:
        return AgentResult(
            text="Project Manager stub. See docs/ROADMAP.md Phase 5.",
            proposed_actions=[],
            memories_to_write=[],
            metadata={"agent": self.name, "stage": "stub"},
        )
