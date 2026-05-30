"""Telegram bot dispatcher — maps commands to handler functions."""
from __future__ import annotations

from telegram.ext import ApplicationBuilder, CommandHandler

from ..core.logging import get_logger
from .handlers import help_command, latest, sources, start, status, subscribe, unsubscribe

logger = get_logger("bot.router")


def build_router(application_builder: ApplicationBuilder) -> None:
    """Register all command handlers with the telegram.ext Application."""
    handlers = [
        CommandHandler("start", start),
        CommandHandler("help", help_command),
        CommandHandler("subscribe", subscribe),
        CommandHandler("unsubscribe", unsubscribe),
        CommandHandler("status", status),
        CommandHandler("latest", latest),
        CommandHandler("sources", sources),
    ]

    for handler in handlers:
        application_builder.add_handler(handler)

    logger.info(f"Registered {len(handlers)} command handlers")
