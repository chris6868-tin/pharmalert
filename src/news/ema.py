"""EMA news and shortage sources via JSON API and HTML parsing."""
from __future__ import annotations

import re
from datetime import datetime, timedelta

import httpx
from bs4 import BeautifulSoup

from ..core.exceptions import ScraperError
from ..core.logging import get_logger
from .base import NewsItem, NewsSource, NewsSourceBase

logger = get_logger("news.ema")

# ── EMA News (JSON) ────────────────────────────────────────────────────────────

class EMAFetcher(NewsSourceBase):
    """
    Fetch EMA news from the official EMA JSON data files (updated twice daily).

    JSON files available at:
    - News:        https://www.ema.europa.eu/en/documents/report/news-json-report_en.json
    - New medicines: https://www.ema.europa.eu/en/documents/report/medicines-output-medicines_json-report_en.json
    """

    NEWS_JSON_URL = "https://www.ema.europa.eu/en/documents/report/news-json-report_en.json"
    MEDICINES_JSON_URL = "https://www.ema.europa.eu/en/documents/report/medicines-output-medicines_json-report_en.json"

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        super().__init__(NewsSource.EMA)
        self._client = http_client
        self._seen_urls: set[str] = set()

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(60.0))
        return self._client

    @property
    def emoji(self) -> str:
        return "🇪🇺"

    @property
    def label(self) -> str:
        return "EMA News"

    def _is_recent(self, date_str: str | None, days: int = 30) -> bool:
        """Return True if date_str (DD/MM/YYYY) is within the last `days` days."""
        if not date_str:
            return False
        try:
            d = datetime.strptime(date_str.strip(), "%d/%m/%Y")
            return d >= datetime.utcnow() - timedelta(days=days)
        except ValueError:
            return False

    def _normalize_date(self, raw: str | None) -> str | None:
        """Return DD/MM/YYYY or None from DD/MM/YYYY input."""
        if not raw:
            return None
        raw = raw.strip()
        try:
            d = datetime.strptime(raw, "%d/%m/%Y")
            return d.strftime("%d/%m/%Y")
        except ValueError:
            return raw

    async def fetch_new_items(self):
        """Fetch from both JSON files."""
        async for item in self._fetch_news_json(self.NEWS_JSON_URL, "news"):
            yield item
        async for item in self._fetch_medicines_json(self.MEDICINES_JSON_URL):
            yield item

    async def _fetch_news_json(self, url: str, label: str):
        """Parse EMA news JSON and yield NewsItems for Human/Medicines topics."""
        client = await self._get_client()
        try:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as e:
            raise ScraperError(f"EMA JSON HTTP {e.response.status_code}: {url}", cause=e) from e
        except httpx.RequestError as e:
            raise ScraperError(f"EMA JSON request failed: {url}", cause=e) from e
        except Exception as e:
            raise ScraperError(f"EMA JSON parse failed: {url}", cause=e) from e

        records = data.get("data", [])
        logger.info(f"EMA JSON [{label}]: {len(records)} total records")

        for record in records:
            news_url = record.get("news_url", "").strip()
            if not news_url:
                continue

            # Skip duplicates within this run
            if news_url in self._seen_urls:
                continue
            self._seen_urls.add(news_url)

            title = record.get("title", "")
            categories = record.get("categories", "")
            topics = record.get("topics", "")
            summary = record.get("news_summary", "")
            published = record.get("first_published_date", "")
            updated = record.get("last_updated_date", "")

            # Filter: only Human medicines-related topics, within last 30 days
            if categories != "Human":
                continue
            skip_topics = {"Corporate", "Veterinary"}
            if topics in skip_topics:
                continue
            if not self._is_recent(published):
                continue

            if not title:
                continue

            slug = re.sub(r"[^a-zA-Z0-9]", "", news_url.split("/")[-1][:50])

            async for item in self._track_and_yield(NewsItem(
                source=NewsSource.EMA,
                external_id=f"ema-{slug}",
                title=f"🇪🇺 [EMA] {title}",
                url=news_url,
                published_date=published or updated or None,
                summary=(
                    f"📂 {topics}\n{summary}" if (topics and summary) else (summary or title)
                ),
                raw_content=f"categories={categories}; topics={topics}",
            )):
                yield item

    async def _fetch_medicines_json(self, url: str):
        """Parse EMA medicines JSON and yield newly authorized medicines."""
        client = await self._get_client()
        try:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as e:
            raise ScraperError(f"EMA Medicines JSON HTTP {e.response.status_code}: {url}", cause=e) from e
        except httpx.RequestError as e:
            raise ScraperError(f"EMA Medicines JSON request failed: {url}", cause=e) from e
        except Exception as e:
            raise ScraperError(f"EMA Medicines JSON parse failed: {url}", cause=e) from e

        records = data.get("data", [])
        logger.info(f"EMA Medicines JSON: {len(records)} total records")

        for record in records:
            category = record.get("category", "")
            if category != "Human":
                continue

            status = record.get("medicine_status", "")
            # Only include newly authorized medicines from last 30 days
            if status != "Authorised":
                continue
            published = record.get("first_published_date", "")
            # Use first_published_date as proxy for when it appeared on EMA
            if not self._is_recent(published, days=30):
                continue

            medicine_url = record.get("medicine_url", "")
            active_substance = record.get("active_substance", "")
            atc_code = record.get("atc_code_human", "")
            medicine_name = record.get("name_of_medicine", "")
            generic_name = record.get("international_non_proprietary_name_common_name", "")
            indication = record.get("therapeutic_indication", "")
            holder = record.get("marketing_authorisation_developer_applicant_holder", "")
            auth_date = record.get("marketing_authorisation_date", "")

            if not medicine_name:
                continue

            display_name = f"{medicine_name} ({generic_name})" if generic_name else medicine_name

            parts = []
            if holder:
                parts.append(f"🏢 *Holder:* {holder}")
            if active_substance:
                parts.append(f"🧪 *Hoạt chất:* {active_substance}")
            if indication:
                parts.append(f"💡 *Chỉ định:* {indication[:300]}")
            if atc_code:
                parts.append(f"🏷️ *ATC:* {atc_code}")
            if auth_date:
                parts.append(f"📅 *Ngày cấp phép:* {auth_date}")

            slug = re.sub(r"[^a-zA-Z0-9]", "", medicine_name[:30])

            async for item in self._track_and_yield(NewsItem(
                source=NewsSource.EMA,
                external_id=f"ema-med-{slug}",
                title=f"🇪🇺 [EMA Medicine] {display_name}",
                url=medicine_url or "",
                published_date=published or auth_date or None,
                summary="\n".join(parts) if parts else f"✅ New medicine authorized by EMA",
            )):
                yield item

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


# ── EMA Medicine Shortages (HTML) ───────────────────────────────────────────────

class EMAShortageFetcher(NewsSourceBase):
    """
    Fetch EMA medicine shortage communications from the MSC HTML page.

    Each shortage item is in a <div class="file-title-metadata ..."> block
    containing a PDF link with title and first-published date.
    """

    SHORTAGE_URL = (
        "https://www.ema.europa.eu/en/human-regulatory-overview/"
        "post-authorisation/medicine-shortages-availability-issues/"
        "medicine-shortage-communications-msc"
    )

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        super().__init__(NewsSource.EMA_SHORTAGE)
        self._client = http_client

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        return self._client

    @property
    def emoji(self) -> str:
        return "🚫"

    @property
    def label(self) -> str:
        return "EMA Medicine Shortage"

    async def fetch_new_items(self):
        client = await self._get_client()
        try:
            response = await client.get(self.SHORTAGE_URL)
            response.raise_for_status()
            html = response.text
        except httpx.HTTPStatusError as e:
            raise ScraperError(f"EMA Shortage HTTP {e.response.status_code}", cause=e) from e
        except httpx.RequestError as e:
            raise ScraperError(f"EMA Shortage request failed", cause=e) from e

        soup = BeautifulSoup(html, "html.parser")

        # Each shortage entry is in a <div class="file-title-metadata ..."> block
        # The parent <div class="file..."> contains the PDF link
        file_blocks = soup.select("div.file-title-metadata")

        logger.info(f"EMA Shortages: parsed {len(file_blocks)} file blocks from MSC page")

        for block in file_blocks:
            # Title: <p class="file-title mb-1 fw-bold">
            title_el = block.select_one("p.file-title")
            if not title_el:
                continue

            title = title_el.get_text(strip=True)
            if not title:
                continue

            # PDF link: <a class="standalone" href="...">View</a>
            link_el = block.find_next("a", class_="standalone")
            href = ""
            if link_el:
                href = link_el.get("href", "").strip()
                if href and not href.startswith("http"):
                    href = "https://www.ema.europa.eu" + href

            # Date: <time datetime="YYYY-MM-DD...">
            time_el = block.find_next("time")
            date_text = ""
            if time_el:
                date_text = time_el.get_text(strip=True)
                # Convert ISO datetime to DD/MM/YYYY if needed
                dt = time_el.get("datetime", "")
                if dt and "T" in dt:
                        try:
                            d = datetime.fromisoformat(dt.split("T")[0])
                            date_text = d.strftime("%d/%m/%Y")
                        except Exception:
                            pass

            if not title:
                continue

            # Skip non-shortage items (Q&A docs, generic files)
            skip_words = ["question", "answers", "signal management", "about this page"]
            if any(w.lower() in title.lower() for w in skip_words):
                continue

            slug = re.sub(r"[^a-zA-Z0-9]", "", title[:40])
            external_id = f"ema-short-{slug}"

            async for item in self._track_and_yield(NewsItem(
                source=NewsSource.EMA_SHORTAGE,
                external_id=external_id,
                title=f"🚫 [EMA Shortage] {title[:120]}",
                url=href or self.SHORTAGE_URL,
                published_date=date_text or None,
                summary=(
                    f"📋 {title}\n📅 Ngày: {date_text}" if date_text else f"📋 {title}"
                ),
            )):
                yield item

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


# ── PRAC Safety Signals (HTML) ─────────────────────────────────────────────────

class PRACFetcher(NewsSourceBase):
    """Fetch PRAC safety signal recommendations from EMA HTML page."""

    PRAC_URL = (
        "https://www.ema.europa.eu/en/human-regulatory-overview/"
        "post-authorisation/pharmacovigilance-post-authorisation/"
        "signal-management/prac-recommendations-safety-signals"
    )

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        super().__init__(NewsSource.PRAC)
        self._client = http_client

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        return self._client

    @property
    def emoji(self) -> str:
        return "⚕️"

    @property
    def label(self) -> str:
        return "EMA PRAC Signals"

    async def fetch_new_items(self):
        client = await self._get_client()
        try:
            response = await client.get(self.PRAC_URL)
            response.raise_for_status()
            html = response.text
        except httpx.HTTPStatusError as e:
            raise ScraperError(f"PRAC HTTP {e.response.status_code}", cause=e) from e
        except httpx.RequestError as e:
            raise ScraperError(f"PRAC request failed", cause=e) from e

        soup = BeautifulSoup(html, "html.parser")
        rows = soup.select("table tbody tr")

        if not rows:
            logger.debug("No PRAC table rows found on page")
            return

        logger.info(f"PRAC: parsed {len(rows)} rows")

        for row in rows:
            cells = row.select("td")
            if len(cells) < 2:
                continue

            date_el = cells[0]
            content_el = cells[1]
            status_el = cells[2] if len(cells) > 2 else None

            date_text = date_el.get_text(strip=True)
            content_link = content_el.select_one("a")
            content_text = content_el.get_text(strip=True, separator=" | ")
            status_text = status_el.get_text(strip=True) if status_el else "Không rõ"

            if not content_text:
                continue

            link = ""
            if content_link:
                link = content_link.get("href", "")
                if link and not link.startswith("http"):
                    link = "https://www.ema.europa.eu" + link

            slug = re.sub(r"[^a-zA-Z0-9]", "", content_text[:40])

            async for item in self._track_and_yield(NewsItem(
                source=NewsSource.PRAC,
                external_id=f"prac-{slug}",
                title=f"⚕️ [PRAC Signal] {content_text[:120]}",
                url=link or self.PRAC_URL,
                published_date=date_text if "/" in date_text else None,
                summary=(
                    f"📅 Ngày: {date_text}\n"
                    f"📋 Nội dung: {content_text[:400]}\n"
                    f"📊 Trạng thái: {status_text}"
                ),
            )):
                yield item

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
