"""Unit tests for the Gemini PDF summarizer."""
from src.summarizer.gemini import extract_text_from_pdf, truncate_for_gemini


class TestExtractTextFromPDF:
    def test_empty_pdf_raises(self, sample_pdf_bytes: bytes) -> None:
        from src.core.exceptions import PDFParseError
        with pytest.raises(PDFParseError, match="no pages"):
            extract_text_from_pdf(sample_pdf_bytes)


class TestTruncateForGemini:
    def test_short_text_unchanged(self) -> None:
        text = "Short text."
        result = truncate_for_gemini(text, max_chars=100)
        assert result == text

    def test_long_text_truncated_preserves_both_ends(self) -> None:
        text = "A" * 20_000 + "END_CONTENT"
        result = truncate_for_gemini(text, max_chars=500)
        assert "A" in result
        assert "END_CONTENT" in result
        assert len(result) <= 600  # Allow some overhead for wrapper text
        assert "=== PHẦN ĐẦU ===" in result
        assert "=== PHẦN CUỐI ===" in result

    def test_exact_boundary_returns_unchanged(self) -> None:
        text = "X" * 100
        result = truncate_for_gemini(text, max_chars=100)
        assert result == text
