"""Telegram command handler for /latest — show recent announcements on demand."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from ...core.database import get_session
from ...core.logging import get_logger
from ...core.models import Announcement

logger = get_logger("bot.handlers.notifications")

MAX_LATEST = 20
DEFAULT_LATEST = 5


def _format_announcement(ann: Announcement, index: int) -> str:
    date_str = f"📅 {ann.published_date}" if ann.published_date else "📅 Không rõ ngày"
    summary = ann.summary or "_Không có tóm tắt_"
    processed_str = (
        ann.processed_at.strftime("%d/%m/%Y %H:%M")
        if ann.processed_at else "Đang xử lý"
    )

    return (
        f"──────────────\n"
        f"#{index} 📢 *{ann.title}*\n"
        f"{date_str}\n"
        f"⏱️ Tóm tắt lúc: {processed_str}\n\n"
        f"{summary}\n\n"
        f"🔗 [Xem chi tiết]({ann.url})"
    )


async def latest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /latest [n] — fetch and display the most recent announcements."""
    chat_id = update.effective_chat.id

    # Parse optional count argument
    n = DEFAULT_LATEST
    if context.args:
        try:
            n = int(context.args[0])
            n = max(1, min(n, MAX_LATEST))
        except ValueError:
            await update.message.reply_text(
                f"Số lượng không hợp lệ. Mặc định hiển thị {DEFAULT_LATEST} thông báo.\n"
                f"Dùng /latest {DEFAULT_LATEST} để xem {DEFAULT_LATEST} thông báo mới nhất."
            )
            return

    async with get_session() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(Announcement)
            .where(Announcement.summary.isnot(None))
            .order_by(Announcement.processed_at.desc())
            .limit(n)
        )
        announcements = list(result.scalars().all())

    if not announcements:
        await update.message.reply_text(
            "📭 Hiện chưa có thông báo nào được xử lý.\n\n"
            "Bot đang trong quá trình kiểm tra trang DAV lần đầu. "
            "Vui lòng quay lại sau vài phút."
        )
        logger.debug(f"No announcements found for /latest, chat_id={chat_id}")
        return

    logger.info(
        f"Serving /latest {len(announcements)} announcements to {chat_id}",
    )

    header = (
        f"📋 *{len(announcements)} thông báo mới nhất*\n\n"
        "──────────────\n"
    )
    await update.message.reply_text(header, parse_mode="Markdown")

    for i, ann in enumerate(announcements, start=1):
        msg = _format_announcement(ann, i)
        await update.message.reply_text(msg, parse_mode="Markdown", disable_web_page_preview=True)

    footer = (
        f"\n──────────────\n"
        f"🔗 [Trang DAV](https://dav.gov.vn/thong-tin-xu-ly-vi-pham-cn5.html)"
    )
    await update.message.reply_text(footer, parse_mode="Markdown", disable_web_page_preview=True)
