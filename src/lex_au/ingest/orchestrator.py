"""Orchestrator for AU legislation ingestion."""

from __future__ import annotations

import logging
from typing import Sequence

from lex_au.core.embeddings import build_sparse_vector, embed_batch
from lex_au.core.vectorize_client import VectorizeClient, VectorizePoint, make_vector_id
from lex_au.legislation.pipeline import AULegislationPipeline
from lex_au.models import AULegislation, AULegislationSection, AULegislationType
from lex_au.settings import (
    AU_EMBEDDING_DIMENSIONS,
    AU_VECTORIZE_INDEX_NAME,
    AU_VECTORIZE_PRESET,
    AU_VECTORIZE_SECTION_INDEX_NAME,
    CURRENT_YEAR,
    FIRST_AU_FEDERAL_YEAR,
)

logger = logging.getLogger(__name__)


def resolve_years(mode: str, year_tokens: list[str] | None) -> list[int]:
    from lex_au.settings import expand_year_tokens

    explicit_years = expand_year_tokens(year_tokens)
    if explicit_years:
        return explicit_years

    if mode == "recent":
        return [CURRENT_YEAR - 1, CURRENT_YEAR]
    if mode == "full":
        return list(range(FIRST_AU_FEDERAL_YEAR, CURRENT_YEAR + 1))

    raise ValueError(f"Unsupported mode for year resolution: {mode}")


def setup_vectorize_indexes() -> dict[str, str]:
    client = VectorizeClient.from_env()
    existing_names = {item.get("name") for item in client.list_indexes()}

    if AU_VECTORIZE_INDEX_NAME not in existing_names:
        client.create_index(
            AU_VECTORIZE_INDEX_NAME,
            dimensions=AU_EMBEDDING_DIMENSIONS,
            metric="cosine",
            description="AU legislation title index",
            preset=AU_VECTORIZE_PRESET,
        )
    if AU_VECTORIZE_SECTION_INDEX_NAME not in existing_names:
        client.create_index(
            AU_VECTORIZE_SECTION_INDEX_NAME,
            dimensions=AU_EMBEDDING_DIMENSIONS,
            metric="cosine",
            description="AU legislation section index",
            preset=AU_VECTORIZE_PRESET,
        )

    return {
        "legislation_index": AU_VECTORIZE_INDEX_NAME,
        "section_index": AU_VECTORIZE_SECTION_INDEX_NAME,
    }


def run_ingest(
    years: list[int],
    types: list[AULegislationType],
    limit: int | None = None,
    version_spec: str = "latest",
    dry_run: bool = False,
    skip_embed: bool = False,
    skip_upload: bool = False,
    batch_size: int = 50,
) -> dict:
    if skip_embed and not (dry_run or skip_upload):
        raise ValueError("Cannot upload to Vectorize when embeddings are disabled.")

    pipeline = AULegislationPipeline()
    legislation_buffer: list[AULegislation] = []
    section_buffer: list[AULegislationSection] = []
    client = None if dry_run or skip_upload else VectorizeClient.from_env()

    stats = {
        "years": years,
        "types": [legislation_type.value for legislation_type in types],
        "legislation_count": 0,
        "section_count": 0,
        "embedded": not skip_embed,
        "uploaded": client is not None,
        "sample": None,
    }

    for legislation in pipeline.iter_legislation(
        years=years,
        types=types,
        limit=limit,
        version_spec=version_spec,
    ):
        legislation_buffer.append(legislation)
        section_buffer.extend(legislation.sections)
        stats["legislation_count"] += 1
        stats["section_count"] += len(legislation.sections)

        if stats["sample"] is None:
            stats["sample"] = {
                "title_id": legislation.id,
                "register_id": legislation.register_id,
                "title": legislation.title,
                "section_count": len(legislation.sections),
                "first_sections": [
                    {
                        "number": section.number,
                        "title": section.title,
                    }
                    for section in legislation.sections[:3]
                ],
            }

        if client is not None and len(legislation_buffer) >= batch_size:
            _upload_documents(
                client=client,
                index_name=AU_VECTORIZE_INDEX_NAME,
                documents=legislation_buffer,
            )
            legislation_buffer = []

        if client is not None and len(section_buffer) >= batch_size:
            _upload_documents(
                client=client,
                index_name=AU_VECTORIZE_SECTION_INDEX_NAME,
                documents=section_buffer,
            )
            section_buffer = []

    if client is not None and legislation_buffer:
        _upload_documents(
            client=client,
            index_name=AU_VECTORIZE_INDEX_NAME,
            documents=legislation_buffer,
        )
    if client is not None and section_buffer:
        _upload_documents(
            client=client,
            index_name=AU_VECTORIZE_SECTION_INDEX_NAME,
            documents=section_buffer,
        )

    return stats


def _upload_documents(
    client: VectorizeClient,
    index_name: str,
    documents: Sequence[AULegislation | AULegislationSection],
) -> None:
    texts = [document.get_embedding_text() for document in documents]
    dense_vectors = embed_batch(texts)
    points = [
        VectorizePoint(
            id=make_vector_id(document.id),
            values=dense_vector,
            sparse_values=build_sparse_vector(text),
            metadata=document.to_vectorize_metadata(),
        )
        for document, text, dense_vector in zip(documents, texts, dense_vectors)
    ]
    client.upsert(index_name, points)
