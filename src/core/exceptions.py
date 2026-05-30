"""Custom application exceptions."""


class BotError(Exception):
    """Base exception for all bot errors."""

    def __init__(self, message: str, *, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.cause = cause


class ScraperError(BotError):
    """Raised when scraping the DAV website fails."""


class PDFParseError(ScraperError):
    """Raised when a PDF cannot be parsed or has no extractable text."""


class PDFSizeError(ScraperError):
    """Raised when a PDF exceeds the configured size limit."""


class GeminiError(BotError):
    """Raised when Gemini API call fails."""


class GeminiQuotaError(GeminiError):
    """Raised when Gemini API quota is exceeded."""


class NotificationError(BotError):
    """Raised when sending a Telegram notification fails."""
