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

                # Filter to only unsent announcements whose source is enabled and created within the last 24 hours
                from datetime import datetime, timedelta
                threshold = datetime.utcnow() - timedelta(hours=24)
                
                enabled = subscriber.get_enabled_sources()
                new_for_subscriber = []
                for ann in all_announcements:
                    if ann.id in sent_ids or ann.source not in enabled:
                        continue
                    
                    # Safely handle both timezone-naive and timezone-aware datetimes
                    ann_created = ann.created_at.replace(tzinfo=None) if ann.created_at else None
                    if ann_created and ann_created < threshold:
                        continue
                        
                    new_for_subscriber.append(ann)

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


# ── PharmaTech Daily topic schedule ──────────────────────────────────────

# weekday() returns 0=Mon, 1=Tue, ... 6=Sun
_PHARMA_DAILY_TOPICS = {
    # Mon, Wed, Fri — Pharmaceutical formulation & excipient science
    0: ("💡", "Sáng tạo Bào chế & Kỹ thuật tá dược", "bao_che"),
    2: ("💡", "Sáng tạo Bào chế & Kỹ thuật tá dược", "bao_che"),
    4: ("💡", "Sáng tạo Bào chế & Kỹ thuật tá dược", "bao_che"),
    # Tue, Thu — Pharma economics & patent cliff
    1: ("📈", "Xu hướng Kinh tế Dược & Patent Cliff", "kinh_te"),
    3: ("📈", "Xu hướng Kinh tế Dược & Patent Cliff", "kinh_te"),
    # Sat, Sun — Clinical breakthroughs & biologics
    5: ("🔬", "Câu chuyện Lâm sàng & Đột phá Sinh học", "lam_sang"),
    6: ("🔬", "Câu chuyện Lâm sàng & Đột phá Sinh học", "lam_sang"),
}

_PHARMA_DAILY_PROMPTS = {
    "bao_che": """
Bạn là một biên tập viên khoa học dược cao cấp. Hôm nay hãy viết một bài phân tích ngắn gọn, châm súc và cực kỳ hấp dẫn bằng tiếng Việt về một điểm sáng sáng tạo THUẦN TÚY VỀ KỸ THUẬT BÀO CHẾ và tá dược hoặc quá trình sản xuất của một sản phẩm thuốc.

Yêu cầu:
- Chủ đề phải độc đáo, chưa xuất hiện trong danh sách bài viết cũ sau đây: {excluded_topics}
- Nguồn cung cấp thông tin: sáng chế (patent), tạp chí khoa học (IJPS, Drug Discovery Today, v.v.), tin tức công nghệ dược
- Tập trung vào: Công thức thuốc thông minh (NDDS), hệ thống giải phóng kiểm soát, nano-technology, lọbp bào phìm đặc biệt, tẩm mộng tiền thuốc hoạt tính sinh học v.v.
- Cấu trúc bài: Tiêu đề đầy đủ + 3-5 đoạn văn châm súc + kết luận gợi mở (không quá 900 từ)
- Giọng văn: Chuyên nghiệp nhưng dễ hiểu, như một người đam mê khoa học kể cho đồng nghiệp nghe
- Cuối bài: ghi rõ tiêu đề ngắn gọm (dưới 10 từ) ở dạng: **Tiêu đề chính:** <tiêu đề>
""",
    "kinh_te": """
Bạn là một biên tập viên khoa học kinh tế dược cấp cao. Hôm nay hãy viết một bài phân tích ngắn gọn, sâu sắc bằng tiếng Việt về một trường hợp đáng chú ý trong KINH TẺ DƯỢC PHẨM (patent cliff, giá thuốc, cưới tóc của công ty, thị trường generic, chiến lược BD&L).

Yêu cầu:
- Chủ đề phải độc đáo, chưa xuất hiện trong: {excluded_topics}
- Nguồn: Fierce Pharma, Evaluate Pharma, Reuters Pharma, báo cáo của USPTO/EPO/EMA
- Tập trung vào: cơ hội cho generic, hết hạn bản quyền (patent cliff), xu hướng M&A, tác động đến Việt Nam
- Cấu trúc: Tiêu đề + 3-4 đoạn + chú giải ngắn về ý nghĩa với thị trường Việt Nam (không quá 900 từ)
- Giọng văn: Phân tích sắc bén, số liệu cụ thể, kết luận hữ u ích
- Cuối bài: **Tiêu đề chính:** <tiêu đề>
""",
    "lam_sang": """
Bạn là một biên tập viên khoa học lâm sàng. Hôm nay hãy viết một bài phân tích ngắn gọm, cuốn hút bằng tiếng Việt về một CÂU CHUYỆN ĐỘT PHÁ VỀ THUỐC MỚI hoặc SINH PHẨM FDA đã được phê duyệt gần đây (trong 12 tháng qua).

Yêu cầu:
- Chủ đề phải độc đáo, chưa xuất hiện trong: {excluded_topics}
- Nguồn: FDA news, NEJM, The Lancet, ClinicalTrials.gov
- Tập trung vào: cơ chế tác động mới lạ, kết quả thử nghiệm lâm sàng nổi bật, tiềm năng ứng dụng tại Việt Nam
- Cấu trúc: Tiêu đề + tóm tắt thử nghiệm + ý nghĩa lâm sàng + kết luận (không quá 750 từ)
- Giọng văn: Khoa học chính xác nhưng có cảm xúc, như kể câu chuyện khám phá y học
- Cuối bài: **Tiêu đề chính:** <tiêu đề>
""",
}

COFFEE_SIGNATURE = (
    "\n\n---\n"
    "_✍️ Biên tập (không chịu trách nhiệm về nội dung): T_ \n"
)


# ── Job 4: PharmaTech Daily — AI-generated pharma insight ──────────────────

async def _generate_pharma_daily(
    settings: _Settings,
    summarizer: GeminiSummarizer,
    force: bool = False,
) -> None:
    """
    Generate a PharmaTech Daily article via Gemini and send to Admin for review.
    Runs daily at pharma_daily_time. Alternates topics by weekday.
    Stores topic history in DB to prevent duplicate subjects.
    """
    if not settings.enable_pharma_daily and not force:
        logger.info("PharmaTech Daily disabled — skipping generation")
        return
    if not settings.admin_telegram_chat_id:
        logger.warning("ADMIN_TELEGRAM_CHAT_ID not set — cannot send PharmaTech Daily draft")
        return

    tz = pytz.timezone(settings.timezone)
    today = datetime.now(tz)
    weekday = today.weekday()
    topic_emoji, topic_label, topic_key = _PHARMA_DAILY_TOPICS[weekday]
    date_display = today.strftime("%A, %d/%m/%Y")

    # Fetch recent 30 published topics (summaries used as topic keys)
    async with get_session() as session:
        rows = await session.execute(
            select(Announcement.title)
            .where(Announcement.source == "pharma_daily")
            .order_by(Announcement.created_at.desc())
            .limit(30)
        )
        recent_titles = [r[0] for r in rows.fetchall()]

    excluded_topics = "; ".join(recent_titles) if recent_titles else "(không có)"

    prompt_template = _PHARMA_DAILY_PROMPTS[topic_key]
    prompt = prompt_template.format(excluded_topics=excluded_topics)

    logger.info(f"Generating PharmaTech Daily [{topic_label}] for {date_display}...")

    try:
        article_text = await summarizer.generate_text(prompt)
    except Exception as e:
        logger.error(f"Gemini generation failed for PharmaTech Daily: {e}")
        http = httpx.AsyncClient(timeout=30.0)
        try:
            await http.post(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                json={
                    "chat_id": settings.admin_telegram_chat_id,
                    "text": f"❌ PharmaTech Daily generation failed: {e}",
                },
            )
        finally:
            await http.aclose()
        return

    # Extract short title from article (model appends: **Tiêu đề chính:** ...)
    short_title = _extract_title(article_text, topic_label, date_display)

    # Build full message for preview
    preview_header = (
        f"{topic_emoji} *PharmaTech Daily — {topic_label}*\n"
        f"📅 {date_display}\n\n"
    )
    broadcast_body = preview_header + article_text + COFFEE_SIGNATURE

    # Save draft (processed_at=None means pending approval)
    async with get_session() as session:
        ann = Announcement(
            source="pharma_daily",
            external_id=f"pharma_daily_{today.strftime('%Y%m%d_%H%M%S')}",
            title=short_title,
            url="https://t.me",  # No external URL for AI-generated content
            published_date=today.strftime("%d/%m/%Y"),
            summary=broadcast_body,
            processed_at=None,  # pending approval
        )
        session.add(ann)
        await session.flush()  # get ann.id before commit
        ann_id = ann.id

    logger.info(f"PharmaTech Daily draft saved (id={ann_id}, title='{short_title}')")

    # Send preview to Admin with approve/regenerate buttons
    preview_text = (
        f"📋 *[PHẢI DUYỆT] PharmaTech Daily*\n"
        f"{topic_emoji} *Chủ đề:* {topic_label}\n"
        f"📅 *Ngày:* {date_display}\n"
        f"🔖 *Tiêu đề:* {short_title}\n\n"
        f"───────────────────────────────────\n"
        f"{article_text[:3000]}"
        + ("\n..._(bài quá dài, đã cắt ngắn xem trước)_" if len(article_text) > 3000 else "")
        + f"\n───────────────────────────────────"
    )

    inline_keyboard = [
        [
            {"text": "✅ Duyệt & Phát sóng", "callback_data": f"pharma_approve:{ann_id}"},
            {"text": "♻️ Tạo bài khác", "callback_data": f"pharma_regenerate:{ann_id}"},
        ]
    ]

    http = httpx.AsyncClient(timeout=30.0)
    try:
        resp = await http.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
            json={
                "chat_id": settings.admin_telegram_chat_id,
                "text": preview_text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
                "reply_markup": {"inline_keyboard": inline_keyboard},
            },
        )
        resp.raise_for_status()
        logger.info(f"PharmaTech Daily draft sent to Admin (chat_id={settings.admin_telegram_chat_id})")
    except Exception as e:
        logger.error(f"Failed to send PharmaTech Daily draft to Admin: {e}")
    finally:
        await http.aclose()


def _extract_title(article_text: str, fallback_label: str, date_display: str) -> str:
    """Extract the short title the AI appended at the end of the article."""
    for line in reversed(article_text.splitlines()):
        line = line.strip()
        if "Tiêu đề chính:" in line:
            title = line.split("Tiêu đề chính:", 1)[-1].strip().strip("*_")
            if title:
                return title
    return f"{fallback_label} — {date_display}"


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

    # Job 4: PharmaTech Daily — AI-generated pharma insight (daily at pharma_daily_time)
    if settings.enable_pharma_daily:
        pd_parts = settings.pharma_daily_time.split(":")
        pd_hour, pd_minute = int(pd_parts[0]), int(pd_parts[1])
        scheduler.add_job(
            _generate_pharma_daily,
            trigger=CronTrigger(hour=pd_hour, minute=pd_minute, timezone=str(tz)),
            args=[settings, summarizer],
            id="pharma_daily",
            name=f"PharmaTech Daily generation at {pd_hour:02d}:{pd_minute:02d}",
            max_instances=1,
            misfire_grace_time=3600,
            replace_existing=True,
        )
        logger.info(f"Scheduled PharmaTech Daily generation at {pd_hour:02d}:{pd_minute:02d}")
    else:
        logger.info("PharmaTech Daily disabled — not scheduling daily generation job")

    return scheduler
