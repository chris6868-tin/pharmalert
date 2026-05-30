"""Telegram command handlers for general commands: /start and /help."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from ...core.logging import get_logger

logger = get_logger("bot.handlers.commands")

WELCOME_MESSAGE = """
👋 *Chào mừng đến với Bot Thông báo DAV!*

Bot này tự động theo dõi trang web của Cục Quản lý Dược (DAV) — Bộ Y tế Việt Nam và gửi thông báo khi có thông báo xử lý vi phạm hành chính mới.

*📋 Các lệnh có sẵn:*

▸ /start — Thông tin giới thiệu
▸ /help — Hướng dẫn sử dụng
▸ /ping — Kiểm tra bot còn chạy
▸ /testnotify — Chạy thử scraping và gửi thông báo test
▸ /subscribe — Đăng ký nhận thông báo hàng ngày
▸ /unsubscribe — Hủy đăng ký
▸ /status — Kiểm tra trạng thái đăng ký
▸ /latest [n] — Xem n thông báo mới nhất (mặc định: 5, tối đa: 20)

*🔒 Quyền riêng tư:*
Bot chỉ lưu trữ chat_id của bạn để gửi thông báo. Không thu thập dữ liệu cá nhân khác.

Bắt đầu bằng cách dùng /subscribe để đăng ký nhận tin nhắn!
"""

HELP_MESSAGE = """
📖 *Hướng dẫn sử dụng Bot DAV*

*🤖 Giới thiệu*
Bot tự động tải danh sách thông báo xử lý vi phạm hành chính từ trang DAV, đọc nội dung file PDF và tóm tắt tự động bằng AI (Gemini), sau đó gửi thông báo đến bạn.

*⏰ Tần suất hoạt động*
• Kiểm tra trang DAV mỗi 60 phút
• Gửi tổng hợp thông báo mới nhất lúc 08:00 mỗi ngày

*📋 Lệnh chi tiết*

/ping — Kiểm tra bot còn chạy.

/testnotify — Chạy test scraping và gửi thông báo đến các subscriber đang hoạt động.

/subscribe — Đăng ký nhận thông báo. Sau khi đăng ký, bạn sẽ nhận được tin nhắn mỗi khi có thông báo vi phạm mới.

/unsubscribe — Hủy đăng ký. Bạn sẽ không nhận được thông báo nào nữa.

/status — Xem trạng thái hiện tại của đăng ký.

/latest — Xem các thông báo mới nhất ngay lập tức. Ví dụ: /latest 10 để xem 10 thông báo gần nhất.

*⚠️ Lưu ý*
• Thông báo được tóm tắt tự động bằng AI, có thể không hoàn toàn chính xác 100%. Hãy kiểm tra file PDF gốc để xác nhận.
• Nếu bot không phản hồi, hãy thử /subscribe lại.
"""


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start — send welcome message."""
    logger.info(
        f"/start from {update.effective_chat.id}",
    )
    await update.message.reply_text(WELCOME_MESSAGE)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help — send help message."""
    logger.info(
        f"/help from {update.effective_chat.id}",
    )
    await update.message.reply_text(HELP_MESSAGE)


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /ping — confirm the bot is running."""
    logger.info(f"/ping from {update.effective_chat.id}")
    await update.message.reply_text("🏓 Bot đang chạy!")


async def test_notify(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /testnotify — run a manual scrape and send notifications."""
    chat_id = update.effective_chat.id
    logger.info(f"/testnotify from {chat_id}")
    await context.bot.send_message(chat_id=chat_id, text="🧪 Đang chạy test scraping và gửi thông báo. Vui lòng chờ...")

    async def _run_test_notify() -> None:
        from src.core.config import get_settings
        from src.scraper import DAVFetcher
        from src.summarizer import GeminiSummarizer
        from src.scheduler.jobs import _scrape_dav, _notify_subscribers

        settings = get_settings()
        fetcher = DAVFetcher(settings)
        summarizer = GeminiSummarizer(settings)

        try:
            await _scrape_dav(settings, fetcher, summarizer)
            await _notify_subscribers(settings, settings.telegram_bot_token, summarizer)
            await context.bot.send_message(
                chat_id=chat_id,
                text="✅ Test notify đã hoàn tất. Kiểm tra log để biết chi tiết."
            )
        except Exception as e:
            logger.error(f"/testnotify failed: {e}", exc_info=True)
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ Test notify thất bại: {e}"
            )

    # Await directly (not create_task/ensure_future) — SQLAlchemy async sessions
    # must run in the same asyncio Task that owns the event loop greenlet context.
    # Spawning a new task breaks that context and causes "greenlet_spawn" errors.
    await _run_test_notify()
