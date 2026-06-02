"""Telegram command handlers for subscription and source management."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from ...core.database import get_session
from ...core.logging import get_logger
from ...core.models import Subscription
from sqlalchemy import select

logger = get_logger("bot.handlers.subscription")

# ── All available sources with display metadata ────────────────────────────────

AVAILABLE_SOURCES = [
    ("dav_violation",    "🇻🇳", "DAV Việt Nam — Vi phạm",       "Thông báo xử lý vi phạm hành chính"),
    ("dav_registration", "🇻🇳", "DAV Việt Nam — Đăng ký thuốc",  "Danh sách thuốc được cấp phép lưu hành"),
    ("dav_gmp",          "🎖️", "DAV Việt Nam — Đạt chuẩn GMP",   "Công bố cơ sở đạt WHO-GMP hoặc cơ sở nước ngoài đáp ứng GMP"),
    ("fda_enforcement",  "🇺🇸", "FDA — Drug Recall",              "Thuốc bị thu hồi (Class I)"),
    ("fda_shortage",     "⚠️",  "FDA — Drug Shortage",            "Thuốc khan hiếm"),
    ("fda_approval",     "✅",  "FDA — New Approval",              "Thuốc mới được phê duyệt"),
    ("ema",              "🇪🇺", "EMA — Tin tức",                  "Tin tức EMA (thuốc mới, vaccine,...)"),
    ("ema_shortage",     "🚫",  "EMA — Thiếu thuốc",             "Thông báo thiếu thuốc tại EU"),
    ("prac",             "⚕️",  "EMA — PRAC Signals",             "Tín hiệu an toàn từ PRAC"),
    ("pharma_daily",     "🔬",  "PharmaTech Daily — Bài phân tích", "Bài phân tích chuyên sâu về khoa học dược do AI biên soạn"),
]

# Default enabled sources for new subscribers
DEFAULT_SOURCES = {"dav_violation", "dav_registration"}


def _render_sources_keyboard(current: set[str]) -> list[list[dict]]:
    """Render inline keyboard for source toggles."""
    rows = []
    for key, emoji, label, _ in AVAILABLE_SOURCES:
        icon = "✅" if key in current else "⬜"
        display = f"{icon} {emoji} {label}"
        rows.append([{"text": display, "callback_data": f"sources_toggle:{key}"}])
    rows.append([{"text": "💾 Lưu thay đổi", "callback_data": "sources_save"}])
    return rows


# ── Command handlers ───────────────────────────────────────────────────────────

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /subscribe — register or reactivate a subscription for this chat."""
    chat_id = update.effective_chat.id
    username = update.effective_user.full_name or update.effective_user.username

    async with get_session() as session:
        result = await session.execute(
            select(Subscription).where(Subscription.chat_id == chat_id)
        )
        existing = result.scalar_one_or_none()

        if existing:
            if existing.is_active:
                await update.message.reply_text(
                    "✅ Bạn đã đăng ký nhận thông báo rồi.\n"
                    "Dùng /sources để chọn nguồn tin."
                )
                return
            existing.is_active = True
            existing.username = username
            existing.set_enabled_sources(DEFAULT_SOURCES)
            await update.message.reply_text(
                "🔔 Đăng ký lại thành công!\n"
                "Mặc định bạn sẽ nhận thông báo từ:\n"
                "  🇻🇳 DAV Việt Nam — Vi phạm\n"
                "  🇻🇳 DAV Việt Nam — Đăng ký thuốc\n\n"
                "Dùng /sources để thêm FDA / EMA."
            )
            logger.info(f"Subscription reactivated: {chat_id}")
        else:
            new_sub = Subscription(
                chat_id=chat_id,
                username=username,
                is_active=True,
            )
            new_sub.set_enabled_sources(DEFAULT_SOURCES)
            session.add(new_sub)
            await update.message.reply_text(
                "🎉 Đăng ký thành công!\n\n"
                "Bạn sẽ nhận thông báo từ:\n"
                "  🇻🇳 DAV Việt Nam — Vi phạm\n"
                "  🇻🇳 DAV Việt Nam — Đăng ký thuốc\n\n"
                "Dùng /sources để bật thêm FDA / EMA."
            )
            logger.info(f"New subscription created: {chat_id}")


async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /unsubscribe — deactivate the subscription for this chat."""
    chat_id = update.effective_chat.id

    async with get_session() as session:
        result = await session.execute(
            select(Subscription).where(Subscription.chat_id == chat_id)
        )
        existing = result.scalar_one_or_none()

        if not existing or not existing.is_active:
            await update.message.reply_text(
                "ℹ️ Bạn chưa đăng ký nhận thông báo.\n"
                "Dùng /subscribe để đăng ký."
            )
            return

        existing.is_active = False
        await update.message.reply_text(
            "🔕 Đã hủy đăng ký thành công.\n"
            "Bạn sẽ không nhận được thông báo nào nữa.\n"
            "Dùng /subscribe nếu muốn đăng ký lại."
        )
        logger.info(f"Subscription deactivated: {chat_id}")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status — show current subscription status."""
    chat_id = update.effective_chat.id

    async with get_session() as session:
        result = await session.execute(
            select(Subscription).where(Subscription.chat_id == chat_id)
        )
        existing = result.scalar_one_or_none()

        if existing and existing.is_active:
            created = existing.created_at.strftime("%d/%m/%Y %H:%M") if existing.created_at else "N/A"
            enabled = existing.get_enabled_sources()

            source_lines = []
            for key, emoji, label, desc in AVAILABLE_SOURCES:
                if key in enabled:
                    source_lines.append(f"  {emoji} {label}")

            await update.message.reply_text(
                f"✅ *Trạng thái: Đang hoạt động*\n\n"
                f"👤 {update.effective_user.full_name}\n"
                f"🕐 Đăng ký từ: {created}\n\n"
                f"📡 Nguồn đang nhận:\n" + "\n".join(source_lines) + "\n\n"
                f"Dùng /sources để thay đổi nguồn tin.",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(
                "❌ *Chưa đăng ký*\n\n"
                "Dùng /subscribe để bắt đầu.",
                parse_mode="Markdown",
            )


async def sources(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /sources — show interactive source selector."""
    chat_id = update.effective_chat.id

    async with get_session() as session:
        result = await session.execute(
            select(Subscription).where(Subscription.chat_id == chat_id)
        )
        existing = result.scalar_one_or_none()

        if not existing or not existing.is_active:
            await update.message.reply_text(
                "⚠️ Bạn chưa đăng ký.\n"
                "Dùng /subscribe trước, sau đó dùng /sources."
            )
            return

        enabled = existing.get_enabled_sources()

        lines = [
            "⚙️ *Quản lý nguồn tin*\n\n"
            "Chọn nguồn bạn muốn nhận thông báo:\n\n"
        ]
        for key, emoji, label, desc in AVAILABLE_SOURCES:
            status_icon = "✅" if key in enabled else "⬜"
            lines.append(f"{status_icon} {emoji} *{label}*\n    {desc}\n")

        lines.append(
            "\n💡 *Nhấn nút bên dưới* để bật/tắt từng nguồn.\n"
            "Hai nguồn DAV mặc định bật cho tất cả users."
        )

        keyboard = _render_sources_keyboard(enabled)

        await update.message.reply_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup={"inline_keyboard": keyboard},
        )


# ── Inline keyboard callback handler ─────────────────────────────────────────────

# In-memory state: user_id → set of enabled source keys (pending changes)
_pending_sources: dict[int, set[str]] = {}


async def sources_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline keyboard button presses for source toggles."""
    query = update.callback_query
    if query is None:
        return

    user_id = query.from_user.id
    data = query.data or ""

    await query.answer()

    async with get_session() as session:
        result = await session.execute(
            select(Subscription).where(Subscription.chat_id == query.message.chat.id)
        )
        existing = result.scalar_one_or_none()
        if not existing or not existing.is_active:
            await query.edit_message_text("⚠️ Phiên đã hết hạn. Dùng /sources để mở lại.")
            return

        current = existing.get_enabled_sources()

        if data == "sources_save":
            # User confirmed — persist pending changes
            pending = _pending_sources.pop(user_id, current)
            # Always keep DAV sources enabled
            safe = pending | {"dav_violation", "dav_registration"}
            existing.set_enabled_sources(safe)
            await query.edit_message_text(
                "✅ Đã lưu cài đặt nguồn tin!\n\n"
                f"📡 Bạn đang nhận tin từ {len(safe)} nguồn:\n"
                + "\n".join(
                    f"  {emoji} {label}"
                    for key, emoji, label, _ in AVAILABLE_SOURCES
                    if key in safe
                ),
                parse_mode="Markdown",
            )
            logger.info(f"Sources updated: {query.message.chat.id}")
            return

        if data.startswith("sources_toggle:"):
            key = data.split(":", 1)[1]

            # Initialize pending state from DB on first toggle
            if user_id not in _pending_sources:
                _pending_sources[user_id] = set(current)

            pending = _pending_sources[user_id]

            if key in pending:
                # Can't disable DAV sources
                if key in {"dav_violation", "dav_registration"}:
                    await query.answer("⚠️ Không thể tắt nguồn DAV.", show_alert=True)
                    return
                pending.discard(key)
            else:
                pending.add(key)

            _pending_sources[user_id] = pending

            # Re-render keyboard with updated state
            keyboard = _render_sources_keyboard(pending)
            lines = [
                "⚙️ *Quản lý nguồn tin*\n\n"
                "✅ = đang bật  |  ⬜ = đang tắt\n\n"
            ]
            for k, emoji, label, desc in AVAILABLE_SOURCES:
                icon = "✅" if k in pending else "⬜"
                lines.append(f"{icon} {emoji} *{label}*\n   {desc}")

            lines.append(
                "\n💡 *Nhấn 💾 Lưu thay đổi* để xác nhận.\n"
                "Hai nguồn DAV mặc định luôn bật."
            )

            await query.edit_message_text(
                "\n".join(lines),
                parse_mode="Markdown",
                reply_markup={"inline_keyboard": keyboard},
            )

