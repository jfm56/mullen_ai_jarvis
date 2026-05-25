"""SQLAlchemy models.

Phase 1: User, AuditLog, Approval (security spine).
Phase 2: Task, Reminder, CalendarEvent, OAuthAccount (Personal Assistant).
Phase 3: Memory, TopicDisable (memory subsystem with domain isolation).
Phase 4: Email, EmailDraft (Email Assistant).
Phase 5: Project, ProjectNote, Opportunity, Proposal (Project Mgr + BD).
Phase 6+: contacts, leads.
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
