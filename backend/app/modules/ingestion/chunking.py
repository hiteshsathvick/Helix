import tiktoken

_encoding = tiktoken.get_encoding("cl100k_base")


def chunk_text(text: str, chunk_tokens: int, overlap_tokens: int) -> list[str]:
    """Token-based chunking with overlap (SPEC.md §18: ~500-1000 tokens,
    overlap). Uses tiktoken purely as a tokenizer, independent of which LLM
    provider eventually consumes the chunks."""
    tokens = _encoding.encode(text)
    if not tokens:
        return []

    chunks = []
    start = 0
    while start < len(tokens):
        end = min(start + chunk_tokens, len(tokens))
        chunks.append(_encoding.decode(tokens[start:end]))
        if end == len(tokens):
            break
        start = end - overlap_tokens
    return chunks
