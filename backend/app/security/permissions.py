"""Permission levels and action classes.

See docs/SECURITY.md for the normative model. This module is the
runtime enforcement layer for that model.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PermissionLevel(str, Enum):
    read_only = "read_only"
    draft_only = "draft_only"
    ask_before_action = "ask_before_action"
    approved_automation = "approved_automation"
    admin = "admin"


class ActionClass(str, Enum):
    read = "read"
    draft = "draft"
    action_low_risk = "action.low_risk"
    action_external_send = "action.external_send"
    action_financial = "action.financial"
    action_destructive = "action.destructive"
    action_system = "action.system"


class Decision(str, Enum):
    allow = "allow"
    require_approval = "require_approval"
    deny = "deny"


_NEVER_AUTO = {
    ActionClass.action_external_send,
    ActionClass.action_financial,
    ActionClass.action_destructive,
    ActionClass.action_system,
}


@dataclass(frozen=True)
class ProposedAction:
    agent: str
    domain: str
    action_class: ActionClass
    name: str
    target_summary: str


def decide(level: PermissionLevel, action: ProposedAction) -> Decision:
    """Return whether an action is allowed, needs approval, or denied.

    The 'never auto' rule (see docs/SECURITY.md) overrides higher
    permission levels for the most sensitive action classes — they
    always require a per-instance approval, including for admin.
    """
    if action.action_class is ActionClass.read:
        return Decision.allow

    if action.action_class is ActionClass.draft:
        if level is PermissionLevel.read_only:
            return Decision.deny
        return Decision.allow

    if action.action_class in _NEVER_AUTO:
        if level is PermissionLevel.read_only:
            return Decision.deny
        return Decision.require_approval

    if action.action_class is ActionClass.action_low_risk:
        if level is PermissionLevel.read_only:
            return Decision.deny
        if level in (PermissionLevel.draft_only, PermissionLevel.ask_before_action):
            return Decision.require_approval
        return Decision.allow

    return Decision.deny
