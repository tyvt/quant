"""One native text-page parse per PDF page, with process-local content caching.

No OCR, network, publication or table-semantic certification. Geometry is retained
even when outside page bounds so downstream binders cannot treat truncation as zero.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path


@dataclass(frozen=True)
class Word:
    text: str
    box: tuple[float, float, float, float]

    @property
    def y(self):
        return (self.box[1] + self.box[3]) / 2


@dataclass(frozen=True)
class Page:
    number: int
    width: float
    height: float
    rotation: int
    text: str
    words: tuple[Word, ...]
    cropbox: tuple[float, float, float, float] | None = None
    mediabox: tuple[float, float, float, float] | None = None


@dataclass(frozen=True)
class ParsedPDF:
    sha256: str
    backend_version: str
    extractor_sha256: str
    pages: tuple[Page, ...]


class PDFCache:
    """Reuses immutable native text/word geometry, not screening calculations."""

    def __init__(self):
        self._cache: dict[tuple[str, str, str], ParsedPDF] = {}
        self._code_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        self.parsed_documents = 0
        self.cache_hits = 0

    def parse(self, raw: bytes, expected_sha256: str) -> ParsedPDF:
        import fitz

        actual = hashlib.sha256(raw).hexdigest()
        if actual != expected_sha256:
            raise ValueError("PDF bytes do not match the fixed source SHA-256")
        code_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        if code_hash != self._code_hash:
            raise ValueError("PDF extractor changed during session; restart")
        key = (actual, fitz.VersionBind, code_hash)
        if key in self._cache:
            self.cache_hits += 1
            return self._cache[key]
        pages = []
        with fitz.open(stream=raw, filetype="pdf") as pdf:
            if pdf.needs_pass or not len(pdf):
                raise ValueError("encrypted or empty PDF is not supported")
            for index, page in enumerate(pdf):
                text_page = page.get_textpage()
                words = tuple(Word(item[4], tuple(round(value, 3) for value in item[:4]))
                              for item in text_page.extractWORDS())
                pages.append(Page(index + 1, round(page.rect.width, 3),
                                  round(page.rect.height, 3), page.rotation,
                                  text_page.extractText(), words,
                                  tuple(round(v, 3) for v in page.cropbox),
                                  tuple(round(v, 3) for v in page.mediabox)))
        result = ParsedPDF(actual, fitz.VersionBind, code_hash, tuple(pages))
        self._cache[key] = result
        self.parsed_documents += 1
        return result
