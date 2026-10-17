"""
Accounts and sessions, app settings, and the usage log of model calls.
"""
from datetime import datetime
from uuid import uuid4
from sqlalchemy import (
    Column, String, DateTime, Integer, Float, Boolean, ForeignKey, func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship

from athena.core.models.base import Base


class AppSetting(Base):
    """User-configurable key/value settings persisted in the database."""
    __tablename__ = "app_settings"

    key = Column(String, primary_key=True)
    value = Column(String, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class User(Base):
    """An account. The first one is the admin; the admin creates the rest (there is no public sign-up)."""
    __tablename__ = "users"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    email = Column(String, unique=True, nullable=False)  # stored lower-case
    display_name = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)       # argon2id
    role = Column(String, nullable=False, default="user")  # admin | user
    is_active = Column(Boolean, nullable=False, default=True)
    must_change_password = Column(Boolean, nullable=False, default=False)  # set by temporary passwords
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    onboarded_at = Column(DateTime(timezone=True), nullable=True)  # finished or skipped the setup guide


class UserSession(Base):
    """A login. The browser holds the token in an httpOnly cookie; only its SHA-256 is stored."""
    __tablename__ = "user_sessions"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)  # rolling: pushed back while the session is used
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    user_agent = Column(String, nullable=True)

    user = relationship("User")


class UsageEvent(Base):
    """Model calls: who asked (none for background work), for what, and their tokens and cost.

    Append-only, so a month's spend survives users deleting their questions and checks. Cost is priced when the
    call is made, at the prices set then.
    """
    __tablename__ = "usage_events"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    user_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    feature = Column(String, nullable=False)         # qa | map_qa | idea_check | lit_review | summary | ...
    kind = Column(String, nullable=False, default="chat")  # chat | embed
    model = Column(String, nullable=False, default="")
    calls = Column(Integer, nullable=False, default=1)  # background calls are summed into one row a minute
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    cost_usd = Column(Float, nullable=False, default=0.0)
