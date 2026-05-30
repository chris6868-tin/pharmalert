"""Pytest configuration and fixtures."""
import asyncio
from pathlib import Path
from typing import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from _pytest.monkeypatch import MonkeyPatch

BASE_DIR = Path(__file__).parent.parent


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_settings() -> Generator[None, None, None]:
    """Override settings with test values."""
    with MonkeyPatch().context() as m:
        m.setenv("TELEGRAM_BOT_TOKEN", "test_token")
        m.setenv("GEMINI_API_KEY", "test_gemini_key")
        m.setenv("DAV_BASE_URL", "https://dav.gov.vn")
        m.setenv("DAV_LISTINGS_URL", "https://dav.gov.vn/thong-tin-xu-ly-vi-pham-cn5.html")
        m.setenv("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
        m.setenv("LOG_LEVEL", "DEBUG")
        m.setenv("CHECK_INTERVAL_MINUTES", "720")
        m.setenv("NOTIFICATION_TIMES", "12:00,17:00")
        m.setenv("TIMEZONE", "Asia/Ho_Chi_Minh")
        m.setenv("MAX_PDF_SIZE_MB", "10")
        m.setenv("GEMINI_MODEL", "gemini-2.0-flash-lite")
        yield


@pytest_asyncio.fixture
async def clean_db() -> AsyncGenerator[None, None]:
    db_path = BASE_DIR / "test.db"
    if db_path.exists():
        db_path.unlink()
    yield
    if db_path.exists():
        db_path.unlink()


@pytest.fixture
def sample_listing_html(tmp_path: Path) -> str:
    """Minimal HTML matching DAV listing page structure."""
    return """<!DOCTYPE html>
<html>
<head><title>Thông tin xử lý vi phạm</title></head>
<body>
<div class="list-notification">
  <div class="notification-item">
    <a href="/uploads/2025/05/thong-bao-001.pdf" title="Thông báo số 001/2025">
      Thông báo số 001/2025/QĐ-XLVPHC ngày 15/05/2025
    </a>
    <span class="date">15/05/2025</span>
  </div>
  <div class="notification-item">
    <a href="/uploads/2025/05/thong-bao-002.pdf" title="Thông báo số 002/2025">
      Thông báo số 002/2025/QĐ-XLVPHC ngày 20/05/2025
    </a>
    <span class="date">20/05/2025</span>
  </div>
</div>
<div class="paging"><a href="?page=2">Trang 2</a></div>
</body>
</html>"""


@pytest.fixture
def sample_pdf_bytes() -> bytes:
    """Minimal valid PDF (empty page)."""
    return (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
        b"xref\n0 4\n"
        b"trailer<</Size 4/Root 1 0 R>>\n"
        b"startxref\n0\n%%EOF"
    )


@pytest.fixture
def sample_gemini_summary() -> str:
    return (
        "**Tóm tắt thông báo:**\n"
        "Công ty TNHH Dược phẩm ABC bị xử phạt 80.000.000 VNĐ về hành vi "
        "vi phạm quy định về dược. Thông báo có hiệu lực sau 15 ngày kể từ ngày ban hành."
    )
