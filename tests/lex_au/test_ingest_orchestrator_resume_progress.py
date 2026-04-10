from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lex_au.ingest.orchestrator import run_ingest
from lex_au.models import AULegislation, AULegislationSection, AULegislationType, AUProvisionType


def _make_legislation(title_id: str, year: int) -> AULegislation:
    section = AULegislationSection(
        id=f"{title_id}-s1",
        uri=f"https://example.test/{title_id}#s1",
        legislation_id=title_id,
        register_id=f"{title_id}-reg",
        title="Section 1",
        text="Example text",
        number="1",
        provision_type=AUProvisionType.SECTION,
        order=1,
        year=year,
        legislation_number=1,
        legislation_type=AULegislationType.ACT,
    )
    return AULegislation(
        id=title_id,
        uri=f"https://example.test/{title_id}",
        title=f"Title {title_id}",
        description="Example description",
        text="Example body",
        year=year,
        number=1,
        type=AULegislationType.ACT,
        status="InForce",
        collection=AULegislationType.ACT.collection_name,
        series_type=AULegislationType.ACT.display_name,
        register_id=f"{title_id}-reg",
        version_label="latest",
        compilation_number=None,
        making_date=None,
        registered_at=None,
        start_date=None,
        retrospective_start_date=None,
        end_date=None,
        sections=[section],
    )


class _StubScraper:
    def count_titles(self, years, types, limit=None, on_progress=None):
        if on_progress is not None:
            on_progress(2024, AULegislationType.ACT, 3)
        return {
            "2024:act": 3,
            "total": 3,
        }


class _StubPipeline:
    def __init__(self):
        self.scraper = _StubScraper()

    def iter_legislation(
        self,
        years,
        types,
        limit=None,
        version_spec="latest",
        resume_after_title_id=None,
        on_resume_scan=None,
    ):
        if on_resume_scan is not None:
            for title_id in ("C2024A00001", "C2024A00002"):
                on_resume_scan(
                    type(
                        "Summary",
                        (),
                        {
                            "title_id": title_id,
                        },
                    )(),
                    title_id == resume_after_title_id,
                )

        yield _make_legislation("C2024A00003", 2024)


class OrchestratorResumeProgressTest(unittest.TestCase):
    def test_resume_scan_logs_progress_and_preserves_checkpoint_totals(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            checkpoint_path = Path(tmp_dir) / "checkpoint.json"
            checkpoint_path.write_text(
                json.dumps(
                    {
                        "last_completed_title_id": "C2024A00002",
                        "legislation_count": 2,
                        "section_count": 2,
                    }
                )
            )

            with patch(
                "lex_au.ingest.orchestrator.AULegislationPipeline",
                return_value=_StubPipeline(),
            ):
                with self.assertLogs("lex_au.ingest.orchestrator", level="INFO") as logs:
                    result = run_ingest(
                        years=[2024],
                        types=[AULegislationType.ACT],
                        dry_run=True,
                        checkpoint_path=str(checkpoint_path),
                        progress_every=1,
                    )

            self.assertEqual(result["legislation_count"], 3)
            self.assertEqual(result["section_count"], 3)

            checkpoint_payload = json.loads(checkpoint_path.read_text())
            self.assertEqual(checkpoint_payload["legislation_count"], 3)
            self.assertEqual(checkpoint_payload["section_count"], 3)
            self.assertTrue(checkpoint_payload["completed"])
            self.assertIsNone(checkpoint_payload["last_completed_title_id"])

            combined_logs = "\n".join(logs.output)
            self.assertIn("Loaded checkpoint and resuming after C2024A00002", combined_logs)
            self.assertIn(
                "Loaded checkpoint totals: 2 titles and 2 sections already completed",
                combined_logs,
            )
            self.assertIn(
                "Resume scan 1 title(s) checked while locating C2024A00002",
                combined_logs,
            )
            self.assertIn(
                "Progress 3/3 (100.0%), current=C2024A00003, this run=1, resumed=2",
                combined_logs,
            )


if __name__ == "__main__":
    unittest.main()
