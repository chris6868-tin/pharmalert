"""Async HTTP client for fetching DAV HTML pages and PDFs with retry + size limit."""
from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from ..core.exceptions import PDFSizeError, ScraperError
from ..core.logging import get_logger

if TYPE_CHECKING:
    from ..core.config import _Settings

logger = get_logger("scraper.fetcher")

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
    "Referer": "https://dav.gov.vn/",
}


class DAVFetcher:
    """Async HTTP fetcher with retry, timeout, and PDF size guard."""

    def __init__(self, settings: _Settings) -> None:
        self._settings = settings
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers=DEFAULT_HEADERS,
                timeout=httpx.Timeout(self._settings.http_timeout_seconds),
                follow_redirects=True,
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _fetch_with_retry(self, url: str) -> httpx.Response:
        """Fetch URL with exponential backoff retry."""
        client = await self._get_client()
        max_retries = self._settings.http_max_retries

        for attempt in range(1, max_retries + 1):
            try:
                response = await client.get(url)
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (429, 500, 502, 503, 504):
                    logger.warning(
                        f"HTTP error on attempt {attempt}/{max_retries} for {url}: {e.response.status_code}",
                    )
                    if attempt == max_retries:
                        raise ScraperError(
                            f"HTTP {e.response.status_code} after {max_retries} retries",
                            cause=e,
                        ) from e
                    await self._backoff(attempt)
                else:
                    raise ScraperError(f"HTTP {e.response.status_code}: {url}", cause=e) from e
            except httpx.RequestError as e:
                logger.warning(
                    f"Request error on attempt {attempt}/{max_retries} for {url}",
                )
                if attempt == max_retries:
                    raise ScraperError(f"Request failed after {max_retries} retries: {url}", cause=e) from e
                await self._backoff(attempt)

    async def _backoff(self, attempt: int) -> None:
        import asyncio
        delay = min(2 ** attempt, 30)  # Cap at 30 seconds
        await asyncio.sleep(delay)

    async def fetch_html(self, url: str) -> str:
        """Fetch an HTML page and return its text content."""
        logger.debug(f"Fetching HTML: {url}")
        response = await self._fetch_with_retry(url)
        return response.text

    async def fetch_pdf_bytes(self, url: str) -> bytes:
        """
        Fetch a PDF file and return its bytes.
        Raises PDFSizeError if the file exceeds max_pdf_size_bytes.
        """
        logger.debug(f"Fetching PDF: {url}")
        client = await self._get_client()
        max_size = self._settings.max_pdf_size_bytes

        try:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                if "pdf" not in content_type.lower() and not url.lower().endswith(".pdf"):
                    logger.warning(
                        f"Unexpected content type for PDF URL {url}: {content_type}",
                    )

                chunks: list[bytes] = []
                total_size = 0

                async for chunk in response.aiter_bytes(chunk_size=65536):
                    total_size += len(chunk)
                    if total_size > max_size:
                        raise PDFSizeError(
                            f"PDF exceeds {self._settings.max_pdf_size_mb} MB limit "
                            f"(total: {total_size / 1024 / 1024:.1f} MB)",
                        )
                    chunks.append(chunk)

                result = b"".join(chunks)
                logger.debug(
                    f"PDF fetched {url}: {len(result)} bytes",
                )
                return result

        except PDFSizeError:
            raise
        except httpx.HTTPStatusError as e:
            raise ScraperError(f"PDF HTTP {e.response.status_code}: {url}", cause=e) from e
        except httpx.RequestError as e:
            raise ScraperError(f"PDF request failed: {url}", cause=e) from e
