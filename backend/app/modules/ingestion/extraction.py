import io

from bs4 import BeautifulSoup
from pypdf import PdfReader

from app.core.errors import ValidationError


def extract_text(content: bytes, mime: str) -> str:
    if mime == "text/plain":
        return content.decode("utf-8", errors="replace")
    if mime == "text/html":
        soup = BeautifulSoup(content, "html.parser")
        return soup.get_text(separator="\n")
    if mime == "application/pdf":
        reader = PdfReader(io.BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    raise ValidationError(f"unsupported mime type for extraction: {mime!r}")
