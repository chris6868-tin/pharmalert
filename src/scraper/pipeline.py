"""DAV scraper pipeline — orchestrates fetching, parsing, PDF download, and DB persistence."""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_session
from ..core.exceptions import ScraperError
from ..core.logging import get_logger
from ..core.models import Announcement

from .fetcher import DAVFetcher
from .parser import DAVListingParser

logger = get_logger("scraper.pipeline")


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
                    url=entry.url,
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
