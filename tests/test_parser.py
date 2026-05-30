"""Unit tests for the DAV HTML listing parser."""
from src.scraper.parser import DAVListingParser, ListingEntry


class TestDAVListingParser:
    def test_resolve_url_full(self) -> None:
        from src.scraper.fetcher import DAVFetcher
        from src.core.config import _Settings

        settings = _Settings()
        fetcher = DAVFetcher(settings)
        parser = DAVListingParser(fetcher, "https://dav.gov.vn")

        assert parser._resolve_url("https://other.com/page") == "https://other.com/page"
        assert parser._resolve_url("/uploads/doc.pdf") == "https://dav.gov.vn/uploads/doc.pdf"
        assert parser._resolve_url("page2.html") == "https://dav.gov.vn/page2.html"

    def test_normalize_id_consistent(self) -> None:
        from src.scraper.fetcher import DAVFetcher
        from src.core.config import _Settings

        settings = _Settings()
        fetcher = DAVFetcher(settings)
        parser = DAVListingParser(fetcher, "https://dav.gov.vn")

        id1 = parser._normalize_id("/uploads/2025/05/thongbao123.pdf", "Thông báo 123")
        id2 = parser._normalize_id("/uploads/2025/05/thongbao123.pdf", "Thông báo 123")
        assert id1 == id2
        assert len(id1) < 100

    def test_normalize_id_different_for_different_urls(self) -> None:
        from src.scraper.fetcher import DAVFetcher
        from src.core.config import _Settings

        settings = _Settings()
        fetcher = DAVFetcher(settings)
        parser = DAVListingParser(fetcher, "https://dav.gov.vn")

        id1 = parser._normalize_id("/file-a.pdf", "Title A")
        id2 = parser._normalize_id("/file-b.pdf", "Title B")
        assert id1 != id2

    def test_parse_page_extracts_entries(self, sample_listing_html: str) -> None:
        from src.scraper.fetcher import DAVFetcher
        from src.core.config import _Settings

        settings = _Settings()
        fetcher = DAVFetcher(settings)
        parser = DAVListingParser(fetcher, "https://dav.gov.vn")

        entries, next_url = parser._parse_page(sample_listing_html, "https://dav.gov.vn/test")

        assert len(entries) == 2
        assert entries[0].title == "Thông báo số 001/2025/QĐ-XLVPHC ngày 15/05/2025"
        assert entries[0].url == "https://dav.gov.vn/uploads/2025/05/thong-bao-001.pdf"
        assert entries[0].published_date == "15/05/2025"

    def test_parse_page_handles_missing_date(self) -> None:
        from src.scraper.fetcher import DAVFetcher
        from src.core.config import _Settings

        settings = _Settings()
        fetcher = DAVFetcher(settings)
        parser = DAVListingParser(fetcher, "https://dav.gov.vn")

        html_no_date = """<html><body>
        <div class="notification-item">
            <a href="/doc.pdf">Simple Doc</a>
        </div></body></html>"""

        entries, _ = parser._parse_page(html_no_date, "https://dav.gov.vn/test")
        assert len(entries) == 1
        assert entries[0].published_date is None
