"""Computer Control Agent (Roadmap Phase 7 — GATED).

Owns: launching allow-listed apps, running allow-listed scripts (hash-
verified at exec time), read-only file search/list/read inside allow-
listed roots, and (later) Playwright sessions on a dedicated profile.

Hard rules (from docs/SECURITY.md, enforced in code):

  * App launches and script runs go through `BaseAgent.propose` with
    `action.action_system` — which requires approval at every permission
    level, INCLUDING admin (per the permission matrix in Phase 1).
  * Destructive scripts (those marked destructive=True at the agent-call
    level) additionally require the approval `decision_note` to contain
    a TYPED CONFIRMATION PHRASE — clicking "approve" alone is not enough.
  * Read-only file ops (search/list/read) are auto-allowed at any level
    >= read_only and audited via `audit.emit`; they do not create approval
    rows because they're already restricted to allow-listed roots.
  * Adding a new app or script is admin-only at the API layer.

This module deliberately does NOT execute scripts/apps inside `handle()`.
The execution surface is exposed via dedicated agent methods that the API
calls explicitly — the LLM cannot conjure an arbitrary execution from a
free-form prompt.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.db.base import get_sessionmaker
from app.db.models import (
    AllowedApp,
    AllowedScript,
    ComputerActionLog,
    ComputerActionStatus,
    ComputerActionType,
)
from app.integrations.computer import (
    app_launcher,
    file_hash,
    file_ops,
    safe_path,
    script_runner,
    subprocess_safe,
)
from app.security import approvals as approvals_svc
from app.security import audit
from app.security.permissions import ActionClass, Decision, PermissionLevel


CONFIRMATION_PHRASE = "I CONFIRM"
"""Typed confirmation phrase required in the approval `decision_note` for
destructive actions. Case- and whitespace-sensitive."""


@dataclass
class _CapabilitiesSnapshot:
    today: datetime
    allowed_apps: list[AllowedApp]
    allowed_scripts: list[AllowedScript]
    recent_actions: list[ComputerActionLog] = field(default_factory=list)
    allowed_roots: list[str] = field(default_factory=list)


class DestructiveConfirmationRequired(PermissionError):
    """Raised when a destructive script run has an approved approval but
    its decision_note does not contain the typed confirmation phrase."""


class ComputerControlAgent(BaseAgent):
    name = "computer_control"
    domains = ("personal", "business")
    default_permission_level = PermissionLevel.read_only

    # ---- handle ------------------------------------------------------------

    async def handle(self, ctx: AgentContext) -> AgentResult:
        snap = await self._collect_capabilities(ctx)
        text = self._build_text(ctx.input_text, snap)
        return AgentResult(
            text=text,
            proposed_actions=[],
            memories_to_write=[],
            metadata={
                "agent": self.name,
                "allowed_apps": len(snap.allowed_apps),
                "allowed_scripts": len(snap.allowed_scripts),
                "recent_actions": len(snap.recent_actions),
                "allowed_roots": snap.allowed_roots,
            },
        )

    async def _collect_capabilities(self, ctx: AgentContext) -> _CapabilitiesSnapshot:
        async with get_sessionmaker()() as session:
            apps = list((await session.execute(
                select(AllowedApp).where(AllowedApp.user_id == ctx.user_id).order_by(AllowedApp.name)
            )).scalars())
            scripts = list((await session.execute(
                select(AllowedScript).where(AllowedScript.user_id == ctx.user_id).order_by(AllowedScript.name)
            )).scalars())
            recent = list((await session.execute(
                select(ComputerActionLog)
                .where(ComputerActionLog.user_id == ctx.user_id)
                .order_by(ComputerActionLog.started_at.desc())
                .limit(10)
            )).scalars())
        return _CapabilitiesSnapshot(
            today=datetime.now(timezone.utc),
            allowed_apps=apps,
            allowed_scripts=scripts,
            recent_actions=recent,
            allowed_roots=[str(r) for r in safe_path.allowed_roots()],
        )

    @staticmethod
    def _build_text(user_input: str, snap: _CapabilitiesSnapshot) -> str:
        lines: list[str] = []
        lines.append(f"Computer Control capabilities as of {snap.today.strftime('%Y-%m-%d')}:")
        lines.append(f"  allow-listed apps: {len(snap.allowed_apps)}")
        for a in snap.allowed_apps[:10]:
            lines.append(f"    - {a.name}: {a.path}")
        lines.append(f"  allow-listed scripts: {len(snap.allowed_scripts)}")
        for s in snap.allowed_scripts[:10]:
            lines.append(f"    - {s.name}: {s.path}")
        lines.append("  allow-listed file roots:")
        for r in snap.allowed_roots:
            lines.append(f"    - {r}")
        if snap.recent_actions:
            lines.append("")
            lines.append("Recent actions:")
            for a in snap.recent_actions[:10]:
                ts = a.started_at.strftime("%Y-%m-%d %H:%M")
                action_type = a.action_type.value if hasattr(a.action_type, "value") else str(a.action_type)
                status = a.status.value if hasattr(a.status, "value") else str(a.status)
                lines.append(f"  - [{ts}] {action_type} {status}: {a.target[:120]}")
        lines.append("")
        lines.append(
            "I can launch the apps and run the scripts above (with your approval), "
            "and read or search files inside the allow-listed roots. "
            "Anything else needs you to add it to the allow-list first."
        )
        if user_input.strip():
            lines.append("")
            lines.append(f"You asked: {user_input}")
        return "\n".join(lines)

    # ---- read-only file ops (auto-allow at read_only+) --------------------

    async def search_files(
        self, ctx: AgentContext, *, query: str, root: str | None = None,
        max_results: int = 50,
    ) -> list[file_ops.FileEntry]:
        if ctx.permission_level is PermissionLevel.read_only:
            pass  # read_only is the minimum; allowed
        results = file_ops.search(query, root=root, max_results=max_results)
        await self._log(
            ctx, action_type=ComputerActionType.file_search,
            target=root or "(all roots)", args=query,
            status=ComputerActionStatus.executed,
        )
        return results

    async def list_dir(self, ctx: AgentContext, *, path: str) -> list[file_ops.FileEntry]:
        results = file_ops.list_dir(path)
        await self._log(
            ctx, action_type=ComputerActionType.file_list,
            target=path, status=ComputerActionStatus.executed,
        )
        return results

    async def read_text(self, ctx: AgentContext, *, path: str) -> str:
        text = file_ops.read_text(path)
        await self._log(
            ctx, action_type=ComputerActionType.file_read,
            target=path, status=ComputerActionStatus.executed,
        )
        return text

    # ---- gated execution (proposes approval) -------------------------------

    async def request_launch_app(
        self, ctx: AgentContext, *, app: AllowedApp, user_args: str = "",
    ):
        """Queue an approval for launching `app`. Returns (action_log, outcome).

        The actual launch happens via `execute_launch_app` AFTER the user
        settles the approval (approve=True).
        """
        action = BaseAgent.action(
            agent=self.name,
            domain=ctx.domain,
            action_class=ActionClass.action_system,
            name="computer.launch_app",
            target_summary=f"launch {app.name} ({app.path})",
        )
        outcome = await self.propose(
            ctx, action,
            preview=f"{app.path} {app.args_template} {user_args}".strip(),
            payload={"app_id": str(app.id), "user_args": user_args},
        )
        log = await self._log(
            ctx,
            action_type=ComputerActionType.launch_app,
            target=f"{app.name} ({app.path})",
            args=user_args,
            status=ComputerActionStatus.pending_approval,
            approval_id=outcome.approval.id if outcome.approval else None,
        )
        return log, outcome

    async def request_run_script(
        self,
        ctx: AgentContext,
        *,
        script: AllowedScript,
        user_args: str = "",
        destructive: bool = False,
    ):
        """Queue an approval for running `script`. Returns (action_log, outcome).

        If `destructive=True`, the eventual `execute_run_script` will
        REFUSE unless the approval's `decision_note` contains the typed
        CONFIRMATION_PHRASE — clicking 'approve' is not enough.
        """
        target_summary = f"run script {script.name} ({script.path})"
        if destructive:
            target_summary += f"  [destructive — requires typed '{CONFIRMATION_PHRASE}' in note]"
        action = BaseAgent.action(
            agent=self.name,
            domain=ctx.domain,
            action_class=ActionClass.action_system,
            name="computer.run_script",
            target_summary=target_summary,
        )
        outcome = await self.propose(
            ctx, action,
            preview=f"{script.interpreter or '(direct)'} {script.path} {script.args_template} {user_args}".strip(),
            payload={
                "script_id": str(script.id),
                "user_args": user_args,
                "destructive": destructive,
                "confirmation_phrase": CONFIRMATION_PHRASE if destructive else "",
            },
        )
        log = await self._log(
            ctx,
            action_type=ComputerActionType.run_script,
            target=f"{script.name} ({script.path})",
            args=user_args + ("  [destructive]" if destructive else ""),
            status=ComputerActionStatus.pending_approval,
            approval_id=outcome.approval.id if outcome.approval else None,
        )
        return log, outcome

    async def execute_launch_app(
        self,
        ctx: AgentContext,
        *,
        app: AllowedApp,
        approval_id: uuid.UUID,
        user_args: str = "",
    ) -> subprocess_safe.RunResult:
        """Execute a previously-approved launch.

        Verifies the approval exists, is `approved` for this app, and then
        launches. Updates the action log row to executed/failed/blocked.
        """
        approval = await approvals_svc.get(approval_id)
        if approval is None or approval.status.value != "approved":
            raise PermissionError(f"approval {approval_id} not approved")
        if (approval.payload or {}).get("app_id") != str(app.id):
            raise PermissionError(
                f"approval {approval_id} is not for app {app.id}"
            )

        try:
            result = await app_launcher.launch(app, user_args=user_args)
            await self._log(
                ctx, action_type=ComputerActionType.launch_app,
                target=f"{app.name} ({app.path})", args=user_args,
                status=ComputerActionStatus.executed,
                approval_id=approval_id, result=result,
            )
            return result
        except (app_launcher.AppLaunchError,
                file_hash.HashMismatchError,
                safe_path.UnsafePathError) as exc:
            await self._log(
                ctx, action_type=ComputerActionType.launch_app,
                target=f"{app.name} ({app.path})", args=user_args,
                status=ComputerActionStatus.blocked,
                approval_id=approval_id, blocked_reason=str(exc),
            )
            raise

    async def execute_run_script(
        self,
        ctx: AgentContext,
        *,
        script: AllowedScript,
        approval_id: uuid.UUID,
        user_args: str = "",
    ) -> subprocess_safe.RunResult:
        approval = await approvals_svc.get(approval_id)
        if approval is None or approval.status.value != "approved":
            raise PermissionError(f"approval {approval_id} not approved")
        payload = approval.payload or {}
        if payload.get("script_id") != str(script.id):
            raise PermissionError(
                f"approval {approval_id} is not for script {script.id}"
            )

        # Destructive scripts require the typed confirmation phrase.
        if payload.get("destructive"):
            note = (approval.decision_note or "").strip()
            if CONFIRMATION_PHRASE not in note:
                await self._log(
                    ctx, action_type=ComputerActionType.run_script,
                    target=f"{script.name} ({script.path})", args=user_args,
                    status=ComputerActionStatus.blocked,
                    approval_id=approval_id,
                    blocked_reason=f"destructive run requires '{CONFIRMATION_PHRASE}' in decision_note",
                )
                raise DestructiveConfirmationRequired(
                    f"destructive script requires typed '{CONFIRMATION_PHRASE}' in approval note"
                )

        try:
            result = await script_runner.run(script, user_args=user_args)
            await self._log(
                ctx, action_type=ComputerActionType.run_script,
                target=f"{script.name} ({script.path})", args=user_args,
                status=ComputerActionStatus.executed,
                approval_id=approval_id, result=result,
            )
            return result
        except (script_runner.ScriptRunError,
                file_hash.HashMismatchError,
                safe_path.UnsafePathError) as exc:
            await self._log(
                ctx, action_type=ComputerActionType.run_script,
                target=f"{script.name} ({script.path})", args=user_args,
                status=ComputerActionStatus.blocked,
                approval_id=approval_id, blocked_reason=str(exc),
            )
            raise

    # ---- logging helper ----------------------------------------------------

    async def _log(
        self,
        ctx: AgentContext,
        *,
        action_type: ComputerActionType,
        target: str,
        args: str = "",
        status: ComputerActionStatus,
        approval_id: uuid.UUID | None = None,
        blocked_reason: str = "",
        result: subprocess_safe.RunResult | None = None,
    ) -> ComputerActionLog:
        log = ComputerActionLog(
            user_id=ctx.user_id,
            action_type=action_type,
            target=target,
            args=args,
            status=status,
            approval_id=approval_id,
            blocked_reason=blocked_reason,
            stdout_excerpt=result.stdout if result else "",
            stderr_excerpt=result.stderr if result else "",
            return_code=result.return_code if result else None,
            completed_at=datetime.now(timezone.utc) if status is not ComputerActionStatus.pending_approval else None,
        )
        async with get_sessionmaker()() as session:
            session.add(log)
            await session.commit()
            await session.refresh(log)
        # Mirror to the security audit log too — computer_action_log is for
        # debugging/visibility; audit_log is the append-only security record.
        await audit.emit(
            agent=self.name,
            domain=ctx.domain,
            action_class=(
                "read" if action_type in (
                    ComputerActionType.file_search,
                    ComputerActionType.file_list,
                    ComputerActionType.file_read,
                ) else "action.system"
            ),
            action_name=f"computer.{action_type.value}",
            target_summary=target[:200],
            decision=status.value,
            user_id=ctx.user_id,
            request_id=ctx.request_id,
            approval_id=approval_id,
            extra={"args": args, "blocked_reason": blocked_reason} if blocked_reason else {"args": args},
        )
        return log


# Re-export from package
__all__ = [
    "ComputerControlAgent",
    "CONFIRMATION_PHRASE",
    "DestructiveConfirmationRequired",
]
