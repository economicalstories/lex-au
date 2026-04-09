"""Unit tests for the AU XHTML parser."""

from __future__ import annotations

import unittest

from lex_au.legislation.parser import AULegislationParser
from lex_au.models import AULegislationType, AUProvisionType, AUTitleSummary


SAMPLE_XHTML = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <body>
    <div>
      <p class="ShortT">Example Act 2024</p>
      <p class="CompiledActNo">No. 7, 2024</p>
      <p class="LongT">An Act to demonstrate AU parser behaviour</p>
      <p class="TOC5">1 Short title</p>
      <p class="ActHead1">Chapter 1—Preliminary</p>
      <p class="ActHead2">Part 1.1—Introduction</p>
      <p class="ActHead5">1  Short title</p>
      <p class="subsection">This Act may be cited as the Example Act 2024.</p>
      <p class="ActHead5">2  Definitions</p>
      <p class="subsection">(1) In this Act:</p>
      <p class="paragraph">(a) example means example text.</p>
      <p class="ActHead1">Schedule 1—Savings provisions</p>
      <p class="subsection">1 This schedule applies to transitional matters.</p>
      <p class="ENotesHeading1">Endnotes</p>
    </div>
  </body>
</html>
"""

SECONDARY_XHTML = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <body>
    <div>
      <p class="Plainheader">Example Instrument</p>
      <p class="Header">Contents</p>
      <p class="TOC1">1 Name</p>
      <p class="LV1">1 Name</p>
      <p class="PlainIndent">This instrument is the Example Instrument 2024.</p>
      <p class="LV1">2 Commencement</p>
      <p class="PlainIndent">This instrument commences on 1 July 2024.</p>
    </div>
  </body>
</html>
"""


class AULegislationParserTest(unittest.TestCase):
    def test_parser_extracts_sections_and_schedule(self) -> None:
        parser = AULegislationParser()
        summary = AUTitleSummary(
            title_id="C2024A00007",
            title="Example Act 2024",
            year=2024,
            number=7,
            status="InForce",
            collection="Act",
            series_type="Act",
            legislation_type=AULegislationType.ACT,
        )
        legislation = parser.parse(
            summary=summary,
            title_data={"makingDate": "2024-03-01T00:00:00"},
            version_data={
                "registerId": "C2024A00007",
                "status": "InForce",
                "compilationNumber": "0",
                "start": "2024-03-01T00:00:00",
                "retrospectiveStart": "2024-03-01T00:00:00",
            },
            document_pages=[("doc1", SAMPLE_XHTML)],
        )

        self.assertEqual(legislation.description, "An Act to demonstrate AU parser behaviour")
        self.assertEqual(len(legislation.sections), 3)

        first_section = legislation.sections[0]
        self.assertEqual(first_section.number, "1")
        self.assertEqual(first_section.title, "Short title")
        self.assertEqual(first_section.chapter, "Chapter 1—Preliminary")
        self.assertEqual(first_section.part, "Part 1.1—Introduction")
        self.assertIn("Example Act 2024", first_section.text)

        schedule = legislation.sections[2]
        self.assertEqual(schedule.provision_type, AUProvisionType.SCHEDULE)
        self.assertEqual(schedule.number, "Schedule 1")
        self.assertEqual(schedule.title, "Savings provisions")
        self.assertIn("transitional matters", schedule.text)

    def test_parser_extracts_lv_sections_for_secondary_instruments(self) -> None:
        parser = AULegislationParser()
        summary = AUTitleSummary(
            title_id="F2024L00001",
            title="Example Instrument 2024",
            year=2024,
            number=1,
            status="InForce",
            collection="LegislativeInstrument",
            series_type="SLI",
            legislation_type=AULegislationType.LI,
        )
        legislation = parser.parse(
            summary=summary,
            title_data={"makingDate": "2024-07-01T00:00:00"},
            version_data={
                "registerId": "F2024L00001",
                "status": "InForce",
                "compilationNumber": "0",
                "start": "2024-07-01T00:00:00",
                "retrospectiveStart": "2024-07-01T00:00:00",
            },
            document_pages=[("doc1", SECONDARY_XHTML)],
        )

        self.assertEqual(len(legislation.sections), 2)
        self.assertEqual(legislation.sections[0].number, "1")
        self.assertEqual(legislation.sections[0].title, "Name")
        self.assertIn("Example Instrument 2024", legislation.sections[0].text)
        self.assertEqual(legislation.sections[1].number, "2")
        self.assertEqual(legislation.sections[1].title, "Commencement")


if __name__ == "__main__":
    unittest.main()
