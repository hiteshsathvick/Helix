import logging
from functools import lru_cache

from app.core.config import get_settings
from app.modules.ingestion.models import EMBEDDING_DIMENSIONS

logger = logging.getLogger("helix.ingestion")


@lru_cache
def _get_model():
    # Imported lazily: sentence-transformers/torch are heavy, and the API
    # process never needs them — only a worker actually embedding chunks
    # does. First call downloads model weights (~80MB) from Hugging Face,
    # cached afterward.
    from sentence_transformers import SentenceTransformer

    settings = get_settings()
    logger.info("loading embedding model: %s", settings.embedding_model_name)
    model = SentenceTransformer(settings.embedding_model_name)

    actual_dim = model.get_sentence_embedding_dimension()
    if actual_dim != EMBEDDING_DIMENSIONS:
        raise RuntimeError(
            f"embedding model {settings.embedding_model_name!r} outputs "
            f"{actual_dim} dimensions, but the chunks.embedding column is "
            f"fixed at {EMBEDDING_DIMENSIONS} (see ingestion/models.py)"
        )
    return model


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    model = _get_model()
    vectors = model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
    return [vector.tolist() for vector in vectors]
