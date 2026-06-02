"""Computer Control agent's browser-action surface.

Layered above `app/integrations/computer/browser.py`. This module:

  1. Loads the per-user `BrowserAllowedDomain` list before any navigate.
  2. Decides which Playwright primitive needs approval and which doesn't:
       - navigate, screenshot, get_text          → auto-allow (logged)
       - click on non-danger text                → auto-allow at admin /
         approved_automation, approval at lower levels
       - submit / click on danger text /
         form fill+submit                        → action.external_send
         (always requires approval, including admin)
  3. Writes a `BrowserAction` row per attempt + mirrors to `audit_log`.
"""

from __future__ import annotations

import fnmatch
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.agents.base import AgentContext, BaseAgent, ProposalOutcome
from app.db.base import get_sessionmaker
from app.db.models import (
    BrowserAction,
    BrowserActionStatus,
    BrowserActionType,
    BrowserAllowedDomain,
    BrowserSession,
    BrowserSessionStatus,
)
from app.integrations.computer import browser as pw
from app.security import audit
from app.security.permissions import ActionClass


class BrowserNotAvailable(RuntimeError):
    """Playwright extra isn't installed."""


@dataclass
class BrowserStartResult:
    session: BrowserSession
    handle: pw.BrowserSessionHandle


async def _load_allowed_patterns(user_id: uuid.UUID) -> list[str]:
    async with get_sessionmaker()() as session:
        result = await session.execute(
            select(BrowserAllowedDomain.pattern).where(
                BrowserAllowedDomain.user_id == user_id
            )
        )
        return [row[0] for row in result.all()]


async def _allows_submit(user_id: uuid.UUID, url: str) -> bool:
    """Is the URL's host in a domain that has `allow_form_submit=True`?"""
    host = pw.urlparse(url).hostname or ""  # type: ignore[attr-defined]
    async with get_sessionmaker()() as session:
        result = await session.execute(
            select(BrowserAllowedDomain).where(
                BrowserAllowedDomain.user_id == user_id,
                BrowserAllowedDomain.allow_form_submit.is_(True),
            )
        )
        for row in result.scalars():
            if fnmatch.fnmatchcase(host.lower(), row.pattern.lower()):
                return True
    return False


# Patch urlparse onto the pw module for the helper above (read-only usage)
from urllib.parse import urlparse as _urlparse  # noqa: E402

pw.urlparse = _urlparse  # type: ignore[attr-defined]


# ---- session lifecycle -----------------------------------------------------


async def start_session(
    ctx: AgentContext,
    *,
    label: str = "",
    headless: bool = True,
    idle_timeout_seconds: int = 600,
) -> BrowserStartResult:
    if not pw.is_available():
        raise BrowserNotAvailable(
            "Playwright is not installed. Install with: "
            "pip install -e .[automation]  (from backend/)  "
            "AND run: python -m playwright install chromium"
        )
    patterns = await _load_allowed_patterns(ctx.user_id)
    if not patterns:
        raise PermissionError(
            "No BrowserAllowedDomain rows for this user. Add at least one "
            "(admin-only) before starting a browser session."
        )

    session_id = uuid.uuid4()
    handle = await pw.start_session(
        session_id=str(session_id),
        user_id=str(ctx.user_id),
        allowed_patterns=patterns,
        headless=headless,
    )

    row = BrowserSession(
        id=session_id,
        user_id=ctx.user_id,
        label=label,
        profile_dir=str(handle.profile_dir),
        status=BrowserSessionStatus.active,
        idle_timeout_seconds=idle_timeout_seconds,
        started_at=handle.started_at,
        last_active_at=handle.last_active_at,
    )
    async with get_sessionmaker()() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)

    await audit.emit(
        agent="computer_control",
        domain=ctx.domain,
        action_class="action.system",
        action_name="browser.start",
        target_summary=f"browser session {session_id} (label={label!r})",
        decision="executed",
        user_id=ctx.user_id,
        request_id=ctx.request_id,
    )
    return BrowserStartResult(session=row, handle=handle)


async def stop_session(ctx: AgentContext, session_id: uuid.UUID) -> None:
    await pw.stop_session(str(session_id))
    async with get_sessionmaker()() as session:
        row = await session.get(BrowserSession, session_id)
        if row is not None and row.user_id == ctx.user_id:
            row.status = BrowserSessionStatus.closed
            row.closed_at = datetime.now(timezone.utc)
            await session.commit()
    await audit.emit(
        agent="computer_control",
        domain=ctx.domain,
        action_class="action.system",
        action_name="browser.stop",
        target_summary=f"browser session {session_id}",
        decision="executed",
        user_id=ctx.user_id,
        request_id=ctx.request_id,
    )


# ---- per-action helpers ----------------------------------------------------


async def _require_live(ctx: AgentContext, session_id: uuid.UUID) -> pw.BrowserSessionHandle:
    handle = pw.get_live(str(session_id))
    if handle is None:
        raise PermissionError(f"browser session {session_id} not live in this process")
    if handle.user_id != str(ctx.user_id):
        raise PermissionError(f"browser session {session_id} belongs to another user")
    return handle


async def _log_action(
    *,
    ctx: AgentContext,
    session_id: uuid.UUID,
    action_type: BrowserActionType,
    target: str,
    args: dict[str, Any] | None = None,
    status: BrowserActionStatus,
    blocked_reason: str = "",
    result_excerpt: str = "",
    approval_id: uuid.UUID | None = None,
) -> BrowserAction:
    row = BrowserAction(
        session_id=session_id,
        user_id=ctx.user_id,
        action_type=action_type,
        target=target,
        args=args or {},
        status=status,
        blocked_reason=blocked_reason,
        result_excerpt=result_excerpt[:2_000],
        approval_id=approval_id,
        completed_at=(
            datetime.now(timezone.utc)
            if status is not BrowserActionStatus.pending_approval
            else None
        ),
    )
    async with get_sessionmaker()() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
    await audit.emit(
        agent="computer_control",
        domain=ctx.domain,
        action_class=(
            "read" if action_type in (
                BrowserActionType.navigate,
                BrowserActionType.screenshot,
                BrowserActionType.get_text,
                BrowserActionType.wait,
            )
            else "action.system"
        ),
        action_name=f"browser.{action_type.value}",
        target_summary=target[:200],
        decision=status.value,
        user_id=ctx.user_id,
        request_id=ctx.request_id,
        approval_id=approval_id,
        extra={"blocked_reason": blocked_reason} if blocked_reason else {},
    )
    return row


# ---- read-only / no-approval actions --------------------------------------


async def navigate(
    ctx: AgentContext, session_id: uuid.UUID, url: str
) -> BrowserAction:
    handle = await _require_live(ctx, session_id)
    try:
        nav = await pw.navigate(handle, url)
    except pw.BrowserNavigationError as exc:
        return await _log_action(
            ctx=ctx, session_id=session_id,
            action_type=BrowserActionType.navigate,
            target=url, status=BrowserActionStatus.blocked,
            blocked_reason=str(exc),
        )
    # Persist current_url on session row
    async with get_sessionmaker()() as session:
        row = await session.get(BrowserSession, session_id)
        if row is not None:
            row.current_url = nav.url
            row.last_active_at = handle.last_active_at
            await session.commit()
    return await _log_action(
        ctx=ctx, session_id=session_id,
        action_type=BrowserActionType.navigate,
        target=url, status=BrowserActionStatus.executed,
        result_excerpt=f"{nav.status_code} {nav.title}",
    )


async def screenshot(
    ctx: AgentContext, session_id: uuid.UUID, *, full_page: bool = False
) -> tuple[bytes, BrowserAction]:
    handle = await _require_live(ctx, session_id)
    png = await pw.screenshot(handle, full_page=full_page)
    row = await _log_action(
        ctx=ctx, session_id=session_id,
        action_type=BrowserActionType.screenshot,
        target=handle.page.url, status=BrowserActionStatus.executed,
        result_excerpt=f"{len(png)} bytes",
    )
    return png, row


async def get_text(
    ctx: AgentContext, session_id: uuid.UUID, selector: str
) -> BrowserAction:
    handle = await _require_live(ctx, session_id)
    text = await pw.get_text(handle, selector)
    return await _log_action(
        ctx=ctx, session_id=session_id,
        action_type=BrowserActionType.get_text,
        target=selector,
        args={"matched": text.matched},
        status=BrowserActionStatus.executed,
        result_excerpt=text.text,
    )


# ---- gated actions ---------------------------------------------------------


async def request_click(
    agent: BaseAgent,
    ctx: AgentContext,
    session_id: uuid.UUID,
    selector: str,
) -> tuple[BrowserAction, ProposalOutcome | None]:
    """Click the first match. If the element's text contains a danger word,
    routes through approval (action.external_send). Otherwise executes
    immediately and logs."""
    handle = await _require_live(ctx, session_id)
    try:
        result = await pw.click(handle, selector, allow_danger=False)
    except pw.DangerActionRequiresApproval:
        # Re-fetch the matched text for the preview.
        try:
            preview_text = (
                await handle.page.locator(selector).first.text_content(timeout=2_000)
            ) or ""
        except Exception:  # noqa: BLE001
            preview_text = ""
        action = BaseAgent.action(
            agent=agent.name,
            domain=ctx.domain,
            action_class=ActionClass.action_external_send,
            name="browser.click_danger",
            target_summary=(
                f"click {selector} on {handle.page.url} "
                f"(text: {preview_text[:80].strip()!r})"
            ),
        )
        outcome = await agent.propose(
            ctx, action,
            preview=preview_text[:500],
            payload={
                "session_id": str(session_id),
                "selector": selector,
                "url": handle.page.url,
            },
        )
        row = await _log_action(
            ctx=ctx, session_id=session_id,
            action_type=BrowserActionType.click,
            target=selector,
            args={"url": handle.page.url, "danger": True},
            status=BrowserActionStatus.pending_approval,
            blocked_reason="danger-word match — approval required",
            approval_id=outcome.approval.id if outcome.approval else None,
        )
        return row, outcome
    row = await _log_action(
        ctx=ctx, session_id=session_id,
        action_type=BrowserActionType.click,
        target=selector,
        args={"url": handle.page.url, "matched_text": result.matched_text[:80]},
        status=BrowserActionStatus.executed,
        result_excerpt=result.matched_text,
    )
    return row, None


async def type_text(
    ctx: AgentContext,
    session_id: uuid.UUID,
    selector: str,
    value: str,
) -> BrowserAction:
    handle = await _require_live(ctx, session_id)
    # Auto-allowed; typing alone is not externally visible until submit.
    await pw.type_text(handle, selector, value, submit=False)
    return await _log_action(
        ctx=ctx, session_id=session_id,
        action_type=BrowserActionType.type_text,
        target=selector,
        args={"url": handle.page.url, "length": len(value)},
        status=BrowserActionStatus.executed,
        result_excerpt=f"typed {len(value)} chars",
    )


async def request_submit(
    agent: BaseAgent,
    ctx: AgentContext,
    session_id: uuid.UUID,
    submit_selector: str,
) -> tuple[BrowserAction, ProposalOutcome]:
    """Submitting a form is action.external_send — ALWAYS requires
    approval, even at admin. No allow_form_submit shortcut here."""
    handle = await _require_live(ctx, session_id)
    try:
        preview_text = (
            await handle.page.locator(submit_selector).first.text_content(timeout=2_000)
        ) or ""
    except Exception:  # noqa: BLE001
        preview_text = ""

    action = BaseAgent.action(
        agent=agent.name,
        domain=ctx.domain,
        action_class=ActionClass.action_external_send,
        name="browser.submit",
        target_summary=(
            f"submit form on {handle.page.url} via {submit_selector} "
            f"(button text: {preview_text[:80].strip()!r})"
        ),
    )
    outcome = await agent.propose(
        ctx, action,
        preview=preview_text[:500],
        payload={
            "session_id": str(session_id),
            "submit_selector": submit_selector,
            "url": handle.page.url,
        },
    )
    row = await _log_action(
        ctx=ctx, session_id=session_id,
        action_type=BrowserActionType.submit,
        target=submit_selector,
        args={"url": handle.page.url},
        status=BrowserActionStatus.pending_approval,
        approval_id=outcome.approval.id if outcome.approval else None,
    )
    return row, outcome


async def execute_submit(
    ctx: AgentContext,
    session_id: uuid.UUID,
    submit_selector: str,
    approval_id: uuid.UUID,
) -> BrowserAction:
    """Caller must verify the approval is settled (approved) before calling."""
    handle = await _require_live(ctx, session_id)
    try:
        result = await pw.submit_form(handle, submit_selector=submit_selector)
    except Exception as exc:  # noqa: BLE001
        return await _log_action(
            ctx=ctx, session_id=session_id,
            action_type=BrowserActionType.submit,
            target=submit_selector,
            args={"url": handle.page.url},
            status=BrowserActionStatus.failed,
            blocked_reason=str(exc)[:500],
            approval_id=approval_id,
        )
    return await _log_action(
        ctx=ctx, session_id=session_id,
        action_type=BrowserActionType.submit,
        target=submit_selector,
        args={
            "url_before": handle.page.url,
            "url_after": result.final_url,
            "matched_text": result.matched_text[:80],
        },
        status=BrowserActionStatus.executed,
        result_excerpt=f"submit landed on {result.final_url}",
        approval_id=approval_id,
    )
