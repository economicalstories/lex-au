"""Orchestrator for AU legislation ingestion."""

from __future__ import annotations

import logging
import time
from pathlib import Path
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
    resume_after_title_id: str | None = None,
    checkpoint_path: str | None = None,
    progress_every: int = 10,
) -> dict:
    if skip_embed and not (dry_run or skip_upload):
        raise ValueError("Cannot upload to Vectorize when embeddings are disabled.")

    pipeline = AULegislationPipeline()
    legislation_buffer: list[AULegislation] = []
    section_buffer: list[AULegislationSection] = []
    client = None if dry_run or skip_upload else VectorizeClient.from_env()
    start_time = time.monotonic()
    checkpoint = None
    checkpoint_resume_title_id = None
    starting_legislation_count = 0
    starting_section_count = 0
    resume_scan_checked = 0

    if checkpoint_path:
        checkpoint = _read_checkpoint(Path(checkpoint_path))
        if checkpoint and not resume_after_title_id:
            checkpoint_resume_title_id = checkpoint.get("last_completed_title_id")
            resume_after_title_id = checkpoint_resume_title_id
            if resume_after_title_id:
                logger.info("Loaded checkpoint and resuming after %s", resume_after_title_id)
        elif checkpoint:
            checkpoint_resume_title_id = checkpoint.get("last_completed_title_id")

        if (
            checkpoint
            and resume_after_title_id
            and checkpoint_resume_title_id == resume_after_title_id
        ):
            starting_legislation_count = _coerce_count(checkpoint.get("legislation_count"))
            starting_section_count = _coerce_count(checkpoint.get("section_count"))
            if starting_legislation_count or starting_section_count:
                logger.info(
                    "Loaded checkpoint totals: %s titles and %s sections already completed",
                    starting_legislation_count,
                    starting_section_count,
                )

    logger.info(
        "Counting planned titles for %s year(s) and %s type(s) before ingest starts",
        len(years),
        len(types),
    )

    def _on_count_progress(year: int, legislation_type: AULegislationType, count: int) -> None:
        logger.info(
            "Counted %s planned %s title(s) for %s",
            count,
            legislation_type.value.upper(),
            year,
        )

    title_counts = pipeline.scraper.count_titles(
        years=years,
        types=types,
        limit=limit,
        on_progress=_on_count_progress,
    )
    logger.info("Planned title counting complete: %s title(s) in scope", title_counts["total"])
    counts_by_year: dict[int, int] = {year: 0 for year in years}
    done_by_year: dict[int, int] = {year: 0 for year in years}
    counts_by_type: dict[str, int] = {legislation_type.value: 0 for legislation_type in types}
    done_by_type: dict[str, int] = {legislation_type.value: 0 for legislation_type in types}

    for key, value in title_counts.items():
        if key == "total":
            continue
        year_text, type_value = key.split(":", maxsplit=1)
        year = int(year_text)
        counts_by_year[year] = counts_by_year.get(year, 0) + value
        counts_by_type[type_value] = counts_by_type.get(type_value, 0) + value

    stats = {
        "years": years,
        "types": [legislation_type.value for legislation_type in types],
        "total_titles_planned": title_counts["total"],
        "legislation_count": starting_legislation_count,
        "section_count": starting_section_count,
        "embedded": not skip_embed,
        "uploaded": client is not None,
        "resume_after_title_id": resume_after_title_id,
        "checkpoint_path": checkpoint_path,
        "sample": None,
    }

    if resume_after_title_id:
        if progress_every > 0:
            logger.info(
                "Starting resume scan for %s; progress will update every %s checked titles",
                resume_after_title_id,
                progress_every,
            )
        else:
            logger.info(
                "Starting resume scan for %s; periodic progress updates are disabled",
                resume_after_title_id,
            )

    def _on_resume_scan(summary, matched: bool) -> None:
        nonlocal resume_scan_checked
        resume_scan_checked += 1
        should_log = resume_scan_checked == 1 or (
            progress_every > 0 and resume_scan_checked % progress_every == 0
        )
        if not should_log:
            return

        status = "checkpoint found" if matched else "checking prior titles"
        logger.info(
            "Resume scan %s title(s) checked while locating %s; latest=%s (%s)",
            resume_scan_checked,
            resume_after_title_id,
            summary.title_id,
            status,
        )

    for legislation in pipeline.iter_legislation(
        years=years,
        types=types,
        limit=limit,
        version_spec=version_spec,
        resume_after_title_id=resume_after_title_id,
        on_resume_scan=_on_resume_scan if resume_after_title_id else None,
    ):
        legislation_buffer.append(legislation)
        section_buffer.extend(legislation.sections)
        stats["legislation_count"] += 1
        stats["section_count"] += len(legislation.sections)
        done_by_year[legislation.year] = done_by_year.get(legislation.year, 0) + 1
        done_by_type[legislation.type.value] = done_by_type.get(legislation.type.value, 0) + 1
        processed_this_run = stats["legislation_count"] - starting_legislation_count

        _log_progress(
            current_title_id=legislation.id,
            stats=stats,
            counts_by_year=counts_by_year,
            done_by_year=done_by_year,
            counts_by_type=counts_by_type,
            done_by_type=done_by_type,
            start_time=start_time,
            starting_legislation_count=starting_legislation_count,
            force=processed_this_run == 1 or (
                progress_every > 0 and processed_this_run % progress_every == 0
            ),
        )

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

        if checkpoint_path:
            _write_checkpoint(
                path=Path(checkpoint_path),
                payload={
                    "last_completed_title_id": legislation.id,
                    "legislation_count": stats["legislation_count"],
                    "section_count": stats["section_count"],
                },
            )

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

    stats["progress"] = {
        "by_year": {
            str(year): {
                "processed": done_by_year.get(year, 0),
                "total": counts_by_year.get(year, 0),
            }
            for year in sorted(counts_by_year)
        },
        "by_type": {
            type_name: {
                "processed": done_by_type.get(type_name, 0),
                "total": counts_by_type.get(type_name, 0),
            }
            for type_name in sorted(counts_by_type)
        },
    }

    if checkpoint_path:
        _write_checkpoint(
            path=Path(checkpoint_path),
            payload={
                "completed": True,
                "last_completed_title_id": None,
                "legislation_count": stats["legislation_count"],
                "section_count": stats["section_count"],
            },
        )

    return stats


def _read_checkpoint(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        import json

        return json.loads(path.read_text())
    except Exception:
        logger.exception("Failed to read checkpoint file %s", path)
        return None


def _write_checkpoint(path: Path, payload: dict) -> None:
    try:
        import json

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2))
    except Exception:
        logger.exception("Failed to write checkpoint file %s", path)


def _coerce_count(value: object) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def _percent(processed: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return (processed / total) * 100.0


def _log_progress(
    current_title_id: str,
    stats: dict,
    counts_by_year: dict[int, int],
    done_by_year: dict[int, int],
    counts_by_type: dict[str, int],
    done_by_type: dict[str, int],
    start_time: float,
    starting_legislation_count: int,
    force: bool,
) -> None:
    if not force:
        return

    total = stats["total_titles_planned"]
    completed = stats["legislation_count"]
    elapsed = max(time.monotonic() - start_time, 1e-6)
    completed_this_run = max(completed - starting_legislation_count, 0)
    rate = completed_this_run / elapsed
    remaining = max(total - completed, 0)
    eta_minutes = remaining / rate / 60 if rate > 0 and remaining > 0 else 0.0

    year_status = ", ".join(
        (
            f"{year}: {done_by_year.get(year, 0)}/{counts_by_year.get(year, 0)} "
            f"({_percent(done_by_year.get(year, 0), counts_by_year.get(year, 0)):.1f}%)"
        )
        for year in sorted(counts_by_year)
    )
    type_status = ", ".join(
        (
            f"{type_name.upper()}: "
            f"{done_by_type.get(type_name, 0)}/{counts_by_type.get(type_name, 0)} "
            f"({_percent(done_by_type.get(type_name, 0), counts_by_type.get(type_name, 0)):.1f}%)"
        )
        for type_name in sorted(counts_by_type)
    )

    if starting_legislation_count > 0:
        logger.info(
            (
                "Progress %s/%s (%.1f%%), current=%s, this run=%s, resumed=%s, "
                "ETA=~%.1f min | by year: %s | by type: %s"
            ),
            completed,
            total,
            _percent(completed, total),
            current_title_id,
            completed_this_run,
            starting_legislation_count,
            eta_minutes,
            year_status,
            type_status,
        )
        return

    logger.info(
        "Progress %s/%s (%.1f%%), current=%s, ETA=~%.1f min | by year: %s | by type: %s",
        completed,
        total,
        _percent(completed, total),
        current_title_id,
        eta_minutes,
        year_status,
        type_status,
    )


def _upload_documents(
    client: VectorizeClient,
    index_name: str,
    documents: Sequence[AULegislation | AULegislationSection],
) -> None:
    logger.info("Preparing %s document(s) for Vectorize index %s", len(documents), index_name)
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
    logger.info("Uploading %s vector(s) to %s", len(points), index_name)
    client.upsert(index_name, points)
    logger.info("Uploaded %s vector(s) to %s", len(points), index_name)
