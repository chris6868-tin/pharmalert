"""APScheduler background jobs for periodic scraping and daily notifications."""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING

import httpx
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from ..core.database import get_session
from ..core.exceptions import GeminiQuotaError, ScraperError
from ..core.logging import get_logger
from ..core.models import Announcement, Notification, Subscription
from ..news import (
    EMAFetcher, EMAShortageFetcher, FDAApprovalFetcher,
    FDAEnforcementFetcher, FDAShortageFetcher, PRACFetcher,
)

if TYPE_CHECKING:
    from ..core.config import _Settings
    from ..scraper import DAVFetcher
    from ..summarizer import GeminiSummarizer

logger = get_logger("scheduler")

# ── Source emoji & label maps ──────────────────────────────────────────────────

_SOURCE_META = {
    # DAV Vietnam
    "dav_violation":    ("🇻🇳", "DAV Việt Nam — Vi phạm"),
    "dav_registration": ("🇻🇳", "DAV Việt Nam — Đăng ký thuốc"),
    # FDA USA
    "fda_enforcement":   ("🇺🇸", "FDA Drug Recall"),
    "fda_shortage":     ("⚠️",  "FDA Drug Shortage"),
    "fda_approval":     ("✅",  "FDA New Approval"),
    "medwatch":         ("🇺🇸", "FDA MedWatch"),
    # EMA Europe
    "ema":              ("🇪🇺", "EMA News"),
    "ema_shortage":     ("🚫",  "EMA Medicine Shortage"),
    "prac":            ("⚕️",  "EMA PRAC Signals"),
}

# ── Job 1: DAV scrape + Gemini summarize ─────────────────────────────────────

async def _scrape_dav(
    settings: _Settings,
    fetcher: DAVFetcher,
    summarizer: GeminiSummarizer,
) -> list[Announcement]:
    """Scrape new DAV entries (violations + registration), download PDFs, summarize, save to DB."""
    if not settings.enable_dav_scraping:
        logger.info("DAV scraping disabled — skipping scrape")
        return []

    from ..scraper import DAVScraperPipeline

    # Scrape both DAV sources — violations and drug registrations
    dav_sources = [
        ("dav_violation",    settings.dav_listings_url),
        ("dav_registration", settings.dav_registration_url),
    ]

    all_processed: list[Announcement] = []

    async with get_session() as session:
        for source_key, url in dav_sources:
            pipeline = DAVScraperPipeline(fetcher, url, source_key=source_key)
            try:
                result = await pipeline.run(session)
                if not result.announcements:
                    logger.info(f"DAV [{source_key}]: No new entries found")
                else:
                    logger.info(f"DAV [{source_key}]: {result.new_entries} new, {result.skipped_entries} skipped, {result.failed_entries} failed")
                    for announcement in result.announcements:
                        if source_key == "dav_registration":
                            # For drug registrations, we don't need summaries — only title and link.
                            announcement.processed_at = datetime.utcnow()
                            all_processed.append(announcement)
                            continue

                        if not announcement.url.lower().endswith(".pdf"):
                            continue
                        try:
                            pdf_bytes = await fetcher.fetch_pdf_bytes(announcement.url)
                            summary = await summarizer.summarize_pdf_bytes(pdf_bytes)
                            announcement.summary = summary
                            announcement.processed_at = datetime.utcnow()
                            all_processed.append(announcement)
                            logger.info(f"DAV [{source_key}] processed: {announcement.external_id} ({len(summary)} chars)")
                            await asyncio.sleep(5)  # rate-limit: avoid Gemini quota
                        except GeminiQuotaError as e:
                            logger.warning(f"DAV [{source_key}] Gemini quota exceeded, stopping summarize: {e}")
                            break
                        except Exception as e:
                            logger.error(f"DAV [{source_key}] failed {announcement.external_id}: {e}")
            finally:
                await pipeline.close()

    # Backfill summaries for existing DAV violations that were saved without summary.
    async with get_session() as backfill_session:
        rows = await backfill_session.execute(
            select(Announcement)
            .where(
                Announcement.source == "dav_violation",
                Announcement.summary.is_(None),
            )
        )
        missing_announcements = list(rows.scalars().all())

        if missing_announcements:
            logger.info(
                f"Backfilling summaries for {len(missing_announcements)} existing DAV violation(s)"
            )

            for announcement in missing_announcements:
                try:
                    pdf_bytes = await fetcher.fetch_pdf_bytes(announcement.url)
                    announcement.summary = await summarizer.summarize_pdf_bytes(pdf_bytes)
                    announcement.processed_at = datetime.utcnow()
                    backfill_session.add(announcement)
                    all_processed.append(announcement)
                    logger.info(
                        f"DAV backfilled: {announcement.external_id} ({len(announcement.summary)} chars)"
                    )
                    await asyncio.sleep(5)  # rate-limit: avoid Gemini quota
                except GeminiQuotaError as e:
                    logger.warning(
                        f"Gemini quota exceeded while backfilling {announcement.external_id}: {e}"
                    )
                    # Stop backfilling — all subsequent calls will also fail
                    break
                except Exception as e:
                    logger.error(f"DAV backfill failed {announcement.external_id}: {e}")

    # Instant Dispatch: If new items are successfully scraped and processed, trigger notification immediately.
    if all_processed:
        logger.info(f"DAV scrape found {len(all_processed)} new processed items. Triggering instant notification!")
        try:
            await _notify_subscribers(settings, settings.telegram_bot_token, summarizer)
        except Exception as e:
            logger.error(f"Failed to trigger instant notification for DAV: {e}")

    return all_processed


# ── Job 2: International news (FDA, EMA, PRAC) ─────────────────────────────

async def _scrape_international(
    settings: _Settings,
    fetcher: DAVFetcher,
    summarizer: GeminiSummarizer,
) -> list[Announcement]:
    """Fetch FDA, EMA, PRAC news and persist new items to DB.

    Only runs when ENABLE_INTERNATIONAL_SOURCES=true in config.
    """
    if not settings.enable_international_sources:
        logger.info("International sources disabled — skipping scrape")
        return []

    async with get_session() as session:
        new_items: list[Announcement] = []
        http = httpx.AsyncClient(timeout=30.0)

        try:
            sources = [
                FDAEnforcementFetcher(http_client=http),
                FDAShortageFetcher(http_client=http),
                FDAApprovalFetcher(http_client=http),
                EMAFetcher(http_client=http),
                EMAShortageFetcher(http_client=http),
                PRACFetcher(http_client=http),
            ]

            for source in sources:
                try:
                    async for news_item in source.fetch_new_items():
                      # Check if already in DB
                      existing = await session.execute(
                          select(Announcement).where(
                              Announcement.external_id == news_item.external_id
                          )
                      )
                      if existing.scalar_one_or_none() is not None:
                          continue

                      ann = Announcement(
                          source=news_item.source.value,
                          external_id=news_item.external_id,
                          title=news_item.title,
                          url=news_item.url,
                          published_date=news_item.published_date,
                          summary=news_item.summary,
                          processed_at=datetime.utcnow(),
                      )
                      session.add(ann)
                      new_items.append(ann)
                      logger.info(f"International new item: {news_item.source.value} — {news_item.title[:60]}")

                    await source.close()

                except Exception as e:
                    logger.error(f"Failed scraping {source.source.value}: {e}")

            await session.commit()
            logger.info(f"International scrape complete: {len(new_items)} new items")
            
            # Instant Dispatch: If new items are successfully scraped and processed, trigger notification immediately.
            if new_items:
                logger.info(f"International scrape found {len(new_items)} new items. Triggering instant notification!")
                try:
                    await _notify_subscribers(settings, settings.telegram_bot_token, summarizer)
                except Exception as e:
                    logger.error(f"Failed to trigger instant notification for International sources: {e}")
                    
            return new_items

        finally:
            await http.aclose()


# ── Job 3: Notification push ──────────────────────────────────────────────────

async def _notify_subscribers(
    settings: _Settings,
    bot_token: str,
    summarizer: GeminiSummarizer,
) -> None:
    """
    Fetch newly scraped announcements and send only those to subscribers.
    An announcement is only sent once per subscriber (tracked via Notification table).
    """
    async with get_session() as session:
        result = await session.execute(
            select(Subscription).where(Subscription.is_active == True)
        )
        subscribers = list(result.scalars().all())
        if not subscribers:
            return

        # All scraped announcements, newest first
        rows = await session.execute(
            select(Announcement)
            .order_by(Announcement.created_at.desc())
        )
        all_announcements = list(rows.scalars().all())

        http = httpx.AsyncClient(timeout=30.0)

        try:
            for subscriber in subscribers:
                # Check which announcements this subscriber has already received
                already_sent = await session.execute(
                    select(Notification.announcement_id).where(
                        Notification.subscription_id == subscriber.id
                    )
                )
                sent_ids: set[int] = {r[0] for r in already_sent.fetchall()}

                # Filter to only unsent announcements whose source is enabled for this subscriber
                enabled = subscriber.get_enabled_sources()
                new_for_subscriber = [
                    ann for ann in all_announcements
                    if ann.id not in sent_ids and ann.source in enabled
                ]

                if not new_for_subscriber:
                    # No new announcements — stay silent
                    logger.debug(f"No new announcements for subscriber {subscriber.chat_id}, skipping")
                    continue

                logger.info(f"Sending {len(new_for_subscriber)} new notifications to {subscriber.chat_id}")

                # Group by source for clean formatting
                by_source: dict[str, list[Announcement]] = {}
                for ann in new_for_subscriber:
                    by_source.setdefault(ann.source, []).append(ann)

                for src in ["dav_violation", "dav_registration",
                             "fda_enforcement", "fda_shortage", "fda_approval",
                             "ema", "ema_shortage", "prac"]:
                    for ann in by_source.get(src, []):
                        message = _format_notification(ann)
                        try:
                            await _send_telegram_message(
                                http, bot_token, subscriber.chat_id, message
                            )
                            await asyncio.sleep(0.5)  # Tránh Telegram rate limit (max ~30 msgs/sec)
                            # Record that this subscriber received this announcement
                            try:
                                # We can query first to see if it exists to be safe and avoid transaction aborts
                                from sqlalchemy.exc import IntegrityError
                                existing_notif = await session.execute(
                                    select(Notification).where(
                                        Notification.subscription_id == subscriber.id,
                                        Notification.announcement_id == ann.id
                                    )
                                )
                                if existing_notif.scalar_one_or_none() is None:
                                    notification = Notification(
                                        subscription_id=subscriber.id,
                                        announcement_id=ann.id,
                                        status="sent",
                                    )
                                    session.add(notification)
                                    # Since get_session() is an async context manager that commits at the end, 
                                    # we can flush to detect database constraints without committing, 
                                    # or just let it commit on clean exit.
                                    await session.flush()
                            except IntegrityError:
                                # If somehow it races or exists, just rollback the flush/savepoint and ignore
                                await session.rollback()
                                logger.warning(f"Notification already exists for sub {subscriber.id}, ann {ann.id}")
                            # NOTE: do NOT commit here — get_session() context manager
                            # commits on clean exit. Double-commit breaks SQLAlchemy's
                            # greenlet context when called from an asyncio.Task.
                        except Exception as e:
                            logger.error(f"Notify failed {subscriber.chat_id}: {e}")

        finally:
            await http.aclose()


def _format_notification(ann: Announcement) -> str:
    """Format an announcement with source emoji and label."""
    emoji, label = _SOURCE_META.get(ann.source, ("📢", "Thông báo"))
    date_str = f"📅 {ann.published_date}" if ann.published_date else ""
    
    parts = [
        f"{emoji} *{label}*",
        f"📋 *{ann.title}*"
    ]
    if date_str:
        parts.append(date_str)
    
    # Only include summary if it is present and not empty
    if ann.summary and ann.summary.strip():
        parts.append(f"\n{ann.summary}")
        
    parts.append(f"\n🔗 [Xem chi tiết]({ann.url})")
    
    return "\n".join(parts)


async def _send_telegram_message(
    http: httpx.AsyncClient,
    token: str,
    chat_id: int,
    text: str,
) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    response = await http.post(url, json={
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    })
    response.raise_for_status()


# ── Scheduler build ────────────────────────────────────────────────────────────

def build_scheduler(
    settings: _Settings,
    fetcher: DAVFetcher,
    summarizer: GeminiSummarizer,
) -> AsyncIOScheduler:
    """Build and configure APScheduler with all jobs."""
    tz = pytz.timezone(settings.timezone)
    scheduler = AsyncIOScheduler(timezone=str(tz))

    # Job 1: DAV scrape (every N minutes)
    if settings.enable_dav_scraping:
        scheduler.add_job(
            _scrape_dav,
            trigger=IntervalTrigger(minutes=settings.check_interval_minutes),
            args=[settings, fetcher, summarizer],
            id="scrape_dav",
            name="DAV scrape + Gemini summarize",
            max_instances=1,
            misfire_grace_time=300,
            replace_existing=True,
        )
        logger.info(f"Scheduled DAV scrape every {settings.check_interval_minutes} min")
    else:
        logger.info("DAV scraping disabled — not scheduling DAV scrape job")

    # Job 2: International news (FDA, EMA, PRAC) — only if enabled
    if settings.enable_international_sources:
        scheduler.add_job(
            _scrape_international,
            trigger=IntervalTrigger(minutes=settings.check_interval_minutes),
            args=[settings, fetcher, summarizer],
            id="scrape_international",
            name="FDA + EMA + PRAC news scrape",
            max_instances=1,
            misfire_grace_time=300,
            replace_existing=True,
        )
        logger.info(f"Scheduled international news scrape every {settings.check_interval_minutes} min")
    else:
        logger.info("International sources disabled — not scheduling FDA/EMA/PRAC")

    # Job 3: Notification push (one cron job per time slot)
    for hour, minute in settings.get_notification_hours():
        scheduler.add_job(
            _notify_subscribers,
            trigger=CronTrigger(hour=hour, minute=minute, timezone=str(tz)),
            args=[settings, settings.telegram_bot_token, summarizer],
            id=f"notify_{hour:02d}{minute:02d}",
            name=f"Notification push at {hour:02d}:{minute:02d}",
            max_instances=1,
            misfire_grace_time=3600,
            replace_existing=True,
        )
        logger.info(f"Scheduled notification at {hour:02d}:{minute:02d}")

    return scheduler
