"""Standalone script to scrape DAV Vietnam from local machine/VPS with local (Vietnam) IP.

This bypasses geo-blocking from dav.gov.vn.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Add project root to python path to ensure proper imports
sys.path.insert(0, str(Path(__file__).parent.resolve()))

from src.core import init_db, close_db, setup_logging, get_logger
from src.core.config import get_settings
from src.scraper import DAVFetcher
from src.summarizer import GeminiSummarizer
from src.scheduler.jobs import _scrape_dav

logger = get_logger("local_scraper")

async def main() -> None:
    settings = get_settings()
    setup_logging(settings)
    
    logger.info("=== Starting Standalone Local DAV Scraper ===")
    
    # Force enable DAV scraping for this script execution
    settings.enable_dav_scraping = True
    
    # Initialize Database
    init_db(settings.resolved_database_url)
    
    # Initialize Fetcher and Summarizer
    fetcher = DAVFetcher(settings)
    summarizer = GeminiSummarizer(settings)
    
    try:
        logger.info("Scraping DAV listings...")
        await _scrape_dav(settings, fetcher, summarizer)
        logger.info("Local DAV scrape completed successfully.")
    except Exception as e:
        logger.exception(f"Local DAV scrape failed: {e}")
        sys.exit(1)
    finally:
        await fetcher.close()
        await close_db()
        logger.info("Database and HTTP clients closed.")

if __name__ == "__main__":
    # Ensure event loop policy for Windows if needed (optional, handled by standard asyncio)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Scraper execution interrupted by user.")
