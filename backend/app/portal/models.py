from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, LargeBinary, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class PortalBase(DeclarativeBase):
    pass


class PublishedResult(PortalBase):
    __tablename__ = "published_results"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    permissions: Mapped[dict] = mapped_column(JSON)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload: Mapped[bytes] = mapped_column(LargeBinary)
    signature: Mapped[str] = mapped_column(String(64))
    access_count: Mapped[int] = mapped_column(Integer, default=0)


class RateBucket(PortalBase):
    __tablename__ = "portal_rate_buckets"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    window: Mapped[int] = mapped_column(Integer, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False)
