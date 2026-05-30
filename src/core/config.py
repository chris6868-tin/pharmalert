"""Application configuration — all settings from environment variables."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class _Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Telegram ──────────────────────────────────────────────────────────────
    telegram_bot_token: str = ""

    # ── Gemini AI ─────────────────────────────────────────────────────────────
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash-lite"

    # ── DAV Scraper ──────────────────────────────────────────────────────────
    dav_base_url: str = "https://dav.gov.vn"
    dav_listings_url: str = (
        "https://dav.gov.vn/thong-tin-xu-ly-vi-pham-cn5.html"
    )
    dav_registration_url: str = (
        "https://dav.gov.vn/dang-ki-thuoc-cn6.html"
    )
    max_pdf_size_mb: int = 10
    http_timeout_seconds: int = 30
    http_max_retries: int = 3

    # ── International sources ────────────────────────────────────────────────
    # Khi False: chỉ scrape DAV (vi phạm + đăng ký thuốc)
    # Khi True: scrape thêm FDA, EMA, PRAC
    enable_international_sources: bool = False

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./data/bot.db"

    @property
    def resolved_database_url(self) -> str:
        """Return database URL with correct async driver prefix.
        
        Auto-corrects common mistakes:
          postgres://...          → postgresql+asyncpg://...  (Supabase/Heroku style)
          postgresql://...        → postgresql+asyncpg://...  (forgot +asyncpg)
          sqlite:///...           → sqlite+aiosqlite:///...   (forgot +aiosqlite)
        """
        url = self.database_url
        if url.startswith("postgres://"):
            # Heroku/Supabase style — add correct driver
            return "postgresql+asyncpg://" + url[len("postgres://"):]
        if url.startswith("postgresql://"):
            # Missing +asyncpg driver
            return "postgresql+asyncpg://" + url[len("postgresql://"):]
        if url.startswith("sqlite://") and "+aiosqlite" not in url:
            # Missing +aiosqlite driver
            return "sqlite+aiosqlite://" + url[len("sqlite://"):]
        return url

    # ── Scheduler ─────────────────────────────────────────────────────────────
    check_interval_minutes: int = 720          # scrape mỗi 30 phút
    notification_times: str = "12:00,17:00"    # danh sách giờ gửi thông báo (HH:MM, cách nhau bằng dấu phẩy)
    timezone: str = "Asia/Ho_Chi_Minh"

    # ── Deployment ────────────────────────────────────────────────────────────
    # PORT được Render tự động set. Health check server lắng nghe trên cổng này.
    # Ở máy local không cần set (bot dùng polling, không cần HTTP server).
    port: int = 8080

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # ── Derived ───────────────────────────────────────────────────────────────
    @property
    def max_pdf_size_bytes(self) -> int:
        return self.max_pdf_size_mb * 1024 * 1024

    @property
    def data_dir(self) -> Path:
        path = Path("data")
        path.mkdir(exist_ok=True)
        return path

    @property
    def db_path(self) -> Path:
        url = self.database_url
        if url.startswith("sqlite"):
            # Extract path from sqlite+aiosqlite:///path or sqlite:///path
            path_str = url.split("///", 1)[-1]
            path = Path(path_str)
            if path.is_absolute():
                return path
            return path.resolve()
        return self.data_dir / "bot.db"

    def validate(self) -> None:
        """Validate required configuration. Raise ValueError if invalid."""
        if not self.telegram_bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required")
        if not self.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is required")

        for slot in self.notification_times.split(","):
            slot = slot.strip()
            if not slot:
                continue
            parts = slot.split(":")
            if len(parts) != 2:
                raise ValueError(
                    f"Invalid notification slot '{slot}' in NOTIFICATION_TIMES. "
                    "Expected HH:MM format (e.g. 12:00, 17:00)"
                )
            try:
                h, m = int(parts[0]), int(parts[1])
                if not (0 <= h <= 23) or not (0 <= m <= 59):
                    raise ValueError()
            except ValueError:
                raise ValueError(
                    f"Invalid notification slot '{slot}' in NOTIFICATION_TIMES. "
                    "Hour must be 0–23, minute must be 0–59."
                )

    def get_notification_hours(self) -> list[tuple[int, int]]:
        """Parse NOTIFICATION_TIMES into list of (hour, minute) tuples."""
        result: list[tuple[int, int]] = []
        for slot in self.notification_times.split(","):
            slot = slot.strip()
            if not slot:
                continue
            h, m = slot.split(":")
            result.append((int(h), int(m)))
        return result


# ── Global singleton ──────────────────────────────────────────────────────────
_settings: _Settings | None = None


def get_settings() -> _Settings:
    global _settings
    if _settings is None:
        _settings = _Settings()
        _settings.validate()
    return _settings


def reload_settings() -> _Settings:
    """Force-reload settings (useful in tests)."""
    global _settings
    _settings = _Settings()
    _settings.validate()
    return _settings
