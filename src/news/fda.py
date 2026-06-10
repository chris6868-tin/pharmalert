"""FDA news sources via openFDA API — Enforcement, Shortages, Approvals."""
from __future__ import annotations

import httpx

from ..core.exceptions import ScraperError
from ..core.logging import get_logger
from .base import NewsItem, NewsSource, NewsSourceBase

logger = get_logger("news.fda")

# ── FDA Drug Enforcement (Class I Recalls) ────────────────────────────────────

class FDAEnforcementFetcher(NewsSourceBase):
    """Fetch FDA drug Class I enforcement/recall data via openFDA API."""

    API_URL = "https://api.fda.gov/drug/enforcement.json"

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        super().__init__(NewsSource.FDA_ENFORCEMENT)
        self._client = http_client

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        return self._client

    @property
    def emoji(self) -> str:
        return "🇺🇸"

    @property
    def label(self) -> str:
        return "FDA Drug Recall"

    async def fetch_new_items(self):
        client = await self._get_client()
        try:
            url = f"{self.API_URL}?search=classification:\"Class%20I\"&limit=20"
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as e:
            raise ScraperError(f"FDA Enforcement HTTP {e.response.status_code}", cause=e) from e
        except httpx.RequestError as e:
            raise ScraperError(f"FDA Enforcement request failed", cause=e) from e

        results = data.get("results", [])
        logger.info(f"FDA Enforcement: {len(results)} records")

        for record in results:
            recall_number = record.get("recall_number", "")
            if not recall_number:
                continue

            product_description = record.get("product_description", "")
            reason = record.get("reason_for_recall", "Không có thông tin")
            firm = record.get("recalling_firm", "Không xác định")
            city = record.get("city", "")
            state = record.get("state", "")
            country = record.get("country", "")
            recall_date = record.get("recall_initiation_date", "")
            status = record.get("status", "")

            formatted_date = ""
            if recall_date and len(recall_date) == 8:
                formatted_date = f"{recall_date[6:8]}/{recall_date[4:6]}/{recall_date[0:4]}"

            location = ", ".join(p for p in [city, state, country] if p)

            reason_clean = reason.replace("\n", " ").replace("  ", " ").strip()
            parts = []
            if firm and firm != "Không xác định":
                parts.append(f"🏢 *Công ty:* {firm}")
            if location:
                parts.append(f"📍 *Địa điểm:* {location}")
            if reason_clean and reason_clean != "Không có thông tin":
                parts.append(f"⚠️ *Lý do thu hồi:* {reason_clean}")
            if status:
                parts.append(f"📊 *Tình trạng:* {status}")

            async for item in self._track_and_yield(NewsItem(
                source=NewsSource.FDA_ENFORCEMENT,
                external_id=f"fda-enf-{recall_number}",
                title=f"🇺🇸 [FDA Recall] #{recall_number} — {firm}",
                url="https://www.fda.gov/safety/recalls-market-withdrawals-safety-alerts",
                published_date=formatted_date or None,
                summary="\n".join(parts) if parts else None,
                raw_content=product_description,
            )):
                yield item

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


# ── FDA Drug Shortages ────────────────────────────────────────────────────────

import re


class FDAShortageFetcher(NewsSourceBase):
    """Fetch current FDA drug shortages via openFDA API."""

    API_URL = "https://api.fda.gov/drug/shortages.json"

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        super().__init__(NewsSource.FDA_SHORTAGE)
        self._client = http_client

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        return self._client

    @property
    def emoji(self) -> str:
        return "⚠️"

    @property
    def label(self) -> str:
        return "FDA Drug Shortage"

    async def fetch_new_items(self):
        client = await self._get_client()
        try:
            url = f"{self.API_URL}?sort=update_date:desc&limit=15"
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as e:
            raise ScraperError(f"FDA Shortage HTTP {e.response.status_code}", cause=e) from e
        except httpx.RequestError as e:
            raise ScraperError(f"FDA Shortage request failed", cause=e) from e

        results = data.get("results", [])
        logger.info(f"FDA Shortages: {len(results)} records")

        for record in results:
            generic_name = record.get("generic_name", "")
            brand_name = record.get("proprietary_name", "")
            company = record.get("company_name", "")
            status = record.get("status", "")
            shortage_reason = record.get("shortage_reason", "")
            availability = record.get("availability", "")
            updated_date = record.get("update_date", "")
            therapeutic = ", ".join(record.get("therapeutic_category", []) or [])

            if not generic_name and not brand_name:
                continue

            drug_name = brand_name if brand_name else generic_name
            display_name = f"{brand_name} ({generic_name})" if brand_name and generic_name else drug_name

            formatted_date = ""
            if updated_date and len(updated_date) == 8:
                formatted_date = f"{updated_date[6:8]}/{updated_date[4:6]}/{updated_date[0:4]}"

            parts = []
            if company:
                parts.append(f"🏢 *Nhà sản xuất:* {company}")
            if shortage_reason and shortage_reason != "Unknown":
                parts.append(f"⚠️ *Nguyên nhân:* {shortage_reason}")
            if status:
                parts.append(f"📊 *Trạng thái:* {status}")
            if availability:
                parts.append(f"📦 *Tình trạng cung ứng:* {availability}")
            if therapeutic:
                parts.append(f"💊 *Nhóm thuốc:* {therapeutic}")

            summary = "\n".join(parts) if parts else "Đang thiếu thuốc trên thị trường Mỹ."

            # Construct stable external ID based on names and status, to ignore minor update_date changes
            generic_clean = re.sub(r"[^a-zA-Z0-9-]", "", generic_name.strip().lower().replace(" ", "-"))[:50]
            brand_clean = re.sub(r"[^a-zA-Z0-9-]", "", brand_name.strip().lower().replace(" ", "-"))[:50]
            status_clean = re.sub(r"[^a-zA-Z0-9-]", "", status.strip().lower().replace(" ", "-"))[:30]

            if generic_clean:
                external_id = f"fda-short-{generic_clean}-{brand_clean}-{status_clean}"
            else:
                external_id = f"fda-short-brand-{brand_clean}-{status_clean}"

            while "--" in external_id:
                external_id = external_id.replace("--", "-")
            external_id = external_id.strip("-")

            async for item in self._track_and_yield(NewsItem(
                source=NewsSource.FDA_SHORTAGE,
                external_id=external_id,
                title=f"⚠️ [FDA Shortage] {display_name}",
                url="https://www.accessdata.fda.gov/scripts/drugshortages/",
                published_date=formatted_date or None,
                summary=summary,
            )):
                yield item

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


# ── FDA New Drug Approvals ────────────────────────────────────────────────────

class FDAApprovalFetcher(NewsSourceBase):
    """Fetch latest FDA new drug approvals via Drugs@FDA API."""

    API_URL = "https://api.fda.gov/drug/drugsfda.json"

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        super().__init__(NewsSource.FDA_APPROVAL)
        self._client = http_client

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        return self._client

    @property
    def emoji(self) -> str:
        return "✅"

    @property
    def label(self) -> str:
        return "FDA New Approval"

    async def fetch_new_items(self):
        """Fetch recently approved drugs (last 60 days) from Drugs@FDA."""
        import datetime

        client = await self._get_client()
        # Get latest approvals by sorting on approval_date desc
        try:
            # openFDA Drugs@FDA doesn't support sorting directly via search param
            # So we fetch recent approvals and filter client-side
            url = f"{self.API_URL}?limit=50"
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as e:
            raise ScraperError(f"FDA Approval HTTP {e.response.status_code}", cause=e) from e
        except httpx.RequestError as e:
            raise ScraperError(f"FDA Approval request failed", cause=e) from e

        results = data.get("results", [])
        cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=60)).strftime("%Y%m%d")

        logger.info(f"FDA Approvals: fetched {len(results)} records, filtering last 60 days")

        for record in results:
            submissions = record.get("submissions", [])
            if not submissions:
                continue

            # Find most recent approval submission
            latest_sub = submissions[0]
            approval_date_raw = latest_sub.get("approval_date", "")
            submission_type = latest_sub.get("submission_class_code", "")

            # Only include actual approvals (not supplements, etc.)
            if not approval_date_raw or approval_date_raw < cutoff:
                continue

            brand_name = record.get("openfda", {}).get("brand_name", [""])[0]
            generic_name = record.get("openfda", {}).get("generic_name", [""])[0]
            sponsor = record.get("sponsor_name", "")
            indication = latest_sub.get("indication", "") or record.get("products", [{}])[0].get("active_ingredients", "")

            if not brand_name and not generic_name:
                continue

            if approval_date_raw and len(approval_date_raw) == 8:
                formatted_date = f"{approval_date_raw[6:8]}/{approval_date_raw[4:6]}/{approval_date_raw[0:4]}"
            else:
                formatted_date = approval_date_raw

            drug_name = brand_name if brand_name else generic_name
            display_name = f"{brand_name} ({generic_name})" if brand_name and generic_name else drug_name

            parts = []
            if sponsor:
                parts.append(f"🏢 *Nhà tài trợ:* {sponsor}")
            if submission_type:
                parts.append(f"📋 *Loại đơn:* {submission_type}")
            if indication:
                parts.append(f"💡 *Chỉ định:* {indication[:200]}")

            async for item in self._track_and_yield(NewsItem(
                source=NewsSource.FDA_APPROVAL,
                external_id=f"fda-appr-{approval_date_raw}-{drug_name[:30]}".lower().replace(" ", "-"),
                title=f"✅ [FDA Approval] {display_name}",
                url="https://www.fda.gov/drugs/drug-approvals-and-databases/drugsfda-data-files",
                published_date=formatted_date or None,
                summary="\n".join(parts) if parts else None,
            )):
                yield item

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
