#!/usr/bin/env python3
"""
Audit AU Vectorize coverage for legislation titles already embedded.

The script scans the AU legislation Vectorize index for stored title IDs,
discovers the authoritative title list from legislation.gov.au for the chosen
scope, and reports what is already embedded vs still missing.

Examples:
    ./.venv/bin/python scripts/check_au_vectorize_progress.py --year 2001-2026
    ./.venv/bin/python scripts/check_au_vectorize_progress.py --year 2024-2026 --type act li
    ./.venv/bin/python scripts/check_au_vectorize_progress.py --year 2001-2026
        --missing-out missing_acts.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
from rich.progress import Progress, SpinnerColumn, TaskProgressColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

# Add src and scripts to path.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env", override=True)

from _console import console, print_header, print_summary, setup_logging  # noqa: E402

from lex_au.core.vectorize_client import VectorizeClient  # noqa: E402
from lex_au.legislation.scraper import AULegislationScraper  # noqa: E402
from lex_au.models import AULegislationType, AUTitleSummary  # noqa: E402
from lex_au.settings import (  # noqa: E402
    AU_VECTORIZE_INDEX_NAME,
    CURRENT_YEAR,
    FIRST_AU_FEDERAL_YEAR,
    expand_year_tokens,
)

logger = logging.getLogger(__name__)


def resolve_years(mode: str, year_tokens: list[str] | None) -> list[int]:
    explicit_years = expand_year_tokens(year_tokens)
    if explicit_years:
        return explicit_years

    if mode == "recent":
        return [CURRENT_YEAR - 1, CURRENT_YEAR]
    if mode == "full":
        return list(range(FIRST_AU_FEDERAL_YEAR, CURRENT_YEAR + 1))

    raise ValueError(f"Unsupported mode for year resolution: {mode}")


def load_vector_ids(
    client: VectorizeClient,
    index_name: str,
    page_size: int,
) -> tuple[set[str], int | None]:
    vector_ids: set[str] = set()
    total_count: int | None = None

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("Scanning Vectorize index", total=None)

        for page in client.iter_vectors(index_name, count=page_size):
            ids = [item["id"] for item in page.get("vectors", []) if item.get("id")]
            vector_ids.update(ids)

            if total_count is None and isinstance(page.get("totalCount"), int):
                total_count = page["totalCount"]
                progress.update(task_id, total=total_count)

            progress.update(
                task_id,
                advance=len(ids),
                description=f"Scanning Vectorize index ({len(vector_ids):,} ids seen)",
            )

    return vector_ids, total_count


def discover_titles(
    scraper: AULegislationScraper,
    years: list[int],
    types: list[AULegislationType],
    limit: int | None,
) -> dict[str, AUTitleSummary]:
    discovered: dict[str, AUTitleSummary] = {}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("Discovering AU titles", total=None)

        for year in years:
            for legislation_type in types:
                remaining = None if limit is None else max(limit - len(discovered), 0)
                if remaining == 0:
                    return discovered

                batch_count = 0
                progress.update(
                    task_id,
                    description=(
                        f"Discovering {legislation_type.value.upper()} {year} "
                        f"({len(discovered):,} titles found so far)"
                    ),
                )

                for summary in scraper.discover_titles(legislation_type, year, limit=remaining):
                    discovered[summary.title_id] = summary
                    batch_count += 1
                    progress.update(
                        task_id,
                        advance=1,
                        description=(
                            f"Discovering {legislation_type.value.upper()} {year} "
                            f"({len(discovered):,} titles found so far)"
                        ),
                    )

                logger.info(
                    "Discovered %s %s title(s) for %s",
                    batch_count,
                    legislation_type.value.upper(),
                    year,
                )

    return discovered


def build_coverage_rows(
    discovered: dict[str, AUTitleSummary],
    embedded_ids: set[str],
) -> tuple[list[dict[str, object]], list[AUTitleSummary]]:
    stats: dict[tuple[int, str], dict[str, int]] = defaultdict(
        lambda: {"total": 0, "embedded": 0, "missing": 0}
    )
    missing: list[AUTitleSummary] = []

    for summary in discovered.values():
        key = (summary.year, summary.legislation_type.value)
        stats[key]["total"] += 1
        if summary.title_id in embedded_ids:
            stats[key]["embedded"] += 1
        else:
            stats[key]["missing"] += 1
            missing.append(summary)

    rows = [
        {
            "year": year,
            "type": type_name,
            "total": values["total"],
            "embedded": values["embedded"],
            "missing": values["missing"],
            "coverage": (values["embedded"] / values["total"] * 100) if values["total"] else 0.0,
        }
        for (year, type_name), values in sorted(stats.items())
    ]

    missing.sort(key=lambda item: (item.year, item.legislation_type.value, item.title_id))
    return rows, missing


def render_coverage_table(rows: list[dict[str, object]]) -> None:
    table = Table(
        title="Coverage by Year and Type",
        border_style="blue",
        expand=False,
        padding=(0, 1),
    )
    table.add_column("Year", justify="right")
    table.add_column("Type", style="bold")
    table.add_column("Total", justify="right")
    table.add_column("Embedded", justify="right", style="green")
    table.add_column("Missing", justify="right", style="red")
    table.add_column("Coverage", justify="right")

    for row in rows:
        table.add_row(
            str(row["year"]),
            str(row["type"]).upper(),
            f"{row['total']:,}",
            f"{row['embedded']:,}",
            f"{row['missing']:,}",
            f"{row['coverage']:.1f}%",
        )

    console.print()
    console.print(table)
    console.print()


def render_missing_table(missing: list[AUTitleSummary], limit: int) -> None:
    if not missing or limit <= 0:
        return

    table = Table(
        title=f"First {min(limit, len(missing))} Missing Titles",
        border_style="yellow",
        expand=False,
        padding=(0, 1),
    )
    table.add_column("Year", justify="right")
    table.add_column("Type", style="bold")
    table.add_column("Title ID", style="cyan")
    table.add_column("Title", overflow="fold")

    for summary in missing[:limit]:
        table.add_row(
            str(summary.year),
            summary.legislation_type.value.upper(),
            summary.title_id,
            summary.title,
        )

    console.print(table)
    console.print()


def write_missing_file(path: Path, missing: list[AUTitleSummary]) -> None:
    payload = [
        {
            "title_id": summary.title_id,
            "title": summary.title,
            "year": summary.year,
            "type": summary.legislation_type.value,
            "collection": summary.collection,
            "series_type": summary.series_type,
            "status": summary.status,
        }
        for summary in missing
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))
    logger.info("Wrote %s missing title(s) to %s", len(payload), path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check which AU legislation titles are already present in Cloudflare Vectorize",
    )
    parser.add_argument(
        "--mode",
        choices=["full", "recent"],
        default="full",
        help="Default year scope when --year is omitted.",
    )
    parser.add_argument(
        "--year",
        nargs="*",
        default=None,
        help="Explicit years or ranges like 2022 2023-2024.",
    )
    parser.add_argument(
        "--type",
        nargs="+",
        choices=[legislation_type.value for legislation_type in AULegislationType],
        default=[legislation_type.value for legislation_type in AULegislationType],
        help="Legislation types to audit.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of discovered titles to compare.",
    )
    parser.add_argument(
        "--index-name",
        default=AU_VECTORIZE_INDEX_NAME,
        help="Vectorize index name to inspect.",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=1000,
        help="Vectorize list page size (max 1000).",
    )
    parser.add_argument(
        "--show-missing",
        type=int,
        default=25,
        help="Show the first N missing titles in the terminal.",
    )
    parser.add_argument(
        "--missing-out",
        type=Path,
        default=None,
        help="Optional JSON file path for all missing titles in scope.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    setup_logging(logging.DEBUG if args.verbose else logging.INFO)

    years = resolve_years(args.mode, args.year)
    types = [AULegislationType(value) for value in args.type]

    print_header(
        "AU Vectorize Coverage Audit",
        details={
            "Index": args.index_name,
            "Years": f"{years[0]}-{years[-1]}" if years else "None",
            "Types": ", ".join(type_name.value.upper() for type_name in types),
        },
    )

    client = VectorizeClient.from_env()
    scraper = AULegislationScraper()

    embedded_ids, total_index_count = load_vector_ids(client, args.index_name, args.page_size)
    discovered = discover_titles(scraper, years, types, args.limit)
    rows, missing = build_coverage_rows(discovered, embedded_ids)

    embedded_in_scope = len(discovered) - len(missing)
    discovered_ids = set(discovered)
    outside_scope = len(embedded_ids - discovered_ids)

    print_summary(
        "Scope Summary",
        {
            "Discovered in scope": f"{len(discovered):,}",
            "Embedded in scope": f"{embedded_in_scope:,}",
            "Missing in scope": f"{len(missing):,}",
            "Coverage": (
                f"{embedded_in_scope / len(discovered) * 100:.1f}%"
                if discovered
                else "0.0%"
            ),
            "IDs scanned in index": f"{len(embedded_ids):,}",
            "Index total count": (
                f"{total_index_count:,}" if total_index_count is not None else "Unknown"
            ),
            "Embedded outside scope": f"{outside_scope:,}",
        },
        success=not missing,
    )

    render_coverage_table(rows)
    render_missing_table(missing, args.show_missing)

    if args.missing_out is not None:
        write_missing_file(args.missing_out, missing)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
