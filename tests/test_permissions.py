"""Permission engine: the rule that anything externally visible needs approval.

This test is the regression suite for docs/SECURITY.md. If a future change
relaxes the matrix here without an accompanying SECURITY.md edit, the
docs and code have drifted apart.
"""

from __future__ import annotations

import pytest

from app.security.permissions import (
    ActionClass,
    Decision,
    PermissionLevel,
    ProposedAction,
    decide,
)


def _action(cls: ActionClass) -> ProposedAction:
    return ProposedAction(
        agent="test",
        domain="personal",
        action_class=cls,
        name="test_action",
        target_summary="test",
    )


# (level, action_class) -> expected Decision
EXPECTED: dict[tuple[PermissionLevel, ActionClass], Decision] = {}
for lvl in PermissionLevel:
    EXPECTED[(lvl, ActionClass.read)] = Decision.allow

EXPECTED[(PermissionLevel.read_only, ActionClass.draft)] = Decision.deny
for lvl in (
    PermissionLevel.draft_only,
    PermissionLevel.ask_before_action,
    PermissionLevel.approved_automation,
    PermissionLevel.admin,
):
    EXPECTED[(lvl, ActionClass.draft)] = Decision.allow

EXPECTED[(PermissionLevel.read_only, ActionClass.action_low_risk)] = Decision.deny
EXPECTED[(PermissionLevel.draft_only, ActionClass.action_low_risk)] = Decision.require_approval
EXPECTED[(PermissionLevel.ask_before_action, ActionClass.action_low_risk)] = (
    Decision.require_approval
)
EXPECTED[(PermissionLevel.approved_automation, ActionClass.action_low_risk)] = Decision.allow
EXPECTED[(PermissionLevel.admin, ActionClass.action_low_risk)] = Decision.allow

# The "never auto" classes always need approval (even at admin), or deny at read_only.
for cls in (
    ActionClass.action_external_send,
    ActionClass.action_financial,
    ActionClass.action_destructive,
    ActionClass.action_system,
):
    EXPECTED[(PermissionLevel.read_only, cls)] = Decision.deny
    for lvl in (
        PermissionLevel.draft_only,
        PermissionLevel.ask_before_action,
        PermissionLevel.approved_automation,
        PermissionLevel.admin,
    ):
        EXPECTED[(lvl, cls)] = Decision.require_approval


@pytest.mark.parametrize(("level", "action_class", "expected"), [
    (lvl, cls, EXPECTED[(lvl, cls)]) for (lvl, cls) in EXPECTED
])
def test_decision_matrix(
    level: PermissionLevel, action_class: ActionClass, expected: Decision
) -> None:
    assert decide(level, _action(action_class)) is expected


def test_matrix_is_complete() -> None:
    """Every (level, class) pair must be enumerated above so we don't
    silently miss a combination if a new variant is added later."""
    expected_count = len(list(PermissionLevel)) * len(list(ActionClass))
    assert len(EXPECTED) == expected_count
