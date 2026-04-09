"""Embeddings and sparse hashing helpers for AU ingestion."""

from __future__ import annotations

from collections import Counter
import re
import unicodedata

from lex_au.settings import AU_EMBEDDING_BATCH_SIZE, AU_EMBEDDING_MODEL_NAME, AU_SPARSE_HASH_DIMENSIONS

TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)?")

_MODEL = None


def _lazy_import_embedding_dependencies():
    try:
        import torch  # type: ignore[import-not-found]
        from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "sentence-transformers and torch are required for AU embeddings. "
            "Install the lex-au dependency group before running with embeddings enabled."
        ) from exc

    return SentenceTransformer, torch


def get_model(model_name: str = AU_EMBEDDING_MODEL_NAME):
    global _MODEL
    if _MODEL is None:
        SentenceTransformer, torch = _lazy_import_embedding_dependencies()
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _MODEL = SentenceTransformer(model_name, device=device)
    return _MODEL


def embed_batch(texts: list[str], batch_size: int = AU_EMBEDDING_BATCH_SIZE) -> list[list[float]]:
    if not texts:
        return []

    model = get_model()
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return embeddings.tolist()


def normalise_text(text: str) -> str:
    return unicodedata.normalize("NFKC", text).lower()


def tokenize_for_sparse(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(normalise_text(text))


def djb2_hash(token: str) -> int:
    value = 5381
    for byte in token.encode("utf-8"):
        value = ((value << 5) + value + byte) & 0xFFFFFFFF
    return value


def build_sparse_vector(
    text: str, dimensions: int = AU_SPARSE_HASH_DIMENSIONS
) -> dict[str, list[int] | list[float]]:
    counts = Counter(djb2_hash(token) % dimensions for token in tokenize_for_sparse(text))
    if not counts:
        return {"indices": [], "values": []}

    indices = sorted(counts)
    total = sum(counts.values())
    values = [counts[index] / total for index in indices]
    return {"indices": indices, "values": values}
