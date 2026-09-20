import enum
from datetime import datetime, timezone

from sqlalchemy import (JSON, DateTime, ForeignKey, Integer, String, Text,
                        UniqueConstraint, Index)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from .database import Base


class UTCDateTime(TypeDecorator):
    """Stores naive UTC, always returns timezone-aware UTC (works on SQLite + Postgres)."""
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return None if value is None else value.replace(tzinfo=timezone.utc)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Role(str, enum.Enum):
    owner = "owner"
    admin = "admin"
    staff = "staff"
    viewer = "viewer"


ROLE_RANK = {Role.viewer: 1, Role.staff: 2, Role.admin: 3, Role.owner: 4}


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class RefreshToken(Base):
    """One row per issued refresh token. `family_id` links a rotation chain so that
    re-use of an already-rotated token revokes the whole family (theft detection)."""
    __tablename__ = "refresh_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    jti: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    family_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    revoked: Mapped[bool] = mapped_column(default=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "org_id", name="uq_membership"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    role: Mapped[Role] = mapped_column(default=Role.viewer)
    user: Mapped[User] = relationship()


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    venue: Mapped[str] = mapped_column(String(200), default="")
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime)
    ends_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|published|cancelled
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    ticket_types: Mapped[list["TicketType"]] = relationship(
        back_populates="event", cascade="all, delete-orphan", order_by="TicketType.id")


class TicketType(Base):
    __tablename__ = "ticket_types"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    price_cents: Mapped[int] = mapped_column(Integer, default=0)
    capacity: Mapped[int] = mapped_column(Integer)
    sold: Mapped[int] = mapped_column(Integer, default=0)
    event: Mapped[Event] = relationship(back_populates="ticket_types")


class Registration(Base):
    __tablename__ = "registrations"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    ticket_type_id: Mapped[int] = mapped_column(ForeignKey("ticket_types.id"))
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    attendee_name: Mapped[str] = mapped_column(String(120))
    attendee_email: Mapped[str] = mapped_column(String(255), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    total_cents: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|confirmed|cancelled
    checked_in_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    event: Mapped[Event] = relationship()
    ticket_type: Mapped[TicketType] = relationship()
    __table_args__ = (Index("ix_reg_org_event", "org_id", "event_id"),)


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    registration_id: Mapped[int] = mapped_column(ForeignKey("registrations.id", ondelete="CASCADE"), index=True)
    provider_ref: Mapped[str] = mapped_column(String(64), unique=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="requires_payment")  # requires_payment|succeeded|failed
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ProcessedWebhook(Base):
    """Idempotency ledger: each provider event id is handled at most once."""
    __tablename__ = "processed_webhooks"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(String(80), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_label: Mapped[str] = mapped_column(String(255), default="system")
    action: Mapped[str] = mapped_column(String(80))
    entity: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[int | None] = mapped_column(nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
