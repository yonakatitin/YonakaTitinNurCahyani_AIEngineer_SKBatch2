from pypdf import PdfReader


def pdf_to_text(path: str) -> str:
    """Ekstrak teks dari PDF berbasis teks (bukan hasil scan)."""
    reader = PdfReader(path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)
