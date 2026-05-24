"""Personal Assistant Agent — first build target (Roadmap Phase 2).

Owns: daily plan, calendar, tasks, reminders, family scheduling,
voice quick-add. Personal domain only.
"""

from __future__ import annotations

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.security.permissions import PermissionLevel


class PersonalAssistantAgent(BaseAgent):
    name = "personal_assistant"
    domains = ("personal",)
    default_permission_level = PermissionLevel.ask_before_action

    async def handle(self, ctx: AgentContext) -> AgentResult:
        # Phase 2 implementation. For Phase 0 we return an explicit placeholder
        # so wiring through the API surface can be tested end-to-end.
        return AgentResult(
            text="Personal Assistant is scaffolded but not yet implemented. See docs/ROADMAP.md Phase 2.",
            proposed_actions=[],
            memories_to_write=[],
            metadata={"agent": self.name, "stage": "phase_0_scaffold"},
        )
