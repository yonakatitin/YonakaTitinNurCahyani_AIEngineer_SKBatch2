"""Ekstraksi teks dari PDF berbasis teks (bukan hasil scan; tanpa OCR)."""
import re

from pypdf import PdfReader

_LIGATURES = {
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl",
}
# spasi tak-putus dan sejenisnya -> spasi biasa; karakter lebar-nol -> dihapus
_CHAR_MAP = {ord(c): " " for c in "\u00a0\u2007\u202f"}
_CHAR_MAP.update({ord(c): None for c in "\u200b\u200c\u200d\ufeff"})


def normalize_pdf_text(text: str) -> str:
    """Pembersihan aman: tidak mengubah isi kata (tanpa menyambung tanda hubung)."""
    for lig, plain in _LIGATURES.items():
        text = text.replace(lig, plain)
    text = text.translate(_CHAR_MAP)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x0c", "\n")
    text = "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def pdf_to_text(path: str, layout: bool = False) -> str:
    reader = PdfReader(path)
    pages = []
    for page in reader.pages:
        if layout:
            pages.append(page.extract_text(extraction_mode="layout") or "")
        else:
            pages.append(page.extract_text() or "")
    return normalize_pdf_text("\n".join(pages))
