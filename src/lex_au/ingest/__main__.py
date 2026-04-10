"""CLI entry point for AU legislation ingestion."""

from __future__ import annotations

import argparse
import json
import logging
import sys

import requests

from lex_au.core.http import APIRequestError
from lex_au.ingest.orchestrator import resolve_years, run_ingest, setup_vectorize_indexes
from lex_au.models import AULegislationType

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AU legislation ingest pipeline")
    parser.add_argument(
        "--mode",
        choices=["full", "recent", "setup"],
        default="recent",
        help="Run a full ingest, a recent-year ingest, or only create Vectorize indexes.",
    )
    parser.add_argument(
        "--type",
        nargs="+",
        choices=[legislation_type.value for legislation_type in AULegislationType],
        default=[legislation_type.value for legislation_type in AULegislationType],
        help="Legislation types to ingest.",
    )
    parser.add_argument(
        "--year",
        nargs="*",
        default=None,
        help="Explicit years or ranges like 2022 2023-2024.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of titles to process.",
    )
    parser.add_argument(
        "--version-spec",
        choices=["latest", "asmade"],
        default="latest",
        help="Which version of each title to ingest.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run discovery and parsing without uploading to Vectorize.",
    )
    parser.add_argument(
        "--skip-embed",
        action="store_true",
        help="Skip dense embedding generation. Useful for parser-only validation.",
    )
    parser.add_argument(
        "--skip-upload",
        action="store_true",
        help="Generate embeddings but do not upload to Vectorize.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Upload batch size used when embeddings and uploads are enabled.",
    )
    parser.add_argument(
        "--resume-after-title-id",
        default=None,
        help="Resume ingest after this title ID (the matching title is skipped).",
    )
    parser.add_argument(
        "--checkpoint-path",
        default=None,
        help="Path to a JSON checkpoint file for automatic resume.",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=10,
        help="Emit friendly progress summary every N ingested titles.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    if args.mode == "setup":
        try:
            result = setup_vectorize_indexes()
        except APIRequestError as exc:
            _report_api_error(exc, verbose=args.verbose)
            return 2
        print(json.dumps(result, indent=2))
        return 0

    years = resolve_years(args.mode, args.year)
    types = [AULegislationType(value) for value in args.type]

    try:
        result = run_ingest(
            years=years,
            types=types,
            limit=args.limit,
            version_spec=args.version_spec,
            dry_run=args.dry_run,
            skip_embed=args.skip_embed,
            skip_upload=args.skip_upload,
            batch_size=args.batch_size,
            resume_after_title_id=args.resume_after_title_id,
            checkpoint_path=args.checkpoint_path,
            progress_every=args.progress_every,
        )
    except APIRequestError as exc:
        _report_api_error(exc, verbose=args.verbose)
        return 2
    except requests.RequestException as exc:
        _report_generic_request_error(exc, verbose=args.verbose)
        return 2
    print(json.dumps(result, indent=2))
    return 0


def _report_api_error(exc: APIRequestError, *, verbose: bool) -> None:
    print("\nAU legislation ingest aborted: upstream API error", file=sys.stderr)
    print(exc.diagnostic_report(), file=sys.stderr)
    print(
        "\nRun 'python -m lex_au.core.diagnostics' to probe the API endpoints, "
        "or re-run with --verbose for full logs.",
        file=sys.stderr,
    )
    if verbose:
        logger.exception("Underlying APIRequestError: %s", exc)


def _report_generic_request_error(exc: Exception, *, verbose: bool) -> None:
    print(
        f"\nAU legislation ingest aborted: network/transport error: {exc}",
        file=sys.stderr,
    )
    print(
        "Run 'python -m lex_au.core.diagnostics' to probe the API endpoints, "
        "or re-run with --verbose for full logs.",
        file=sys.stderr,
    )
    if verbose:
        logger.exception("Underlying transport error: %s", exc)


if __name__ == "__main__":
    sys.exit(main())
