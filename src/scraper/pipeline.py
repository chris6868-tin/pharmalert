"""DAV scraper pipeline — orchestrates fetching, parsing, PDF download, and DB persistence."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_session
from ..core.exceptions import ScraperError
from ..core.logging import get_logger
from ..core.models import Announcement

from .fetcher import DAVFetcher
from .parser import DAVListingParser

logger = get_logger("scraper.pipeline")


def _is_too_old(published_date_str: str | None, max_days: int = 60) -> bool:
    """Check if the publication date is older than max_days.
    
    Standard DAV date format is DD/MM/YYYY (e.g., "22/08/2014" or "20/8/2014").
    """
    if not published_date_str:
        return False
    try:
        # Giữ lại chỉ các chữ số và dấu gạch chéo
        clean_str = re.sub(r'[^0-9/]', '', published_date_str).strip()
        parts = clean_str.split('/')
        if len(parts) == 3:
            day = int(parts[0])
            month = int(parts[1])
            year = int(parts[2])
            pub_date = datetime(year, month, day)
            age = datetime.now() - pub_date
            if age > timedelta(days=max_days):
                return True
    except Exception as e:
        logger.debug(f"Failed to parse publication date '{published_date_str}': {e}")
    return False


@dataclass(slots=True)
class ScrapeResult:
    """Result of a single scraping run."""
    new_entries: int
    skipped_entries: int
    failed_entries: int
    announcements: list[Announcement]


class DAVScraperPipeline:
    """
    Full scraping pipeline:
      1. Fetch listing pages (with pagination)
      2. Filter entries already in DB
      3. Persist new entries
      4. Return list of new Announcement ORM objects
    """

    def __init__(
        self,
        fetcher: DAVFetcher,
        listings_url: str,
        source_key: str = "dav_violation",
    ) -> None:
        self._fetcher = fetcher
        self._parser = DAVListingParser(fetcher, fetcher._settings.dav_base_url)
        self._listings_url = listings_url
        self._source_key = source_key

    async def run(self, session: AsyncSession) -> ScrapeResult:
        """
        Fetch new announcements from DAV listing pages.
        Returns ScrapeResult with new/skipped/failed counts and Announcement objects.
        """
        new_entries: list[Announcement] = []
        skipped = 0
        failed = 0

        logger.info("Starting DAV scrape pipeline")

        async for entry in self._parser.fetch_all_entries(self._listings_url, max_pages=5):
            # Lọc bỏ các tin quá cũ (tránh lỗi web DAV tự xáo trộn đưa bài từ 2014 lên trang đầu)
            if _is_too_old(entry.published_date, max_days=60):
                logger.info(f"Skipping announcement older than 60 days ({entry.published_date}): {entry.title[:60]}")
                skipped += 1
                continue

            # Check if already in DB
            existing = await session.execute(
                select(Announcement).where(Announcement.external_id == entry.dav_id)
            )
            if existing.scalar_one_or_none() is not None:
                skipped += 1
                logger.debug(f"Skipping already-processed entry: {entry.dav_id}")
                continue

            # Create announcement record (PDF not yet downloaded in this phase)
            try:
                announcement = Announcement(
                    source=self._source_key,
                    external_id=entry.dav_id,
                    title=entry.title,
                    url=entry.detail_url if entry.detail_url else entry.url,
                    published_date=entry.published_date,
                )
                session.add(announcement)
                new_entries.append(announcement)
                logger.info(f"New announcement found: {announcement.external_id} — {announcement.title[:80]}")
            except Exception as e:
                logger.error(f"Failed to create announcement record for {entry.dav_id}: {e}")
                failed += 1

        logger.info(f"Pipeline complete: {len(new_entries)} new, {skipped} skipped, {failed} failed")
        return ScrapeResult(
            new_entries=len(new_entries),
            skipped_entries=skipped,
            failed_entries=failed,
            announcements=new_entries,
        )

    async def close(self) -> None:
        await self._fetcher.close()
