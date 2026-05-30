"""Structured logging setup with loguru."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger as _logger

if TYPE_CHECKING:
    from .config import _Settings


def setup_logging(settings: _Settings) -> None:
    """Configure loguru with console + rotating file output."""
    _logger.remove()

    log_level = settings.log_level

    # Console output (always)
    _logger.add(
        sys.stdout,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        level=log_level,
        colorize=True,
        backtrace=True,
        diagnose=True,
    )

    # Rotating file output
    log_file = settings.data_dir / "bot.log"
    _logger.add(
        str(log_file),
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
        level=log_level,
        rotation="10 MB",
        retention="7 days",
        compression="zip",
        backtrace=True,
        diagnose=True,
    )

    _logger.info(f"Logging initialized: {log_file}")


def get_logger(name: str | None = None):
    if name:
        return _logger.bind(name=name)
    return _logger
