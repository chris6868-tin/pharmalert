"""Application entry point — wires everything together with graceful shutdown."""
from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from .core import (
    close_db,
    create_tables,
    init_db,
    setup_logging,
    get_logger,
)
from .scraper import DAVFetcher
from .scheduler import build_scheduler
from .summarizer import GeminiSummarizer
from .bot import create_bot


# ── Health check server (dùng khi deploy trên Render) ─────────────────────────

async def _start_health_server(port: int):
    """Start a simple HTTP server for health checks (UptimeRobot / Render)."""
    try:
        from aiohttp import web

        async def _health(request):
            return web.Response(text="OK", status=200)

        http_app = web.Application()
        http_app.router.add_get("/", _health)
        http_app.router.add_get("/health", _health)

        runner = web.AppRunner(http_app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        return runner
    except ImportError:
        return None


async def _main() -> None:
    from .core.config import get_settings

    settings = get_settings()

    # ── Logging ────────────────────────────────────────────────────────────────
    setup_logging(settings)
    logger = get_logger("main")
    logger.info("=== DAV Telegram Bot starting ===")
    logger.info(
        f"Config: scraper={settings.dav_listings_url}, gemini={settings.gemini_model}"
    )

    # ── Database ───────────────────────────────────────────────────────────────
    init_db(settings.resolved_database_url)
    await create_tables()
    db_info = settings.resolved_database_url.split("@")[-1] if "@" in settings.resolved_database_url else settings.resolved_database_url.split("///")[-1]
    logger.info(f"Database ready: {db_info}")

    # ── Scraper + Summarizer ──────────────────────────────────────────────────
    fetcher = DAVFetcher(settings)
    summarizer = GeminiSummarizer(settings)

    # ── Telegram bot ───────────────────────────────────────────────────────────
    app, updater = create_bot(settings.telegram_bot_token)
    await app.initialize()
    logger.info("Telegram bot initialized")

    # ── Health check server (chỉ chạy khi có PORT env var — tức là trên Render) ──
    health_runner = None
    is_production = os.environ.get("RENDER") or os.environ.get("PORT")
    if is_production:
        health_runner = await _start_health_server(settings.port)
        logger.info(f"Health check server started on port {settings.port} — /health")

    # ── Scheduler ─────────────────────────────────────────────────────────────
    scheduler = build_scheduler(settings, fetcher, summarizer)
    scheduler.start()
    logger.info("Scheduler started")

    # ── Graceful shutdown via Ctrl+C ──────────────────────────────────────────
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def _sig_handler(sig: signal.Signals) -> None:
        if not shutdown_event.is_set():
            shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda s=sig: _sig_handler(s))
        except NotImplementedError:
            pass

    # ── Initial scrape (background, after polling starts) ─────────────────────
    async def _initial_scrape(settings, fetcher, summarizer) -> None:
        try:
            from .scheduler.jobs import _scrape_dav, _scrape_international
            await _scrape_dav(settings, fetcher, summarizer)
            if settings.enable_international_sources:
                await _scrape_international(settings, fetcher, summarizer)
            logger.info("Initial scrape complete")
        except Exception as e:
            logger.error(f"Initial scrape failed: {e}")

    # ── Start polling ───────────────────────────────────────────────────────
    await app.start()
    await updater.start_polling(drop_pending_updates=True)
    logger.info("Telegram bot started — polling for updates")

    await _initial_scrape(settings, fetcher, summarizer)

    logger.info("=== DAV Telegram Bot is running — press Ctrl+C to stop ===")

    # ── Wait for shutdown ─────────────────────────────────────────────────────
    try:
        await shutdown_event.wait()
    finally:
        logger.info("Shutting down...")
        await updater.stop()
        scheduler.shutdown(wait=False)
        await app.stop()
        await app.shutdown()
        await close_db()
        if health_runner:
            await health_runner.cleanup()
        logger.info("Shutdown complete")


def main() -> None:
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass
    except SystemExit:
        raise
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
