"""PDF text extraction + Gemini-powered summarization."""
from __future__ import annotations

import base64
import io
import re
from typing import TYPE_CHECKING

import fitz          # PyMuPDF
import httpx

from ..core.exceptions import GeminiError, GeminiQuotaError, PDFParseError, PDFSizeError
from ..core.logging import get_logger

if TYPE_CHECKING:
    from ..core.config import _Settings

logger = get_logger("summarizer.gemini")

# ── PDF helpers ───────────────────────────────────────────────────────────────

def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """
    Extract all text from a PDF using PyMuPDF.
    Raises PDFParseError if the PDF is unreadable or has no text.
    """
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            if doc.page_count == 0:
                raise PDFParseError("PDF has no pages")

            parts: list[str] = []
            for page_num in range(doc.page_count):
                page = doc[page_num]
                text = page.get_text("text")
                if text.strip():
                    parts.append(f"[Trang {page_num + 1}]\n{text.strip()}")

            if not parts:
                raise PDFParseError(
                    "PDF contains no extractable text (likely a scanned image — OCR not supported)"
                )

            full_text = "\n\n".join(parts)
            logger.debug(f"Extracted {doc.page_count} pages, {len(full_text)} chars")
            return full_text
    except Exception as e:
        raise PDFParseError(f"Cannot open PDF: {e}") from e


def truncate_for_gemini(text: str, max_chars: int = 30_000) -> str:
    """Truncate text to max_chars, keeping beginning and end for context."""
    if len(text) <= max_chars:
        return text

    half = max_chars // 2
    return (
        f"[Nội dung đã được cắt ngắn — phần đầu và cuối được giữ lại]\n\n"
        f"=== PHẦN ĐẦU ===\n{text[:half]}\n\n"
        f"=== PHẦN CUỐI ===\n{text[-half:]}"
    )


# ── Gemini API ────────────────────────────────────────────────────────────────

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


SYSTEM_PROMPT = """Bạn là trợ lý chuyên tóm tắt thông báo xử lý vi phạm hành chính từ Cục Quản lý Dược (DAV) – Bộ Y tế Việt Nam.

Nhiệm vụ của bạn:
1. Đọc nội dung thông báo xử phạt vi phạm hành chính (thường là quyết định xử phạt hoặc thông báo thu hồi).
2. Trích xuất và trình bày các thông tin quan trọng theo format sau:

**THÔNG BÁO XỬ PHẠT VI PHẠM HÀNH CHÍNH**

📋 *Tên đơn vị/người vi phạm:* ...
📅 *Ngày ban hành:* ...
⚖️ *Hành vi vi phạm:* ...
💰 *Mức phạt:* ...
📍 *Địa điểm xử phạt:* ...
📌 *Căn cứ pháp lý:* ...
⏰ *Thời hạn thực hiện:* ...

TÓM TẮT: 2-3 câu tổng kết ngắn gọn.

Quy tắc:
- Viết bằng tiếng Việt
- Nếu không tìm thấy một trường thông tin, ghi rõ "Không xác định được"
- Giữ tone trung lập, chính thức
- Chỉ trích xuất thông tin có trong văn bản, không bịa đặt
"""


def _build_gemini_request(text: str, model: str) -> dict:
    return {
        "contents": [{
            "parts": [{"text": text}]
        }],
        "systemInstruction": {
            "parts": [{"text": SYSTEM_PROMPT}]
        },
        "generationConfig": {
            "temperature": 0.3,
            "topP": 0.8,
            "topK": 40,
            "maxOutputTokens": 2048,
        },
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        ],
    }


def _parse_gemini_response(response_data: dict) -> str:
    """Extract the text from a Gemini API response."""
    candidates = response_data.get("candidates", [])
    if not candidates:
        raise GeminiError("No candidates in Gemini response")

    content = candidates[0].get("content", {})
    parts = content.get("parts", [])

    for part in parts:
        if "text" in part:
            return part["text"].strip()

    raise GeminiError("No text part in Gemini response")


class GeminiSummarizer:
    """Gemini-powered PDF summarizer for DAV announcements."""

    def __init__(self, settings: _Settings) -> None:
        self._api_key = settings.gemini_api_key
        self._model = settings.gemini_model
        self._max_pdf_size = settings.max_pdf_size_bytes

    def _validate_pdf_size(self, pdf_bytes: bytes) -> None:
        if len(pdf_bytes) > self._max_pdf_size:
            size_mb = len(pdf_bytes) / 1024 / 1024
            max_mb = self._max_pdf_size / 1024 / 1024
            raise PDFSizeError(
                f"PDF size {size_mb:.1f} MB exceeds limit of {max_mb:.0f} MB"
            )

    async def summarize_pdf_bytes(self, pdf_bytes: bytes) -> str:
        """
        Full pipeline: validate size → extract text → truncate → call Gemini → parse result.
        Returns the formatted summary string.
        """
        self._validate_pdf_size(pdf_bytes)
        raw_text = extract_text_from_pdf(pdf_bytes)
        truncated = truncate_for_gemini(raw_text)
        summary = await self._call_gemini(truncated)
        return summary

    async def summarize_text(self, text: str) -> str:
        """Summarize pre-extracted text directly (for testing)."""
        truncated = truncate_for_gemini(text)
        return await self._call_gemini(truncated)

    async def generate_text(self, prompt: str, max_tokens: int = 4096) -> str:
        """
        Generate free-form text using Gemini with a custom prompt.
        Unlike summarize_*, this does NOT use the DAV system prompt.
        Used for PharmaTech Daily article generation.
        """
        url = f"{GEMINI_API_BASE}/models/{self._model}:generateContent"
        params = {"key": self._api_key}
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.7,
                "topP": 0.9,
                "topK": 40,
                "maxOutputTokens": max_tokens,
            },
            "safetySettings": [
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(90.0)) as client:
                response = await client.post(url, json=payload, params=params)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            try:
                err_body = e.response.json()
                err_msg = err_body.get("error", {}).get("message", "")
            except Exception:
                err_msg = ""
            if status == 429 or "quota" in err_msg.lower():
                raise GeminiQuotaError(
                    f"Gemini quota exceeded: {err_msg or status}", cause=e,
                ) from e
            raise GeminiError(f"Gemini API HTTP {status}: {err_msg or e}", cause=e) from e
        except httpx.RequestError as e:
            raise GeminiError(f"Gemini API request failed: {e}", cause=e) from e

        try:
            return _parse_gemini_response(data)
        except (KeyError, IndexError, TypeError) as e:
            logger.error(f"Unexpected Gemini response structure: {str(data)[:500]}")
            raise GeminiError(f"Cannot parse Gemini response: {e}", cause=e) from e

    async def _call_gemini(self, text: str) -> str:
        """Make a single request to the Gemini API with error handling."""
        url = f"{GEMINI_API_BASE}/models/{self._model}:generateContent"
        params = {"key": self._api_key}
        payload = _build_gemini_request(text, self._model)

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
                response = await client.post(url, json=payload, params=params)
                response.raise_for_status()
                data = response.json()

        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            try:
                err_body = e.response.json()
                err_msg = err_body.get("error", {}).get("message", "")
            except Exception:
                err_msg = ""

            if status == 429 or "quota" in err_msg.lower():
                raise GeminiQuotaError(
                    f"Gemini quota exceeded: {err_msg or status}",
                    cause=e,
                ) from e
            raise GeminiError(
                f"Gemini API HTTP {status}: {err_msg or e}",
                cause=e,
            ) from e

        except httpx.RequestError as e:
            raise GeminiError(f"Gemini API request failed: {e}", cause=e) from e

        # Parse response
        try:
            return _parse_gemini_response(data)
        except (KeyError, IndexError, TypeError) as e:
            logger.error(f"Unexpected Gemini response structure: {str(data)[:500]}")
            raise GeminiError(f"Cannot parse Gemini response: {e}", cause=e) from e

    async def extract_gmp_foreign_from_pdf(self, pdf_bytes: bytes) -> list[dict]:
        """Extract foreign GMP certified factories from PDF bytes as a list of dicts using Gemini."""
        self._validate_pdf_size(pdf_bytes)
        raw_text = extract_text_from_pdf(pdf_bytes)
        truncated = truncate_for_gemini(raw_text, max_chars=40_000)
        
        prompt = (
            "Bạn là chuyên gia phân tích dữ liệu y tế. Dưới đây là văn bản danh sách các cơ sở sản xuất nước ngoài được đánh giá đáp ứng tiêu chuẩn GMP:\n\n"
            f"{truncated}\n\n"
            "Nhiệm vụ của bạn là: Trích xuất toàn bộ danh sách các cơ sở sản xuất dược phẩm đạt chuẩn GMP trong văn bản này.\n"
            "Để tiết kiệm độ dài và tránh bị cắt ngắn văn bản, bạn phải trả về dữ liệu dưới dạng văn bản thuần, mỗi cơ sở nằm trên một dòng duy nhất (ngăn cách các cột bằng dấu gạch đứng '|'):\n"
            "Tên cơ sở | Địa chỉ thực tế nhà máy | Tiêu chuẩn GMP | Cơ quan đánh giá/cấp | Phạm vi hoạt động chính\n\n"
            "Ví dụ dòng kết quả:\n"
            "Pfizer Ireland Pharmaceuticals | Grange Castle Business Park, Clondalkin, Dublin 22, Ireland | EU-GMP | Cục Quản lý Dược Việt Nam | Thuốc vô trùng, Thuốc không vô trùng\n\n"
            "Quy tắc quan trọng:\n"
            "- Trả về CHỈ danh sách các dòng kết quả, không viết bất kỳ lời giới thiệu hay giải thích nào khác.\n"
            "- Không sử dụng bất kỳ định dạng markdown nào (như bảng biểu markdown, thẻ ```, v.v.).\n"
            "- Mỗi cơ sở phải nằm hoàn toàn trên MỘT dòng duy nhất (không ngắt dòng giữa chừng).\n"
            "- Chỉ trích xuất các cơ sở thực tế có trong văn bản.\n"
        )
        
        response_text = await self.generate_text(prompt, max_tokens=4096)
        
        normalized = []
        for line in response_text.splitlines():
            line = line.strip()
            if not line or "|" not in line:
                continue
            parts = [x.strip() for x in line.split("|")]
            if len(parts) < 2:
                continue
                
            factory_name = parts[0]
            address = parts[1]
            # Bỏ qua dòng tiêu đề nếu AI trích xuất nhầm
            if not factory_name or not address or any(x in factory_name.lower() for x in ["tên cơ sở", "factory name", "---"]):
                continue
                
            standard = parts[2] if len(parts) > 2 and parts[2] else "EU-GMP"
            authority = parts[3] if len(parts) > 3 and parts[3] else "Cục Quản lý Dược"
            scope = parts[4] if len(parts) > 4 and parts[4] else "N/A"
            
            normalized.append({
                "factory_name": factory_name,
                "address": address,
                "scope": scope if scope else None,
                "standard": standard if standard else "GMP",
                "authority": authority if authority else "Cục Quản lý Dược",
                "headquarters_address": None,
                "location_name": None,
                "responsible_pharmacist": None,
                "certificate_license": None
            })
            
        logger.info(f"Successfully extracted {len(normalized)} foreign GMP factories via Gemini pipe-delimited parser.")
        return normalized
