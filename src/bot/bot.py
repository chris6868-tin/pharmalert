"""Telegram bot initialization and graceful lifecycle management."""
from __future__ import annotations

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    Updater,
)

from ..core.logging import get_logger
from .handlers import help_command, latest, ping, start, status, subscribe, test_notify, unsubscribe, sources
from .handlers.subscription import sources_callback

logger = get_logger("bot")


def create_bot(token: str) -> tuple[Application, Updater]:
    """
    Build and return (Application, Updater) for the telegram bot.
    Registers all handlers, sets up error handler.
    """
    app = (
        ApplicationBuilder()
        .token(token)
        .read_timeout(30)
        .write_timeout(30)
        .connect_timeout(10)
        .pool_timeout(30)
        .build()
    )

    updater = app.updater
    if updater is None:
        raise RuntimeError("Failed to build Telegram Updater from Application")

    # Register command handlers
    for cmd, fn in [
        ("start", start),
        ("help", help_command),
        ("ping", ping),
        ("testnotify", test_notify),
        ("subscribe", subscribe),
        ("unsubscribe", unsubscribe),
        ("status", status),
        ("latest", latest),
        ("sources", sources),
    ]:
        app.add_handler(CommandHandler(cmd, fn))
        logger.info(f"Registered /{cmd}")

    logger.info("Registered 9 command handlers")

    # Register callback handler for inline keyboard (source toggles)
    app.add_handler(CallbackQueryHandler(sources_callback, pattern=r"sources_(toggle|save):?"))

    # Global error handler
    async def error_handler(update: Update | object, context: ContextTypes.DEFAULT_TYPE) -> None:
        if isinstance(update, Update):
            chat_id = update.effective_chat.id if update.effective_chat else "unknown"
            user_id = update.effective_user.id if update.effective_user else "unknown"
        else:
            chat_id = user_id = "unknown"

        logger.error(
            f"Telegram error while handling update (chat_id={chat_id}, user_id={user_id}, "
            f"update_id={update.update_id if isinstance(update, Update) else None}): {context.error}",
        )

        if isinstance(update, Update) and update.effective_chat:
            try:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=(
                        "⚠️ Đã xảy ra lỗi khi xử lý yêu cầu của bạn.\n"
                        "Vui lòng thử lại sau."
                    ),
                )
            except Exception:
                pass

    app.add_error_handler(error_handler)

    logger.info(f"Telegram bot created, token prefix: {token[:8]}...")
    return app, updater
