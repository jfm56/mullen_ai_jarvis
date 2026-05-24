"""Permission engine — the rule that anything externally visible needs approval."""

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


def test_read_always_allowed() -> None:
    for level in PermissionLevel:
        assert decide(level, _action(ActionClass.read)) is Decision.allow


@pytest.mark.parametrize(
    "cls",
    [
        ActionClass.action_external_send,
        ActionClass.action_financial,
        ActionClass.action_destructive,
        ActionClass.action_system,
    ],
)
def test_never_auto_classes_require_approval_even_at_admin(cls: ActionClass) -> None:
    assert decide(PermissionLevel.admin, _action(cls)) is Decision.require_approval


def test_read_only_cannot_draft() -> None:
    assert decide(PermissionLevel.read_only, _action(ActionClass.draft)) is Decision.deny
