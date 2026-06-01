"""Telegram command handlers for general commands: /start and /help."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from ...core.logging import get_logger

logger = get_logger("bot.handlers.commands")

WELCOME_MESSAGE = """
👋 *Chào mừng đến với PharmaTech Bot!*

Bot tự động theo dõi tin tức Cục Quản lý Dược (DAV), FDA, EMA và phân tích chuyên sâu về khoa học dược phẩm — mọi thứ dành riêng cho người làm nghề.

*📋 Các lệnh:*

▸ /start — Thông tin giới thiệu
▸ /help — Hướng dẫn sử dụng
▸ /ping — Kiểm tra bot còn chạy không
▸ /subscribe — Đăng ký nhận thông báo
▸ /unsubscribe — Hủy đăng ký
▸ /status — Kiểm tra trạng thái đăng ký
▸ /sources — Chọn nguồn tin muốn nhận
▸ /latest [n] — Xem n thông báo mới nhất (mặc định: 5)

💡 Dùng /sources để bật nguồn *PharmaTech Daily* — bài phân tích khoa học dược do AI biên soạn mỗi ngày!

*🔒 Quyền riêng tư:* Bot chỉ lưu chat\_id để gửi thông báo.

Bắt đầu bằng cách gõ /subscribe nhé!
"""

HELP_MESSAGE = """
📖 *Hướng dẫn sử dụng PharmaTech Bot*

*🤖 Giới thiệu*
Bot tự động cào tin tức từ DAV, FDA, EMA và sử dụng AI (Gemini) để tóm tắt và tạo bài phân tích chuyên sâu về khoa học dược — cả kỹ thuật bào chế lẫn kinh tế dược phẩm.

*⏰ Tần suất hoạt động*
• Kiểm tra nguồn tin mỗi vài giờ
• Gửi thông báo theo lịch đã cấu hình
• PharmaTech Daily: bài phân tích mới mỗi buổi sáng (sau khi Admin duyệt)

*📋 Lệnh chi tiết*

/ping — Kiểm tra bot còn chạy.

/subscribe — Đăng ký nhận thông báo. Sau khi đăng ký, bạn nhận tin khi có vi phạm mới từ DAV.

/unsubscribe — Hủy đăng ký. Sẽ không nhận thông báo nào nữa.

/status — Xem trạng thái đăng ký và các nguồn đang bật.

/sources — Bật/tắt từng nguồn tin: DAV, FDA, EMA, PRAC và PharmaTech Daily.

/latest [n] — Xem n thông báo mới nhất ngay lập tức. Ví dụ: /latest 10

*🔬 PharmaTech Daily*
Mỗi ngày, AI sẽ nghiên cứu và biên soạn một bài phân tích chuyên sâu luân phiên:
• Thứ 2, 4, 6: 💡 Sáng tạo Bào chế & Tá dược
• Thứ 3, 5: 📈 Kinh tế Dược & Patent Cliff
• Thứ 7, CN: 🔬 Lâm sàng & Sinh học

Bật nguồn này qua /sources → PharmaTech Daily.

*⚠️ Lưu ý*
• Thông báo được tóm tắt/tạo bằng AI, hãy kiểm tra nguồn gốc để xác nhận.
• Bài PharmaTech Daily được Admin duyệt trước khi gửi — đảm bảo chất lượng.
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
    """Handle /testnotify — admin-only: run a manual scrape and send notifications."""
    from ...core.config import get_settings
    chat_id = update.effective_chat.id
    settings = get_settings()

    # Restrict to admin only
    if settings.admin_telegram_chat_id and chat_id != settings.admin_telegram_chat_id:
        await update.message.reply_text(
            "🔒 Lệnh này chỉ dành cho Admin."
        )
        return

    logger.info(f"/testnotify from admin {chat_id}")
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
