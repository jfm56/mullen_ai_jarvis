"""SQLAlchemy models.

Phase 1: User, AuditLog, Approval (security spine).
Phase 2: Task, Reminder, CalendarEvent, OAuthAccount (Personal Assistant).
Phase 3: Memory, TopicDisable (memory subsystem with domain isolation).
Phase 4: Email, EmailDraft (Email Assistant).
Phase 5: Project, ProjectNote, Opportunity, Proposal (Project Mgr + BD).
Phase 6: SocialPost, Lead, OutreachMessage (Marketing + Lead Gen).
Phase 7: AllowedApp, AllowedScript, ComputerActionLog (Computer Control).
Phase 5b: OrgProfile, GrantApplication, GrantSection, GrantAttachment (Grant Writer).
Phase 8: BackupRecord (encrypted backup tracking).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import get_settings
from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class ApprovalStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"
    executed = "executed"
    failed = "failed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    approvals: Mapped[list[Approval]] = relationship(back_populates="decided_by_user")


class AuditLog(Base):
    """Append-only audit log.

    A Postgres trigger created in migration 0001 blocks UPDATE and DELETE
    on this table — the SQLAlchemy mapping intentionally omits update paths.
    """

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    agent: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    domain: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    action_class: Mapped[str] = mapped_column(String(64), nullable=False)
    action_name: Mapped[str] = mapped_column(String(128), nullable=False)
    target_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    integration: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    latency_ms: Mapped[int] = mapped_column(default=0, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    output_hash: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    approval_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approvals.id", ondelete="SET NULL")
    )
    extra: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    __table_args__ = (
        Index("ix_audit_log_agent_ts", "agent", "timestamp"),
        Index("ix_audit_log_domain_ts", "domain", "timestamp"),
    )


class Approval(Base):
    """An action the agent has proposed and the user must decide on.

    Created when the permission engine returns `require_approval`.
    Settled when the user approves or rejects via /approvals/{id}/decision.
    """

    __tablename__ = "approvals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    agent: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    domain: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    action_class: Mapped[str] = mapped_column(String(64), nullable=False)
    action_name: Mapped[str] = mapped_column(String(128), nullable=False)
    target_summary: Mapped[str] = mapped_column(Text, nullable=False)
    preview: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    status: Mapped[ApprovalStatus] = mapped_column(
        SAEnum(ApprovalStatus, name="approval_status", native_enum=False),
        default=ApprovalStatus.pending,
        nullable=False,
        index=True,
    )
    decision_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    request_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    decided_by_user: Mapped[User | None] = relationship(back_populates="approvals")


# ---------------------------------------------------------------------------
# Phase 2: Personal Assistant — tasks, reminders, calendar, OAuth accounts.
# ---------------------------------------------------------------------------


class TaskStatus(str, enum.Enum):
    pending = "pending"
    in_progress = "in_progress"
    done = "done"
    cancelled = "cancelled"


class TaskPriority(str, enum.Enum):
    low = "low"
    normal = "normal"
    high = "high"
    urgent = "urgent"


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    domain: Mapped[str] = mapped_column(String(64), nullable=False, default="personal", index=True)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[TaskStatus] = mapped_column(
        SAEnum(TaskStatus, name="task_status", native_enum=False),
        default=TaskStatus.pending,
        nullable=False,
        index=True,
    )
    priority: Mapped[TaskPriority] = mapped_column(
        SAEnum(TaskPriority, name="task_priority", native_enum=False),
        default=TaskPriority.normal,
        nullable=False,
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_tasks_user_status", "user_id", "status"),
        Index("ix_tasks_user_due", "user_id", "due_at"),
    )


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    domain: Mapped[str] = mapped_column(String(64), nullable=False, default="personal")
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL")
    )

    text: Mapped[str] = mapped_column(Text, nullable=False)
    fire_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    fired: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_reminders_due_unfired", "fire_at", "fired", "cancelled"),
    )


class CalendarEvent(Base):
    """Mirror of an external calendar event (Google Calendar in Phase 2).

    `external_id` + `source` uniquely identify the upstream event so sync
    is idempotent. Locally-created events have source='local' and no external_id
    until they round-trip to the upstream calendar.
    """

    __tablename__ = "calendar_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    domain: Mapped[str] = mapped_column(String(64), nullable=False, default="personal", index=True)

    source: Mapped[str] = mapped_column(String(32), nullable=False, default="google")
    external_id: Mapped[str | None] = mapped_column(String(255))
    calendar_id: Mapped[str] = mapped_column(String(255), nullable=False, default="primary")

    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    location: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    all_day: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    raw: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    __table_args__ = (
        Index("ix_calendar_events_user_start", "user_id", "start_at"),
        Index(
            "ix_calendar_events_source_external",
            "source",
            "external_id",
            unique=True,
            postgresql_where=Text("external_id IS NOT NULL"),
        ),
    )


class OAuthAccount(Base):
    """OAuth token reference for an external service.

    The actual refresh token is stored in the OS keyring (see
    `app/security/secrets.py`). This row holds metadata: which provider,
    which account, which scopes were granted, when the access token expires.
    The keyring key is `oauth_refresh:{provider}:{account_email}`.
    """

    __tablename__ = "oauth_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    account_email: Mapped[str] = mapped_column(String(255), nullable=False)
    scopes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    access_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index(
            "ix_oauth_provider_account",
            "user_id",
            "provider",
            "account_email",
            unique=True,
        ),
    )


# ---------------------------------------------------------------------------
# Phase 3: Memory subsystem.
# ---------------------------------------------------------------------------


class MemoryKind(str, enum.Enum):
    short_term = "short_term"   # conversation buffer, expires
    episodic = "episodic"       # raw interaction record
    semantic = "semantic"       # distilled fact / preference
    procedural = "procedural"   # approved workflow we can re-run


_EMBEDDING_DIM = get_settings().embedding_dim


class Memory(Base):
    """A domain-tagged memory with an optional embedding for similarity search.

    Domain isolation is enforced at the query layer in `app/memory/store.py`.
    Every search() call requires an explicit domain. Cross-domain reads
    require `cross_domain_search()` which audits each invocation.
    """

    __tablename__ = "memories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    domain: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    kind: Mapped[MemoryKind] = mapped_column(
        SAEnum(MemoryKind, name="memory_kind", native_enum=False),
        nullable=False,
        index=True,
    )

    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(_EMBEDDING_DIM))
    metadata_json: Mapped[dict] = mapped_column(
        "metadata", JSON, default=dict, nullable=False
    )

    # Provenance: which approval / audit row produced this memory.
    source_approval_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approvals.id", ondelete="SET NULL")
    )
    source_audit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("audit_log.id", ondelete="SET NULL")
    )

    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_memories_user_domain_kind", "user_id", "domain", "kind"),
        Index("ix_memories_user_domain_live", "user_id", "domain", "deleted_at"),
    )


class TopicDisable(Base):
    """Per-user opt-out: never write memories matching `pattern` in `domain`.

    Matching is a case-insensitive substring check against the memory text.
    A semantic (embedding-based) variant can replace this later without
    changing the API.
    """

    __tablename__ = "topic_disables"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    domain: Mapped[str] = mapped_column(String(64), nullable=False)
    pattern: Mapped[str] = mapped_column(String(255), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_topic_disables_user_domain", "user_id", "domain"),
    )


# ---------------------------------------------------------------------------
# Phase 4: Email Assistant.
# ---------------------------------------------------------------------------


class EmailCategory(str, enum.Enum):
    unclassified = "unclassified"
    urgent = "urgent"
    waiting_on_me = "waiting_on_me"
    fyi = "fyi"
    newsletter = "newsletter"
    suspicious = "suspicious"
    lead_inquiry = "lead_inquiry"
    internal = "internal"  # within Mullen Analytics
    personal = "personal"


class EmailDirection(str, enum.Enum):
    inbound = "inbound"
    outbound = "outbound"


class Email(Base):
    """Mirror of one external email message.

    Idempotent on (source='gmail', external_id=raw['id']).
    Body text is stored locally so the Email Assistant can operate offline
    after the initial sync.
    """

    __tablename__ = "emails"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    domain: Mapped[str] = mapped_column(
        String(64), nullable=False, default="personal", index=True
    )

    source: Mapped[str] = mapped_column(String(32), nullable=False, default="gmail")
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String(255), index=True)
    direction: Mapped[EmailDirection] = mapped_column(
        SAEnum(EmailDirection, name="email_direction", native_enum=False),
        default=EmailDirection.inbound,
        nullable=False,
    )

    from_addr: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    to_addrs: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cc_addrs: Mapped[str] = mapped_column(Text, nullable=False, default="")
    subject: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    snippet: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    labels: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    # Local enrichment.
    category: Mapped[EmailCategory] = mapped_column(
        SAEnum(EmailCategory, name="email_category", native_enum=False),
        default=EmailCategory.unclassified,
        nullable=False,
        index=True,
    )
    urgency_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    is_scam: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    scam_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    scam_signals: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    raw: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    __table_args__ = (
        Index(
            "ix_emails_source_external", "source", "external_id", unique=True
        ),
        Index("ix_emails_user_received", "user_id", "received_at"),
        Index("ix_emails_user_category", "user_id", "category"),
    )


class EmailDraft(Base):
    """A locally-generated reply that has NOT been sent.

    Sending requires a separate Approval row (action_class=action.external_send)
    settled by the user. `sent_approval_id` is set when the user approves
    and the executor calls Gmail's send endpoint.
    """

    __tablename__ = "email_drafts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    email_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("emails.id", ondelete="SET NULL")
    )

    to_addrs: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cc_addrs: Mapped[str] = mapped_column(Text, nullable=False, default="")
    subject: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    generated_by: Mapped[str] = mapped_column(String(64), nullable=False, default="email_assistant")
    model: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    sent_approval_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approvals.id", ondelete="SET NULL")
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_email_drafts_user_email", "user_id", "email_id"),
    )


# ---------------------------------------------------------------------------
# Phase 5: Project Manager + Business Development.
# ---------------------------------------------------------------------------


class ProjectStatus(str, enum.Enum):
    proposal = "proposal"   # not yet won; in pursuit
    active = "active"
    paused = "paused"
    won = "won"             # closed, delivered
    lost = "lost"           # didn't win the work
    archived = "archived"


class Vertical(str, enum.Enum):
    healthcare = "healthcare"
    ems = "ems"
    fire = "fire"
    drone = "drone"
    ai_consulting = "ai_consulting"
    school = "school"
    other = "other"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    domain: Mapped[str] = mapped_column(
        String(64), nullable=False, default="business", index=True
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    client: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    vertical: Mapped[Vertical] = mapped_column(
        SAEnum(Vertical, name="project_vertical", native_enum=False),
        default=Vertical.other,
        nullable=False,
        index=True,
    )
    status: Mapped[ProjectStatus] = mapped_column(
        SAEnum(ProjectStatus, name="project_status", native_enum=False),
        default=ProjectStatus.active,
        nullable=False,
        index=True,
    )
    priority: Mapped[int] = mapped_column(default=3, nullable=False)  # 1=top..5=low

    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    value_estimate: Mapped[float] = mapped_column(default=0.0, nullable=False)
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    target_end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    notes: Mapped[list[ProjectNote]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_projects_user_status", "user_id", "status"),
        Index("ix_projects_user_slug", "user_id", "slug", unique=True),
    )


class ProjectNoteKind(str, enum.Enum):
    log = "log"
    decision = "decision"
    risk = "risk"
    blocker = "blocker"
    win = "win"


class ProjectNote(Base):
    __tablename__ = "project_notes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[ProjectNoteKind] = mapped_column(
        SAEnum(ProjectNoteKind, name="project_note_kind", native_enum=False),
        default=ProjectNoteKind.log,
        nullable=False,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    project: Mapped[Project] = relationship(back_populates="notes")

    __table_args__ = (
        Index("ix_project_notes_project_created", "project_id", "created_at"),
    )


class OpportunityKind(str, enum.Enum):
    grant = "grant"
    rfp = "rfp"
    partnership = "partnership"
    cold_inbound = "cold_inbound"
    referral = "referral"
    other = "other"


class OpportunityStatus(str, enum.Enum):
    watching = "watching"
    researching = "researching"
    applying = "applying"
    submitted = "submitted"
    won = "won"
    lost = "lost"
    dropped = "dropped"


class Opportunity(Base):
    __tablename__ = "opportunities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    domain: Mapped[str] = mapped_column(String(64), nullable=False, default="business")

    title: Mapped[str] = mapped_column(String(512), nullable=False)
    agency_or_company: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    kind: Mapped[OpportunityKind] = mapped_column(
        SAEnum(OpportunityKind, name="opportunity_kind", native_enum=False),
        default=OpportunityKind.other,
        nullable=False,
        index=True,
    )
    vertical: Mapped[Vertical] = mapped_column(
        SAEnum(Vertical, name="opportunity_vertical", native_enum=False),
        default=Vertical.other,
        nullable=False,
        index=True,
    )
    status: Mapped[OpportunityStatus] = mapped_column(
        SAEnum(OpportunityStatus, name="opportunity_status", native_enum=False),
        default=OpportunityStatus.watching,
        nullable=False,
        index=True,
    )

    url: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    value_estimate: Mapped[float] = mapped_column(default=0.0, nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    source_email_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("emails.id", ondelete="SET NULL")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_opportunities_user_status", "user_id", "status"),
        Index("ix_opportunities_user_deadline", "user_id", "deadline"),
    )


class ProposalStatus(str, enum.Enum):
    draft = "draft"
    review = "review"
    submitted = "submitted"
    won = "won"
    lost = "lost"
    discarded = "discarded"


class Proposal(Base):
    """A proposal/RFP-response document.

    Either tied to a Project (a follow-on for an existing client) or to an
    Opportunity (a pursuit). Submitting the proposal externally requires a
    separate Approval — same pattern as EmailDraft.send.
    """

    __tablename__ = "proposals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL")
    )
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("opportunities.id", ondelete="SET NULL")
    )

    title: Mapped[str] = mapped_column(String(512), nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ProposalStatus] = mapped_column(
        SAEnum(ProposalStatus, name="proposal_status", native_enum=False),
        default=ProposalStatus.draft,
        nullable=False,
        index=True,
    )
    generated_by: Mapped[str] = mapped_column(String(64), nullable=False, default="business_development")
    model: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    submit_approval_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approvals.id", ondelete="SET NULL")
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_proposals_user_status", "user_id", "status"),
    )


# ---------------------------------------------------------------------------
# Phase 6: Marketing + Lead Generation.
# ---------------------------------------------------------------------------


class SocialPlatform(str, enum.Enum):
    linkedin = "linkedin"
    facebook = "facebook"
    x = "x"
    instagram = "instagram"
    blog = "blog"
    other = "other"


class SocialPostStatus(str, enum.Enum):
    draft = "draft"
    scheduled = "scheduled"
    published = "published"
    discarded = "discarded"


class SocialPost(Base):
    """A piece of social/marketing content.

    Posting externally requires `post_approval_id` to be settled (approved).
    Engagement metrics are paste-in initially; APIs come later per ROADMAP.
    """

    __tablename__ = "social_posts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    platform: Mapped[SocialPlatform] = mapped_column(
        SAEnum(SocialPlatform, name="social_platform", native_enum=False),
        default=SocialPlatform.linkedin,
        nullable=False,
        index=True,
    )
    vertical: Mapped[Vertical] = mapped_column(
        SAEnum(Vertical, name="social_vertical", native_enum=False),
        default=Vertical.other,
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[SocialPostStatus] = mapped_column(
        SAEnum(SocialPostStatus, name="social_post_status", native_enum=False),
        default=SocialPostStatus.draft,
        nullable=False,
        index=True,
    )

    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    post_approval_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approvals.id", ondelete="SET NULL")
    )

    engagement: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    generated_by: Mapped[str] = mapped_column(String(64), nullable=False, default="marketing")
    model: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_social_posts_user_status", "user_id", "status"),
        Index("ix_social_posts_user_scheduled", "user_id", "scheduled_for"),
    )


class LeadSource(str, enum.Enum):
    manual = "manual"
    inbound_email = "inbound_email"
    referral = "referral"
    event = "event"
    research = "research"
    other = "other"


class LeadStatus(str, enum.Enum):
    researched = "researched"
    contacted = "contacted"
    meeting = "meeting"
    proposal = "proposal"
    won = "won"
    lost = "lost"
    disqualified = "disqualified"


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    company: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    role: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    email: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    phone: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    vertical: Mapped[Vertical] = mapped_column(
        SAEnum(Vertical, name="lead_vertical", native_enum=False),
        default=Vertical.other,
        nullable=False,
        index=True,
    )
    source: Mapped[LeadSource] = mapped_column(
        SAEnum(LeadSource, name="lead_source", native_enum=False),
        default=LeadSource.manual,
        nullable=False,
    )
    status: Mapped[LeadStatus] = mapped_column(
        SAEnum(LeadStatus, name="lead_status", native_enum=False),
        default=LeadStatus.researched,
        nullable=False,
        index=True,
    )

    # Score 0..100 — higher = better fit for ICP.
    score: Mapped[int] = mapped_column(default=0, nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    source_email_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("emails.id", ondelete="SET NULL")
    )

    last_contacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_followup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_leads_user_status", "user_id", "status"),
        Index("ix_leads_user_followup", "user_id", "next_followup_at"),
    )


class OutreachChannel(str, enum.Enum):
    email = "email"
    linkedin = "linkedin"
    phone = "phone"
    sms = "sms"
    other = "other"


class OutreachStatus(str, enum.Enum):
    draft = "draft"
    sent = "sent"
    replied = "replied"
    discarded = "discarded"


class OutreachMessage(Base):
    """A drafted outbound message to a lead.

    Sending requires `sent_approval_id` to be approved.
    """

    __tablename__ = "outreach_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    )

    channel: Mapped[OutreachChannel] = mapped_column(
        SAEnum(OutreachChannel, name="outreach_channel", native_enum=False),
        default=OutreachChannel.email,
        nullable=False,
    )
    subject: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[OutreachStatus] = mapped_column(
        SAEnum(OutreachStatus, name="outreach_status", native_enum=False),
        default=OutreachStatus.draft,
        nullable=False,
        index=True,
    )

    sent_approval_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approvals.id", ondelete="SET NULL")
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    generated_by: Mapped[str] = mapped_column(String(64), nullable=False, default="lead_generation")
    model: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_outreach_lead_created", "lead_id", "created_at"),
    )


# ---------------------------------------------------------------------------
# Phase 7: Computer Control (gated). See docs/SECURITY.md.
# ---------------------------------------------------------------------------


class ComputerActionType(str, enum.Enum):
    launch_app = "launch_app"
    run_script = "run_script"
    file_search = "file_search"
    file_list = "file_list"
    file_read = "file_read"
    playwright_open = "playwright_open"


class ComputerActionStatus(str, enum.Enum):
    pending_approval = "pending_approval"
    executed = "executed"
    failed = "failed"
    blocked = "blocked"


class AllowedApp(Base):
    """An application the Computer Control agent is permitted to launch.

    The CRUD endpoints for this table are admin-only and the agent never
    auto-adds rows. New apps are added by a human with typed confirmation.
    """

    __tablename__ = "allowed_apps"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    args_template: Mapped[str] = mapped_column(Text, nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # If hash_required is True, the executable's sha256 must match expected_hash
    # at every launch. Useful for scripts/wrappers; usually skipped for stock OS apps.
    hash_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expected_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_allowed_apps_user_name", "user_id", "name", unique=True),
    )


class AllowedScript(Base):
    """A script the Computer Control agent is permitted to run.

    Hash is REQUIRED and re-verified immediately before each execution.
    If the file on disk has changed since the row was created, the run is blocked
    with a `blocked` action log row.
    """

    __tablename__ = "allowed_scripts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    interpreter: Mapped[str] = mapped_column(String(255), nullable=False, default="")  # e.g., "python", "powershell"
    args_template: Mapped[str] = mapped_column(Text, nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sha256_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_allowed_scripts_user_name", "user_id", "name", unique=True),
    )


class ComputerActionLog(Base):
    """Record of every computer-control action attempted.

    Separate from `audit_log` because we want per-action stdout/return-code
    visibility for debugging, while keeping the security audit log minimal.
    """

    __tablename__ = "computer_action_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    action_type: Mapped[ComputerActionType] = mapped_column(
        SAEnum(ComputerActionType, name="computer_action_type", native_enum=False),
        nullable=False,
        index=True,
    )
    target: Mapped[str] = mapped_column(Text, nullable=False)
    args: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[ComputerActionStatus] = mapped_column(
        SAEnum(ComputerActionStatus, name="computer_action_status", native_enum=False),
        default=ComputerActionStatus.pending_approval,
        nullable=False,
        index=True,
    )

    return_code: Mapped[int | None] = mapped_column()
    stdout_excerpt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    stderr_excerpt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    blocked_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")

    approval_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approvals.id", ondelete="SET NULL")
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_computer_action_log_user_started", "user_id", "started_at"),
    )


# ---------------------------------------------------------------------------
# Phase 5b: Grant Writer.
# ---------------------------------------------------------------------------


class OrgType(str, enum.Enum):
    small_business = "small_business"
    sole_prop = "sole_prop"
    nonprofit_501c3 = "nonprofit_501c3"
    state_local_govt = "state_local_govt"
    tribal_govt = "tribal_govt"
    academic = "academic"
    hospital = "hospital"
    fire_dept = "fire_dept"
    ems_agency = "ems_agency"
    other = "other"


class OrgProfile(Base):
    """The applicant organization. Used for eligibility screening + boilerplate."""

    __tablename__ = "org_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    legal_name: Mapped[str] = mapped_column(String(255), nullable=False)
    short_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    org_type: Mapped[OrgType] = mapped_column(
        SAEnum(OrgType, name="org_type", native_enum=False),
        default=OrgType.small_business,
        nullable=False,
    )

    ein: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    uei: Mapped[str] = mapped_column(String(32), nullable=False, default="")  # SAM.gov UEI
    duns: Mapped[str] = mapped_column(String(32), nullable=False, default="")  # legacy
    naics_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    sam_status: Mapped[str] = mapped_column(String(32), nullable=False, default="")  # active|expired|none
    sam_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    founded_year: Mapped[int | None] = mapped_column()
    address: Mapped[str] = mapped_column(Text, nullable=False, default="")
    contact_email: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    contact_phone: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    website: Mapped[str] = mapped_column(String(512), nullable=False, default="")

    capabilities_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    boilerplate: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    # boilerplate keys (free-form): mission, history, past_performance, key_personnel, ...

    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_org_profiles_user_legal_name", "user_id", "legal_name", unique=True),
    )


class FunderType(str, enum.Enum):
    federal_health = "federal_health"           # NIH, SAMHSA, HRSA, AHRQ, CDC
    federal_public_safety = "federal_public_safety"  # FEMA AFG, DOJ COPS, BJA
    federal_other = "federal_other"             # DOE, NSF, USDA, etc.
    state = "state"                             # state EMS / fire / health office
    local = "local"                             # county/municipal
    foundation = "foundation"
    corporate = "corporate"
    other = "other"


class GrantApplicationStatus(str, enum.Enum):
    intake = "intake"                  # opportunity logged, not yet started
    eligibility = "eligibility"        # screening in progress / blocked
    drafting = "drafting"              # sections being written
    review = "review"                  # internal review before submission
    ready = "ready"                    # bundle assembled, awaiting approval to submit
    submitted = "submitted"
    awarded = "awarded"
    declined = "declined"
    withdrawn = "withdrawn"


class EligibilityVerdict(str, enum.Enum):
    pending = "pending"
    pass_ = "pass"          # 'pass' is a Python keyword; trailing underscore in the member
    fail = "fail"
    needs_review = "needs_review"
    skipped = "skipped"     # user opted to skip the check


class GrantApplication(Base):
    """A grant we're applying for.

    Linked to an existing Opportunity (the BD agent's watch list) when the
    application originates from one — but a grant can also be created
    directly from a NOFO URL without an Opportunity row.
    """

    __tablename__ = "grant_applications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    org_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_profiles.id", ondelete="SET NULL")
    )
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("opportunities.id", ondelete="SET NULL")
    )

    funder_type: Mapped[FunderType] = mapped_column(
        SAEnum(FunderType, name="funder_type", native_enum=False),
        nullable=False,
        index=True,
    )
    funder_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    mechanism_code: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # e.g., "R01", "AFG-O", "HRSA-25-XXX", "SAMHSA-SM-25-XXX"
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    abstract: Mapped[str] = mapped_column(Text, nullable=False, default="")
    requested_amount: Mapped[float] = mapped_column(default=0.0, nullable=False)
    period_months: Mapped[int] = mapped_column(default=0, nullable=False)

    status: Mapped[GrantApplicationStatus] = mapped_column(
        SAEnum(GrantApplicationStatus, name="grant_application_status", native_enum=False),
        default=GrantApplicationStatus.intake,
        nullable=False,
        index=True,
    )

    eligibility_verdict: Mapped[EligibilityVerdict] = mapped_column(
        SAEnum(EligibilityVerdict, name="eligibility_verdict", native_enum=False),
        default=EligibilityVerdict.pending,
        nullable=False,
    )
    eligibility_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    nofo_url: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    nofo_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    bundle_path: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    # When the agent assembles, this points to the local folder under an
    # allowed root (verified via app.integrations.computer.safe_path).
    submission_approval_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approvals.id", ondelete="SET NULL")
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    sections: Mapped[list[GrantSection]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="GrantSection.order_index",
    )
    attachments: Mapped[list[GrantAttachment]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_grant_apps_user_status", "user_id", "status"),
        Index("ix_grant_apps_user_deadline", "user_id", "deadline"),
    )


class GrantSectionStatus(str, enum.Enum):
    not_started = "not_started"
    draft = "draft"
    review = "review"
    ready = "ready"
    skipped = "skipped"


class GrantSection(Base):
    """One section of a grant narrative.

    `kind` is a stable identifier (e.g., 'specific_aims', 'needs_statement',
    'budget_narrative') that lets agents look up the right prompt template.
    """

    __tablename__ = "grant_sections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("grant_applications.id", ondelete="CASCADE"), nullable=False
    )

    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    body_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    order_index: Mapped[int] = mapped_column(default=0, nullable=False)

    status: Mapped[GrantSectionStatus] = mapped_column(
        SAEnum(GrantSectionStatus, name="grant_section_status", native_enum=False),
        default=GrantSectionStatus.not_started,
        nullable=False,
        index=True,
    )
    word_limit: Mapped[int] = mapped_column(default=0, nullable=False)
    word_count: Mapped[int] = mapped_column(default=0, nullable=False)

    generated_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    application: Mapped[GrantApplication] = relationship(back_populates="sections")

    __table_args__ = (
        Index("ix_grant_sections_app_kind", "application_id", "kind", unique=True),
        Index("ix_grant_sections_app_order", "application_id", "order_index"),
    )


class GrantAttachment(Base):
    """A file that must accompany the application (biosketch, LOI, budget workbook, ...).

    `file_path`, if set, points at a file inside an allow-listed root
    (verified by app.integrations.computer.safe_path at write time).
    """

    __tablename__ = "grant_attachments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("grant_applications.id", ondelete="CASCADE"), nullable=False
    )

    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    # e.g., 'biosketch', 'letter_of_support', 'budget_workbook',
    # 'indirect_cost_rate_agreement', 'sf424', 'project_abstract_form', ...
    label: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    present: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    application: Mapped[GrantApplication] = relationship(back_populates="attachments")

    __table_args__ = (
        Index("ix_grant_attachments_app_kind", "application_id", "kind"),
    )


# ---------------------------------------------------------------------------
# Phase 8: Backups.
# ---------------------------------------------------------------------------


class BackupKind(str, enum.Enum):
    full = "full"          # pg_dump of the whole DB
    schema_only = "schema_only"
    data_only = "data_only"


class BackupStatus(str, enum.Enum):
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"
    restored_from = "restored_from"  # tagged after a successful restore reads this row


class BackupRecord(Base):
    """Metadata for an encrypted backup. The file itself lives on disk
    inside an allow-listed root; the key lives in keyring (never in the DB).
    """

    __tablename__ = "backup_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    kind: Mapped[BackupKind] = mapped_column(
        SAEnum(BackupKind, name="backup_kind", native_enum=False),
        default=BackupKind.full,
        nullable=False,
    )
    status: Mapped[BackupStatus] = mapped_column(
        SAEnum(BackupStatus, name="backup_status", native_enum=False),
        default=BackupStatus.in_progress,
        nullable=False,
        index=True,
    )
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_size: Mapped[int] = mapped_column(default=0, nullable=False)
    sha256_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    encryption_alg: Mapped[str] = mapped_column(
        String(32), nullable=False, default="AES-256-GCM"
    )
    key_id: Mapped[str] = mapped_column(String(64), nullable=False, default="backup_master_key")
    failure_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_backup_records_user_started", "user_id", "started_at"),
    )
