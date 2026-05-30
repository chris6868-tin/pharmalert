"""Abstract base class for international news sources."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import AsyncIterator

from ..core.logging import get_logger

logger = get_logger("news.base")


class NewsSource(Enum):
    # DAV Vietnam
    DAV_VIOLATION = "dav_violation"
    DAV_REGISTRATION = "dav_registration"
    # FDA USA
    FDA_ENFORCEMENT = "fda_enforcement"
    FDA_SHORTAGE = "fda_shortage"
    FDA_APPROVAL = "fda_approval"
    MEDWATCH = "medwatch"
    # EMA Europe
    EMA = "ema"
    EMA_SHORTAGE = "ema_shortage"
    PRAC = "prac"

    @classmethod
    def all_keys(cls) -> list[str]:
        return [s.value for s in cls]


@dataclass
class NewsItem:
    """A single news item from any source."""
    source: NewsSource
    external_id: str          # unique ID from source
    title: str
    url: str
    published_date: str | None
    summary: str | None = None
    raw_content: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)


class NewsSourceBase(ABC):
    """
    Abstract base for any news source.
    Subclasses implement _fetch_items() to return new NewsItems since last check.
    """

    def __init__(self, source: NewsSource) -> None:
        self._source = source
        self._seen_ids: set[str] = set()

    @property
    def source(self) -> NewsSource:
        return self._source

    @property
    @abstractmethod
    def emoji(self) -> str:
        """Emoji used in Telegram messages for this source."""
        raise NotImplementedError

    @property
    @abstractmethod
    def label(self) -> str:
        """Human-readable label for this source."""
        raise NotImplementedError

    @abstractmethod
    async def fetch_new_items(self) -> AsyncIterator[NewsItem]:
        """
        Yield new news items since last fetch.
        Subclasses handle deduplication internally.
        """
        raise NotImplementedError

    async def _track_and_yield(
        self,
        item: NewsItem,
    ) -> AsyncIterator[NewsItem]:
        """Yield item only if we haven't seen its ID before."""
        if item.external_id not in self._seen_ids:
            self._seen_ids.add(item.external_id)
            yield item
        else:
            logger.debug(
                f"Skipping duplicate item {item.external_id} from {self._source.value}",
            )
