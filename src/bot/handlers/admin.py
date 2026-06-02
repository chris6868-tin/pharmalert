"""Admin callback handlers for PharmaTech Daily article review/approval."""
from __future__ import annotations

import json
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from ...core.database import get_session
from ...core.logging import get_logger
from ...core.models import Announcement

logger = get_logger("bot.handlers.admin")


async def admin_approval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle inline keyboard callbacks from Admin for PharmaTech Daily drafts.

    Patterns:
      pharma_approve:<announcement_id>   → approve & broadcast
      pharma_regenerate:<announcement_id> → delete draft & regenerate
    """
    query = update.callback_query
    if query is None:
        return

    await query.answer()

    data = query.data or ""
    parts = data.split(":", 1)
    if len(parts) != 2:
        return

    action, ann_id_str = parts
    try:
        ann_id = int(ann_id_str)
    except ValueError:
        await query.edit_message_text("❌ Dữ liệu callback không hợp lệ.")
        return

    if action == "pharma_approve":
        await _handle_approve(query, context, ann_id)
    elif action == "pharma_regenerate":
        await _handle_regenerate(query, context, ann_id)
    else:
        await query.edit_message_text("❓ Hành động không xác định.")


async def _handle_approve(query, context, ann_id: int) -> None:
    """Approve the draft and broadcast to all pharma_daily subscribers."""
    from ...core.config import get_settings
    from ..handlers.subscription import AVAILABLE_SOURCES
    from sqlalchemy import select
    from ...core.models import Subscription, Notification
    import httpx

    settings = get_settings()

    async with get_session() as session:
        result = await session.execute(
            select(Announcement).where(Announcement.id == ann_id)
        )
        ann = result.scalar_one_or_none()

        if not ann:
            await query.edit_message_text("❌ Không tìm thấy bài viết trong cơ sở dữ liệu.")
            return

        if ann.processed_at is not None:
            await query.edit_message_text("⚠️ Bài viết này đã được duyệt rồi.")
            return

        # Mark as approved
        ann.processed_at = datetime.utcnow()

        # Get all subscribers with pharma_daily enabled
        subs_result = await session.execute(
            select(Subscription).where(Subscription.is_active == True)
        )
        subscribers = list(subs_result.scalars().all())
        pharma_subs = [s for s in subscribers if "pharma_daily" in s.get_enabled_sources()]

        if not pharma_subs:
            await query.edit_message_text(
                "✅ Bài đã duyệt.\n\n"
                "⚠️ Chưa có người dùng nào đăng ký nhận *PharmaTech Daily*.",
                parse_mode="Markdown",
            )
            return

        # Broadcast
        http = httpx.AsyncClient(timeout=30.0)
        sent_count = 0
        fail_count = 0
        try:
            message = _format_pharma_daily_message(ann)
            for sub in pharma_subs:
                try:
                    resp = await http.post(
                        f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                        json={
                            "chat_id": sub.chat_id,
                            "text": message,
                            "parse_mode": "Markdown",
                            "disable_web_page_preview": True,
                        },
                    )
                    resp.raise_for_status()
                    sent_count += 1

                    # Record notification
                    existing_notif = await session.execute(
                        select(Notification).where(
                            Notification.subscription_id == sub.id,
                            Notification.announcement_id == ann.id,
                        )
                    )
                    if existing_notif.scalar_one_or_none() is None:
                        session.add(Notification(
                            subscription_id=sub.id,
                            announcement_id=ann.id,
                            status="sent",
                        ))
                except Exception as e:
                    fail_count += 1
                    logger.error(f"Failed to send pharma_daily to {sub.chat_id}: {e}")
        finally:
            await http.aclose()

        await session.flush()

    await query.edit_message_text(
        f"✅ *Đã duyệt và phát sóng PharmaTech Daily!*\n\n"
        f"📨 Đã gửi đến *{sent_count}* người dùng"
        + (f"\n⚠️ Thất bại: {fail_count}" if fail_count else ""),
        parse_mode="Markdown",
    )
    logger.info(f"PharmaTech Daily (ann_id={ann_id}) approved and broadcast to {sent_count} users")


async def _handle_regenerate(query, context, ann_id: int) -> None:
    """Delete draft and trigger a new generation immediately."""
    from ...core.config import get_settings
    from sqlalchemy import select

    settings = get_settings()

    async with get_session() as session:
        result = await session.execute(
            select(Announcement).where(Announcement.id == ann_id)
        )
        ann = result.scalar_one_or_none()
        if ann:
            await session.delete(ann)

    await query.edit_message_text(
        "♻️ *Đang tạo lại bài viết mới...*\n\nVui lòng chờ trong giây lát.",
        parse_mode="Markdown",
    )

    # Trigger regeneration
    try:
        from ...core.config import get_settings
        from ...summarizer import GeminiSummarizer
        from ...scheduler.jobs import _generate_pharma_daily

        settings = get_settings()
        summarizer = GeminiSummarizer(settings)
        await _generate_pharma_daily(settings, summarizer, force=True)
    except Exception as e:
        logger.error(f"Regeneration failed: {e}", exc_info=True)
        await context.bot.send_message(
            chat_id=query.message.chat.id,
            text=f"❌ Tạo lại thất bại: {e}",
        )


def _format_pharma_daily_message(ann: Announcement) -> str:
    """Format PharmaTech Daily announcement for broadcast."""
    return ann.summary or ann.title
