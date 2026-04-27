from sqlalchemy import Column, Integer, ForeignKey, Text, DateTime, JSON, Enum, String, ARRAY, Boolean, Index
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from app.database.base import Base


# Enum for models -----------------------------------------

class AuthProvider(enum.Enum):
    EMAIL = "email"
    GOOGLE = "google"
    APPLE = "apple"

class SubscriptionPlan(enum.Enum):
    TRIAL = "trial"
    MONTHLY = "monthly"

class SubscriptionStatus(enum.Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELED = "canceled"

class MessageRole(enum.Enum):
    USER = "user"
    AGENT = "agent"
    
class MeditationStatus(enum.Enum):
    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


class SupportIssueStatus(enum.Enum):
    OPEN = "open"
    CLOSED = "closed"


class UserRole(enum.Enum):
    USER = "user"
    ADMIN = "admin"
    

# Database models ------------------------------------------

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String)
    auth_provider = Column(Enum(AuthProvider), nullable=False)
    role = Column(Enum(UserRole), nullable=False, default=UserRole.USER)
    google_id = Column(String, unique=True, index=True, nullable=True)
    apple_id = Column(String, unique=True, index=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    preferences = relationship("UserPreferences", back_populates="user", uselist=False, cascade="all, delete-orphan", passive_deletes=True)
    subscription = relationship("Subscription", back_populates="user", uselist=False, cascade="all, delete-orphan", passive_deletes=True)
    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan", passive_deletes=True)
    support_issues = relationship(
        "SupportIssue",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="SupportIssue.user_id",
    )


class UserPreferences(Base):
    __tablename__ = "user_preferences"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    theme = Column(String, default="system")
    language = Column(String, default="English")
    voice_volume = Column(String, default="+6.0")
    bg_volume = Column(String, default="0.35")
    notifications = Column(JSON, default={"recommendations": True, "promotional": True, "bedtime": True})
    
    user = relationship("User", back_populates="preferences")


class Subscription(Base):
    __tablename__ = "subscriptions"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    status = Column(Enum(SubscriptionStatus), default=SubscriptionStatus.ACTIVE)
    plan_type = Column(Enum(SubscriptionPlan), default=SubscriptionPlan.TRIAL)
    apple_original_transaction_id = Column(String, unique=True, index=True, nullable=True)
    start_date = Column(DateTime, default=datetime.utcnow)
    end_date = Column(DateTime, nullable=True)
    
    user = relationship("User", back_populates="subscription")


class OTP(Base):
    __tablename__ = "otps"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, index=True, nullable=False)
    code = Column(String, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Session(Base):
    __tablename__ = "sessions"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="sessions")
    messages = relationship("Message", back_populates="session", cascade="all, delete-orphan", passive_deletes=True)
    meditations = relationship("Meditation", back_populates="session", cascade="all, delete-orphan", passive_deletes=True)


class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    role = Column(Enum(MessageRole), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("Session", back_populates="messages")


class Meditation(Base):
    __tablename__ = "meditations"
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=True)
    summary = Column(Text)
    script = Column(JSON)
    audio_blocks = Column(JSON)
    status = Column(Enum(MeditationStatus), default=MeditationStatus.PENDING)
    progress = Column(Integer, default=0)
    is_liked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    session = relationship("Session", back_populates="meditations")


class Music(Base):
    __tablename__ = "music"
    id = Column(Integer, primary_key=True, index=True)
    display_name = Column(String, nullable=False)
    path = Column(String, unique=True, nullable=False)
    category = Column(String, nullable=False)
    mood = Column(ARRAY(String), nullable=False)
    description = Column(Text)
    tags = Column(ARRAY(String))


class SupportIssue(Base):
    __tablename__ = "support_issues"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    description = Column(Text, nullable=False)
    category = Column(String, nullable=True)
    meta = Column("metadata", JSON, nullable=True)
    status = Column(Enum(SupportIssueStatus), nullable=False, default=SupportIssueStatus.OPEN)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    closed_at = Column(DateTime, nullable=True)
    closed_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    user = relationship("User", back_populates="support_issues", foreign_keys=[user_id])
    closed_by_user = relationship("User", foreign_keys=[closed_by_user_id])

    __table_args__ = (Index("ix_support_issues_user_id_created_at", "user_id", "created_at"),)
