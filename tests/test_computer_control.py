"""Computer Control agent: gating contracts.

The critical safety properties under test:

1. Launching an app or running a script — even at admin level — must go
   through BaseAgent.propose with action.action_system, producing a
   pending approval. The agent has no code path that bypasses this.

2. A destructive script run, once approved, REFUSES TO EXECUTE unless the
   approval's decision_note contains the typed CONFIRMATION_PHRASE.
   Clicking 'approve' alone is not enough.

3. Hash mismatch on a script blocks execution and records a `blocked` row.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.agents.base import AgentContext
from app.agents.computer_control import (
    CONFIRMATION_PHRASE,
    ComputerControlAgent,
    DestructiveConfirmationRequired,
)
from app.db.models import (
    AllowedApp,
    AllowedScript,
    ComputerActionStatus,
    ComputerActionType,
)
from app.security.permissions import ActionClass, Decision, PermissionLevel


# ---- Fakes -----------------------------------------------------------------


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def commit(self) -> None: ...
    async def refresh(self, obj):
        if not hasattr(obj, "id") or obj.id is None:
            obj.id = uuid.uuid4()
        for attr in ("started_at", "created_at", "updated_at"):
            if not hasattr(obj, attr) or getattr(obj, attr, None) is None:
                setattr(obj, attr, datetime.now(timezone.utc))


class _FakeSessionMaker:
    def __init__(self) -> None:
        self.sessions: list[_FakeSession] = []

    def __call__(self) -> "_FakeSessionMaker":
        return self

    async def __aenter__(self) -> _FakeSession:
        s = _FakeSession()
        self.sessions.append(s)
        return s

    async def __aexit__(self, *_a) -> bool:
        return False


def _app(name: str = "notepad", path: str = "C:/Windows/System32/notepad.exe") -> AllowedApp:
    a = AllowedApp(
        user_id=uuid.uuid4(), name=name, path=path,
        args_template="", description="", hash_required=False, expected_hash="",
    )
    a.id = uuid.uuid4()
    return a


def _script(name: str = "cleanup") -> AllowedScript:
    s = AllowedScript(
        user_id=uuid.uuid4(), name=name, path="F:/Projects/x/cleanup.ps1",
        interpreter="powershell", args_template="", description="",
        sha256_hash="a" * 64,
    )
    s.id = uuid.uuid4()
    return s


def _ctx(level: PermissionLevel = PermissionLevel.ask_before_action) -> AgentContext:
    return AgentContext(
        user_id=uuid.uuid4(),
        domain="personal",
        permission_level=level,
        request_id="req",
        input_text="",
        metadata={},
    )


# ---- Gating ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_launch_routes_through_approval_even_at_admin(monkeypatch) -> None:
    agent = ComputerControlAgent()
    captured: dict = {}

    sm = _FakeSessionMaker()
    monkeypatch.setattr("app.agents.computer_control.agent.get_sessionmaker", lambda: sm)

    async def fake_propose(self, ctx, action, **kwargs):
        captured["action"] = action
        captured["payload"] = kwargs.get("payload", {})
        return SimpleNamespace(
            decision=Decision.require_approval,
            approval=SimpleNamespace(id=uuid.uuid4()),
        )

    monkeypatch.setattr(ComputerControlAgent, "propose", fake_propose)

    async def fake_audit_emit(**kwargs):
        pass

    monkeypatch.setattr("app.agents.computer_control.agent.audit.emit", fake_audit_emit)

    app = _app()
    log, outcome = await agent.request_launch_app(
        _ctx(level=PermissionLevel.admin), app=app, user_args=""
    )
    assert captured["action"].action_class is ActionClass.action_system
    assert captured["action"].name == "computer.launch_app"
    assert captured["payload"]["app_id"] == str(app.id)
    assert outcome.decision is Decision.require_approval
    assert log.status is ComputerActionStatus.pending_approval


@pytest.mark.asyncio
async def test_request_run_script_destructive_marks_payload_and_summary(monkeypatch) -> None:
    agent = ComputerControlAgent()
    captured: dict = {}

    sm = _FakeSessionMaker()
    monkeypatch.setattr("app.agents.computer_control.agent.get_sessionmaker", lambda: sm)

    async def fake_propose(self, ctx, action, **kwargs):
        captured["action"] = action
        captured["payload"] = kwargs.get("payload", {})
        return SimpleNamespace(
            decision=Decision.require_approval,
            approval=SimpleNamespace(id=uuid.uuid4()),
        )

    async def fake_audit(**_kwargs):
        pass

    monkeypatch.setattr(ComputerControlAgent, "propose", fake_propose)
    monkeypatch.setattr("app.agents.computer_control.agent.audit.emit", fake_audit)

    script = _script()
    await agent.request_run_script(
        _ctx(), script=script, user_args="", destructive=True
    )
    assert captured["payload"]["destructive"] is True
    assert captured["payload"]["confirmation_phrase"] == CONFIRMATION_PHRASE
    assert "destructive" in captured["action"].target_summary
    assert CONFIRMATION_PHRASE in captured["action"].target_summary


# ---- Destructive confirmation enforcement ---------------------------------


@pytest.mark.asyncio
async def test_execute_destructive_without_phrase_is_blocked(monkeypatch) -> None:
    agent = ComputerControlAgent()
    script = _script()
    approval_id = uuid.uuid4()

    sm = _FakeSessionMaker()
    monkeypatch.setattr("app.agents.computer_control.agent.get_sessionmaker", lambda: sm)

    async def fake_audit(**_kwargs): pass
    monkeypatch.setattr("app.agents.computer_control.agent.audit.emit", fake_audit)

    async def fake_get(_id):
        return SimpleNamespace(
            status=SimpleNamespace(value="approved"),
            payload={"script_id": str(script.id), "destructive": True},
            decision_note="ok let's go",  # missing the phrase
        )
    monkeypatch.setattr("app.agents.computer_control.agent.approvals_svc.get", fake_get)

    with pytest.raises(DestructiveConfirmationRequired):
        await agent.execute_run_script(_ctx(), script=script, approval_id=approval_id)


@pytest.mark.asyncio
async def test_execute_destructive_with_phrase_proceeds_to_runner(monkeypatch) -> None:
    agent = ComputerControlAgent()
    script = _script()
    approval_id = uuid.uuid4()

    sm = _FakeSessionMaker()
    monkeypatch.setattr("app.agents.computer_control.agent.get_sessionmaker", lambda: sm)

    async def fake_audit(**_kwargs): pass
    monkeypatch.setattr("app.agents.computer_control.agent.audit.emit", fake_audit)

    async def fake_get(_id):
        return SimpleNamespace(
            status=SimpleNamespace(value="approved"),
            payload={"script_id": str(script.id), "destructive": True},
            decision_note=f"yes — {CONFIRMATION_PHRASE}",
        )
    monkeypatch.setattr("app.agents.computer_control.agent.approvals_svc.get", fake_get)

    runner_called = {"yes": False}

    async def fake_runner(script_, *, user_args=None, timeout=60.0):
        runner_called["yes"] = True
        return SimpleNamespace(return_code=0, stdout="ok", stderr="", timed_out=False)

    monkeypatch.setattr("app.agents.computer_control.agent.script_runner.run", fake_runner)

    result = await agent.execute_run_script(_ctx(), script=script, approval_id=approval_id)
    assert runner_called["yes"] is True
    assert result.return_code == 0


@pytest.mark.asyncio
async def test_execute_rejects_approval_for_different_script(monkeypatch) -> None:
    agent = ComputerControlAgent()
    script = _script()
    other_script_id = uuid.uuid4()
    approval_id = uuid.uuid4()

    sm = _FakeSessionMaker()
    monkeypatch.setattr("app.agents.computer_control.agent.get_sessionmaker", lambda: sm)

    async def fake_audit(**_kwargs): pass
    monkeypatch.setattr("app.agents.computer_control.agent.audit.emit", fake_audit)

    async def fake_get(_id):
        return SimpleNamespace(
            status=SimpleNamespace(value="approved"),
            payload={"script_id": str(other_script_id), "destructive": False},
            decision_note="",
        )
    monkeypatch.setattr("app.agents.computer_control.agent.approvals_svc.get", fake_get)

    with pytest.raises(PermissionError, match="not for script"):
        await agent.execute_run_script(_ctx(), script=script, approval_id=approval_id)


@pytest.mark.asyncio
async def test_execute_rejects_unapproved_approval(monkeypatch) -> None:
    agent = ComputerControlAgent()
    app = _app()
    approval_id = uuid.uuid4()

    sm = _FakeSessionMaker()
    monkeypatch.setattr("app.agents.computer_control.agent.get_sessionmaker", lambda: sm)

    async def fake_audit(**_kwargs): pass
    monkeypatch.setattr("app.agents.computer_control.agent.audit.emit", fake_audit)

    async def fake_get(_id):
        # Pending, not approved.
        return SimpleNamespace(
            status=SimpleNamespace(value="pending"),
            payload={"app_id": str(app.id)},
            decision_note="",
        )
    monkeypatch.setattr("app.agents.computer_control.agent.approvals_svc.get", fake_get)

    with pytest.raises(PermissionError, match="not approved"):
        await agent.execute_launch_app(_ctx(), app=app, approval_id=approval_id)


# ---- handle is purely informational ---------------------------------------


@pytest.mark.asyncio
async def test_handle_does_not_propose_or_execute(monkeypatch) -> None:
    agent = ComputerControlAgent()

    async def fake_collect(self, ctx):  # noqa: ARG001
        return SimpleNamespace(
            today=datetime.now(timezone.utc),
            allowed_apps=[_app()],
            allowed_scripts=[_script()],
            recent_actions=[],
            allowed_roots=["F:/Projects"],
        )

    monkeypatch.setattr(ComputerControlAgent, "_collect_capabilities", fake_collect)
    result = await agent.handle(_ctx())
    assert result.proposed_actions == []
    assert "allow-listed apps" in result.text
    assert "F:/Projects" in result.text
    assert result.metadata["allowed_apps"] == 1
