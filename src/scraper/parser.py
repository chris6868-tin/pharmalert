"""HTML parser for the DAV violation announcements listing page."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, AsyncIterator

from bs4 import BeautifulSoup

from ..core.logging import get_logger

if TYPE_CHECKING:
    from .fetcher import DAVFetcher

logger = get_logger("scraper.parser")


@dataclass(slots=True)
class ListingEntry:
    """A single announcement entry parsed from the listing page."""
    dav_id: str        # unique ID derived from URL or title
    title: str
    url: str           # URL of the detail page
    published_date: str | None


@dataclass(slots=True)
class DetailEntry:
    """Announcement with resolved PDF URL from the detail page."""
    dav_id: str
    title: str
    url: str           # PDF URL — not the listing/detail page URL
    published_date: str | None


class DAVListingParser:
    """
    Parse the DAV listing page HTML and extract announcement entries.

    The listing page contains links to detail pages. Each detail page then
    contains a PDF attachment link. This parser fetches both steps to
    produce DetailEntry objects with the actual PDF URL.
    """

    def __init__(self, fetcher: DAVFetcher, base_url: str) -> None:
        self._fetcher = fetcher
        self._base_url = base_url.rstrip("/")
        self._visited_pages: set[str] = set()

    def _resolve_url(self, href: str) -> str:
        """Convert relative href to absolute URL."""
        if href.startswith("http"):
            return href
        if href.startswith("/"):
            return self._base_url + href
        return f"{self._base_url}/{href}"

    def _normalize_id(self, url: str, title: str) -> str:
        """Generate a stable unique ID from URL and title."""
        url_part = re.sub(r"[^a-zA-Z0-9]", "", url.split("/")[-1])
        title_part = re.sub(r"[^a-zA-Z0-9]", "", title)[:30]
        return f"{url_part}_{title_part}".lower()

    def _extract_date(self, item_soup: BeautifulSoup) -> str | None:
        """Try to extract a date from the item's DOM context."""
        date_selectors = [
            "span.date",
            "span.ngay",
            "time",
            ".date",
            "[class*='date']",
            ".notification-date",
        ]
        for selector in date_selectors:
            el = item_soup.select_one(selector)
            if el and el.get_text(strip=True):
                return el.get_text(strip=True)
        return None

    def _parse_listing_page(self, html: str, page_url: str) -> tuple[list[ListingEntry], str | None]:
        """
        Parse a single DAV listing page HTML.
        Returns (entries, next_page_url_or_none).
        """
        soup = BeautifulSoup(html, "html.parser")
        entries: list[ListingEntry] = []

        # The listing page uses <a class="item small" href="..."> with an
        # <h3 class="title"> and a <time> inside.
        # The link text is in h3.title, the date is in <time>.
        items = soup.select("a.item.small")

        if not items:
            # Fallback: any anchor in the main content area
            items = soup.select("a.item")
        if not items:
            # Generic fallback for Vietnamese government listing pages
            items = soup.select(".content-item a[href]")

        logger.debug(
            f"DAV listing: found {len(items)} anchor items on {page_url}",
        )

        for item in items:
            href = item.get("href", "").strip()
            if not href or href.startswith("#") or href.startswith("javascript:"):
                continue

            # Get title from h3.title inside the anchor
            title_el = item.select_one("h3.title")
            title = title_el.get_text(strip=True) if title_el else ""
            if not title:
                continue

            # Get date from <time> inside the anchor
            time_el = item.select_one("time")
            published_date = None
            if time_el:
                pd = time_el.get_text(strip=True)
                if pd:
                    published_date = pd
            if not published_date:
                published_date = self._extract_date(item)

            url = self._resolve_url(href)
            dav_id = self._normalize_id(url, title)

            entries.append(ListingEntry(
                dav_id=dav_id,
                title=title,
                url=url,
                published_date=published_date,
            ))
            logger.debug(f"Parsed listing entry: {title[:60]}")

        # Detect next page
        next_url: str | None = None
        paging_selectors = [
            "a.next",
            "a[rel='next']",
            ".paging a:last-child",
            ".pagination a:last-child",
            "a.page-next",
        ]
        for selector in paging_selectors:
            next_el = soup.select_one(selector)
            if next_el:
                next_href = next_el.get("href", "").strip()
                if next_href:
                    next_url = self._resolve_url(next_href)
                    break

        return entries, next_url

    def _parse_detail_page(self, html: str) -> str | None:
        """
        Parse a DAV detail page HTML and return the PDF URL.
        The PDF is in <a href="/upload_images/files/...">File đính kèm</a>.
        Returns the absolute PDF URL or None.
        """
        soup = BeautifulSoup(html, "html.parser")

        # Primary selector: link containing "File đính kèm" text
        pdf_links = soup.select("a[href]")
        for link in pdf_links:
            href = link.get("href", "").strip()
            text = link.get_text(strip=True)
            if "file" in href.lower() and (".pdf" in href.lower() or text == "File đính kèm"):
                if href.startswith("/"):
                    return self._base_url + href
                if href.startswith("http"):
                    return href
            # Also catch relative /upload_images/ links
            if "/upload_images/" in href and href.lower().endswith(".pdf"):
                if href.startswith("/"):
                    return self._base_url + href
                if href.startswith("http"):
                    return href

        # Fallback: any PDF link
        for link in soup.select("a[href$='.pdf']"):
            href = link.get("href", "").strip()
            if href:
                if href.startswith("/"):
                    return self._base_url + href
                return href

        return None

    async def fetch_all_entries(
        self, start_url: str, max_pages: int = 5
    ) -> AsyncIterator[DetailEntry]:
        """
        Yield all announcement entries with their PDF URLs resolved.

        Flow per announcement:
          1. Listing page  → parse detail-page URL
          2. Detail page   → fetch PDF URL
          3. Yield DetailEntry(url=PDF_URL)

        Stops after max_pages listing pages to prevent infinite loops.
        """
        current_url = start_url
        page_count = 0

        while current_url and page_count < max_pages:
            if current_url in self._visited_pages:
                logger.debug(f"Skipping already visited page: {current_url}")
                break

            self._visited_pages.add(current_url)
            page_count += 1

            logger.info(
                f"Fetching DAV listing page {page_count}/{max_pages}: {current_url}",
            )

            html = await self._fetcher.fetch_html(current_url)
            listing_entries, next_url = self._parse_listing_page(html, current_url)

            for entry in listing_entries:
                logger.info(
                    f"Fetching DAV detail page to resolve PDF: {entry.url}",
                )
                try:
                    detail_html = await self._fetcher.fetch_html(entry.url)
                    pdf_url = self._parse_detail_page(detail_html)

                    if pdf_url:
                        yield DetailEntry(
                            dav_id=entry.dav_id,
                            title=entry.title,
                            url=pdf_url,
                            published_date=entry.published_date,
                        )
                    else:
                        logger.warning(
                            f"No PDF found on detail page: {entry.url}",
                        )
                except Exception as e:
                    logger.error(
                        f"Failed to fetch detail page {entry.url}: {e}",
                    )

            if not next_url:
                break

            current_url = next_url

        logger.info(
            f"DAV scraping complete: {page_count} pages",
        )
