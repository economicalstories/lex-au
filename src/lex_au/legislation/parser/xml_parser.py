"""Parser for AU legislation XHTML exposed by the register's EPUB view."""

from __future__ import annotations

import logging
import re
from xml.etree import ElementTree as ET

from lex_au.models import (
    AULegislation,
    AULegislationSection,
    AUProvisionType,
    AUTitleSummary,
    slugify_fragment,
)
from lex_au.settings import AU_WEB_BASE_URL

logger = logging.getLogger(__name__)

XHTML_NS = {"xhtml": "http://www.w3.org/1999/xhtml"}
HEADING_CLASSES = {"ActHead1", "ActHead2", "ActHead3", "ActHead4", "ActHead5"}
SECONDARY_SECTION_CLASSES = {"LV1"}
SCHEDULE_HEADING_CLASSES = {"SH1"}
SKIP_CLASSES = {"ShortT", "CompiledActNo", "Header"}


def _clean_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _is_page_marker(text: str) -> bool:
    return bool(re.match(r"^Page \d+ of \d+$", text))


class AULegislationParser:
    def parse(
        self,
        summary: AUTitleSummary,
        title_data: dict,
        version_data: dict,
        document_pages: list[tuple[str, str]],
        version_label: str = "latest",
    ) -> AULegislation:
        description = summary.title
        sections: list[AULegislationSection] = []
        current_section: AULegislationSection | None = None
        current_paragraphs: list[str] = []
        fallback_paragraphs: list[str] = []
        current_chapter: str | None = None
        current_part: str | None = None
        current_division: str | None = None
        section_order = 0

        def flush_current_section() -> None:
            nonlocal current_section, current_paragraphs
            if current_section is None:
                return
            current_section.text = "\n".join(current_paragraphs).strip()
            sections.append(current_section)
            current_section = None
            current_paragraphs = []

        for _, page_html in document_pages:
            root = ET.fromstring(page_html)
            for paragraph in root.findall(".//xhtml:p", XHTML_NS):
                cls = paragraph.attrib.get("class", "")
                text = _clean_text("".join(paragraph.itertext()))
                if not text:
                    continue

                if cls.startswith("TOC"):
                    continue

                if cls.startswith("ENote") or cls.startswith("ENotes"):
                    flush_current_section()
                    break

                if cls == "LongT" and description == summary.title:
                    description = text

                if cls in SKIP_CLASSES:
                    continue
                if _is_page_marker(text):
                    continue

                fallback_paragraphs.append(text)

                if cls in HEADING_CLASSES or cls in SECONDARY_SECTION_CLASSES or cls in SCHEDULE_HEADING_CLASSES:
                    if self._is_schedule_heading(text):
                        flush_current_section()
                        section_order += 1
                        number, title = self._split_schedule_heading(text)
                        current_section = self._make_section(
                            summary=summary,
                            version_data=version_data,
                            number=number,
                            title=title,
                            provision_type=AUProvisionType.SCHEDULE,
                            order=section_order,
                            chapter=current_chapter,
                            part=current_part,
                            division=current_division,
                        )
                        continue

                    if cls == "ActHead1":
                        current_chapter = text
                        current_part = None
                        current_division = None
                        continue
                    if cls == "ActHead2":
                        current_part = text
                        current_division = None
                        continue
                    if cls in {"ActHead3", "ActHead4"}:
                        current_division = text
                        continue
                    if cls == "ActHead5":
                        flush_current_section()
                        section_order += 1
                        number, title = self._split_section_heading(text)
                        current_section = self._make_section(
                            summary=summary,
                            version_data=version_data,
                            number=number,
                            title=title,
                            provision_type=AUProvisionType.SECTION,
                            order=section_order,
                            chapter=current_chapter,
                            part=current_part,
                            division=current_division,
                        )
                        continue
                    if cls in SECONDARY_SECTION_CLASSES:
                        flush_current_section()
                        section_order += 1
                        number, title = self._split_section_heading(text)
                        current_section = self._make_section(
                            summary=summary,
                            version_data=version_data,
                            number=number,
                            title=title,
                            provision_type=AUProvisionType.SECTION,
                            order=section_order,
                            chapter=current_chapter,
                            part=current_part,
                            division=current_division,
                        )
                        continue

                if current_section is not None:
                    current_paragraphs.append(text)

        flush_current_section()

        if not sections and fallback_paragraphs:
            section_order += 1
            sections.append(
                self._make_section(
                    summary=summary,
                    version_data=version_data,
                    number="full-text",
                    title=summary.title,
                    provision_type=AUProvisionType.SECTION,
                    order=section_order,
                    chapter=None,
                    part=None,
                    division=None,
                )
            )
            sections[0].text = "\n".join(fallback_paragraphs).strip()

        text = "\n\n".join(section.get_embedding_text() for section in sections).strip()
        return AULegislation(
            id=summary.title_id,
            uri=f"{AU_WEB_BASE_URL}/{summary.title_id}",
            title=summary.title,
            description=description,
            text=text,
            year=summary.year,
            number=summary.number,
            type=summary.legislation_type,
            status=version_data.get("status", summary.status),
            collection=summary.collection,
            series_type=summary.series_type,
            register_id=version_data.get("registerId", summary.title_id),
            version_label=version_label,
            compilation_number=version_data.get("compilationNumber"),
            making_date=title_data.get("makingDate"),
            registered_at=version_data.get("registeredAt"),
            start_date=version_data.get("start"),
            retrospective_start_date=version_data.get("retrospectiveStart"),
            end_date=version_data.get("end"),
            administering_departments=[
                department["name"]
                for department in title_data.get("administeringDepartments", [])
                if department.get("name")
            ],
            sections=sections,
        )

    def _make_section(
        self,
        summary: AUTitleSummary,
        version_data: dict,
        number: str,
        title: str,
        provision_type: AUProvisionType,
        order: int,
        chapter: str | None,
        part: str | None,
        division: str | None,
    ) -> AULegislationSection:
        fragment = slugify_fragment(f"{provision_type.value}-{number}")
        return AULegislationSection(
            id=f"{summary.title_id}#{fragment}",
            uri=f"{AU_WEB_BASE_URL}/{summary.title_id}/{version_data.get('registerId', summary.title_id)}#{fragment}",
            legislation_id=summary.title_id,
            register_id=version_data.get("registerId", summary.title_id),
            title=title,
            text="",
            number=number,
            provision_type=provision_type,
            order=order,
            year=summary.year,
            legislation_number=summary.number,
            legislation_type=summary.legislation_type,
            chapter=chapter,
            part=part,
            division=division,
        )

    def _is_schedule_heading(self, text: str) -> bool:
        return text.lower().startswith("schedule ")

    def _split_section_heading(self, text: str) -> tuple[str, str]:
        match = re.match(r"^(?P<number>[0-9A-Za-z().-]+)\s+(?P<title>.+)$", text)
        if match:
            return match.group("number"), match.group("title")
        return text, text

    def _split_schedule_heading(self, text: str) -> tuple[str, str]:
        parts = re.split(r"\s*[—-]\s*", text, maxsplit=1)
        number = parts[0]
        title = parts[1] if len(parts) > 1 and parts[1] else parts[0]
        return number, title
