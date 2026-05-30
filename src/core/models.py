"""SQLAlchemy ORM models for the bot database."""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
    is_active: Mapped[bool] = mapped_column(default=True)
    # JSON list of enabled source keys, e.g. ["dav_violation","dav_registration","fda_enforcement","ema"]
    enabled_sources: Mapped[str | None] = mapped_column(Text, nullable=True)

    notifications: Mapped[list["Notification"]] = relationship(
        back_populates="subscription", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_subscriptions_chat_active", "chat_id", "is_active"),)

    # ── Source helpers ──────────────────────────────────────────────────────
    def get_enabled_sources(self) -> set[str]:
        """Return set of enabled source keys for this subscriber."""
        if not self.enabled_sources:
            return {"dav_violation", "dav_registration"}
        try:
            return set(json.loads(self.enabled_sources))
        except Exception:
            return {"dav_violation", "dav_registration"}

    def set_enabled_sources(self, sources: set[str]) -> None:
        self.enabled_sources = json.dumps(sorted(sources))


class Announcement(Base):
    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(30), default="dav", index=True)
    external_id: Mapped[str] = mapped_column(String(500), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(1000))
    url: Mapped[str] = mapped_column(String(2000))
    published_date: Mapped[str | None] = mapped_column(String(50), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    notifications: Mapped[list["Notification"]] = relationship(
        back_populates="announcement", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_announcements_source_published", "source", "published_date"),
        Index("ix_announcements_processed", "processed_at"),
        Index("ix_announcements_source_processed", "source", "processed_at"),
    )


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    subscription_id: Mapped[int] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="CASCADE")
    )
    announcement_id: Mapped[int] = mapped_column(
        ForeignKey("announcements.id", ondelete="CASCADE")
    )
    sent_at: Mapped[datetime] = mapped_column(server_default=func.now())
    status: Mapped[str] = mapped_column(String(20), default="sent")

    subscription: Mapped["Subscription"] = relationship(back_populates="notifications")
    announcement: Mapped["Announcement"] = relationship(back_populates="notifications")

    __table_args__ = (
        Index(
            "ix_notifications_sub_ann",
            "subscription_id",
            "announcement_id",
            unique=True,
        ),
    )
