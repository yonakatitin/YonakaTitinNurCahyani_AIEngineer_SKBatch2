from pathlib import Path

from src.ingest import normalize_pdf_text, pdf_to_text

ROOT = Path(__file__).resolve().parent.parent


def test_normalize_ligatures_and_special_spaces():
    out = normalize_pdf_text("e\ufb03cient\u00a0work\u200b  now")
    assert out == "efficient work now"


def test_normalize_collapses_blank_lines_and_trailing_spaces():
    out = normalize_pdf_text("a   \n\n\n\n b \r\n c")
    assert out == "a\n\nb\nc"


def test_normalize_keeps_hyphenated_words_untouched():
    assert "TensorFlow-\nbased" in normalize_pdf_text("TensorFlow-\nbased NLP")


def test_demo_pdf_text_is_extractable():
    text = pdf_to_text(str(ROOT / "data" / "demo_cv_pdf.pdf"))
    assert "Nadia Fiktif Anggraini" in text
    assert "Pydantic" in text
    assert len(text) > 1000
