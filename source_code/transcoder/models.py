from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from transcoder.db import Base


def utcnow() -> dt.datetime:
    # Naive UTC to match SQLite's DateTime columns, which drop tzinfo on
    # read-back; keeps comparisons consistent (no mixed aware/naive errors).
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def episode_exclusion_key(title: str, season: int | str, episode: int | str) -> str:
    return f"{title}|{season}|{episode}"


def movie_exclusion_key(title: str) -> str:
    return title


class MediaItem(Base):
    __tablename__ = "media_item"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_media_source_external"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(16))
    external_id: Mapped[str] = mapped_column(String(64))
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(512))
    season: Mapped[int | None] = mapped_column(Integer, nullable=True)
    episode: Mapped[int | None] = mapped_column(Integer, nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remote_path: Mapped[str] = mapped_column(String(1024), default="")
    codec: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolution: Mapped[int] = mapped_column(Integer, default=0)
    quality: Mapped[str | None] = mapped_column(String(128), nullable=True)
    languages: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_h265: Mapped[bool] = mapped_column(Boolean, default=False)
    eligibility: Mapped[str] = mapped_column(String(32), default="needs_transcode")
    last_scanned_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    jobs: Mapped[list["Job"]] = relationship(back_populates="media_item")


class Job(Base):
    __tablename__ = "job"

    id: Mapped[int] = mapped_column(primary_key=True)
    media_item_id: Mapped[int] = mapped_column(ForeignKey("media_item.id"))
    state: Mapped[str] = mapped_column(String(32), default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    preset: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    original_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reduction_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    output_filename: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    log_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)

    media_item: Mapped["MediaItem"] = relationship(back_populates="jobs")


class Exclusion(Base):
    __tablename__ = "exclusion"
    __table_args__ = (
        UniqueConstraint("source", "key", name="uq_exclusion_source_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(16))
    key: Mapped[str] = mapped_column(String(640))
    reason: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


class Setting(Base):
    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
