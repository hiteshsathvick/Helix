import uuid

from pydantic import BaseModel


class SearchResult(BaseModel):
    document_id: uuid.UUID
    document_title: str
    chunk_id: uuid.UUID
    ordinal: int
    # Matched terms are bounded by \x01...\x02 (search.service.HIGHLIGHT_*),
    # not HTML tags — split on those to highlight; never render as HTML,
    # since the underlying document content is untrusted (CLAUDE.md §5).
    snippet: str
    score: float


class SearchResponse(BaseModel):
    results: list[SearchResult]
    next_cursor: str | None
