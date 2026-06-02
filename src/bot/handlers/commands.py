"""Telegram command handlers for general commands: /start and /help."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from sqlalchemy import select, or_, func
from ...core.models import GmpFactory
from ...core.database import get_session
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
▸ /gmp <tên_cơ_sở> — Tìm kiếm cơ sở đạt chuẩn GMP / ĐKKD dược
▸ /gmpstats — Xem thống kê cơ sở dữ liệu GMP

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

/gmp <tên_cơ_sở> — Tìm kiếm nhanh cơ sở sản xuất dược đạt tiêu chuẩn GMP (WHO, EU, PIC/S, v.v.) hoặc có giấy chứng nhận ĐKKD dược. Ví dụ: `/gmp Imexpharm`

/gmpstats — Xem tổng quan thống kê về số lượng và phân loại các cơ sở đạt chuẩn GMP tại Việt Nam.

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


async def gmp_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /gmp <query> — search for GMP factories by name or address."""
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text(
            "🔍 *Cách dùng lệnh:* `/gmp <tên hoặc địa chỉ cơ sở>`\n"
            "Ví dụ: `/gmp Imexpharm` hoặc `/gmp Bình Dương`\n\n"
            "Bot sẽ tìm kiếm các cơ sở sản xuất đạt tiêu chuẩn GMP hoặc có giấy chứng nhận ĐKKD dược.",
            parse_mode="Markdown"
        )
        return

    query_str = " ".join(context.args).strip()
    if len(query_str) < 2:
        await update.message.reply_text("⚠️ Vui lòng nhập từ khóa tìm kiếm có độ dài từ 2 ký tự trở lên.")
        return

    logger.info(f"/gmp search '{query_str}' from {chat_id}")
    await update.message.reply_text(f"🔍 Đang tìm kiếm cơ sở GMP khớp với *'{query_str}'*...", parse_mode="Markdown")

    async with get_session() as session:
        stmt = select(GmpFactory).where(
            or_(
                GmpFactory.factory_name.ilike(f"%{query_str}%"),
                GmpFactory.address.ilike(f"%{query_str}%")
            )
        ).limit(10)  # Giới hạn 10 kết quả

        result = await session.execute(stmt)
        factories = list(result.scalars().all())

        if not factories:
            await update.message.reply_text(f"❌ Không tìm thấy cơ sở nào khớp với từ khóa *'{query_str}'*.", parse_mode="Markdown")
            return

        msg_parts = [
            f"🔍 *Kết quả tìm kiếm cho '{query_str}' ({len(factories)} kết quả đầu):*\n"
        ]
        for idx, f in enumerate(factories, 1):
            if f.category == "gmp_manufacturing":
                msg_parts.append(
                    f"🏢 *{idx}. {f.factory_name}*\n"
                    f"📍 *Địa chỉ:* {f.address}\n"
                    f"🔬 *Tiêu chuẩn:* {f.standard or 'WHO-GMP'}\n"
                    f"🏛️ *Cơ quan cấp:* {f.authority or 'N/A'}\n"
                    f"📋 *Phạm vi:* {f.scope or 'N/A'}"
                )
            elif f.category == "gmp_foreign":
                msg_parts.append(
                    f"🏢 *{idx}. {f.factory_name}* (Nước ngoài)\n"
                    f"📍 *Địa chỉ:* {f.address}\n"
                    f"🔬 *Tiêu chuẩn:* {f.standard or 'EU-GMP'}\n"
                    f"🏛️ *Cơ quan đánh giá:* {f.authority or 'Cục Quản lý Dược'}\n"
                    f"📋 *Phạm vi:* {f.scope or 'N/A'}"
                )
            else:  # gmp_license
                msg_parts.append(
                    f"🏢 *{idx}. {f.factory_name}* (ĐKKD Dược)\n"
                    f"📍 *Địa điểm:* {f.address}\n"
                    f"👤 *Dược sĩ chuyên môn:* {f.responsible_pharmacist or 'N/A'}\n"
                    f"📄 *Số GCN:* {f.certificate_license or 'N/A'}\n"
                    f"📋 *Phạm vi:* {f.scope or 'N/A'}"
                )
            msg_parts.append("──────────────────────")

        await update.message.reply_text("\n".join(msg_parts), parse_mode="Markdown")


async def gmp_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /gmpstats — show statistics of the GMP database."""
    chat_id = update.effective_chat.id
    logger.info(f"/gmpstats from {chat_id}")

    async with get_session() as session:
        # Tổng số theo từng nhóm
        stmt = select(GmpFactory.category, func.count(GmpFactory.id)).group_by(GmpFactory.category)
        res = await session.execute(stmt)
        counts = {cat: count for cat, count in res.all()}

        # Phân loại tiêu chuẩn sản xuất trong nước
        std_stmt = (
            select(GmpFactory.standard, func.count(GmpFactory.id))
            .where(GmpFactory.category == "gmp_manufacturing")
            .group_by(GmpFactory.standard)
        )
        std_res = await session.execute(std_stmt)
        std_counts = {std: count for std, count in std_res.all()}

        total_mfg = counts.get("gmp_manufacturing", 0)
        total_lic = counts.get("gmp_license", 0)
        total_for = counts.get("gmp_foreign", 0)
        total_all = total_mfg + total_lic + total_for

        msg = [
            "🎖️ *THỐNG KÊ CƠ SỞ ĐẠT CHUẨN GMP*",
            f"Tổng số cơ sở trong cơ sở dữ liệu: *{total_all}*\n",
            f"🏭 *Cơ sở sản xuất trong nước (WHO/EU/PIC/S):* {total_mfg}",
            f"🌎 *Cơ sở sản xuất nước ngoài đáp ứng GMP:* {total_for}",
            f"📄 *Cơ sở đủ điều kiện kinh doanh dược:* {total_lic}\n",
            "🔬 *Phân loại tiêu chuẩn sản xuất trong nước:*"
        ]

        for std, cnt in sorted(std_counts.items(), key=lambda x: x[1], reverse=True):
            std_label = std if std else "Khác / Chưa phân loại"
            msg.append(f" ▸ *{std_label}:* {cnt} cơ sở")

        await update.message.reply_text("\n".join(msg), parse_mode="Markdown")
