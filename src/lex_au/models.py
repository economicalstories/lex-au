"""Data models for AU legislation ingestion."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import re
from typing import Any

from lex_au.settings import AU_WEB_BASE_URL


def _compact_dict(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if value not in (None, "", [], {})
    }


class AULegislationType(str, Enum):
    ACT = "act"
    LI = "li"
    NI = "ni"

    @property
    def collection_name(self) -> str:
        return {
            AULegislationType.ACT: "Act",
            AULegislationType.LI: "LegislativeInstrument",
            AULegislationType.NI: "NotifiableInstrument",
        }[self]

    @property
    def display_name(self) -> str:
        return {
            AULegislationType.ACT: "Act",
            AULegislationType.LI: "Legislative Instrument",
            AULegislationType.NI: "Notifiable Instrument",
        }[self]

    def title_id_prefix(self, year: int) -> str:
        return {
            AULegislationType.ACT: f"C{year}A",
            AULegislationType.LI: f"F{year}L",
            AULegislationType.NI: f"F{year}N",
        }[self]

    @classmethod
    def from_collection(cls, collection_name: str) -> "AULegislationType":
        normalised = collection_name.strip().lower()
        mapping = {
            "act": cls.ACT,
            "legislativeinstrument": cls.LI,
            "legislative instrument": cls.LI,
            "notifiableinstrument": cls.NI,
            "notifiable instrument": cls.NI,
        }
        try:
            return mapping[normalised]
        except KeyError as exc:
            raise ValueError(f"Unsupported AU collection: {collection_name}") from exc


class AUProvisionType(str, Enum):
    SECTION = "section"
    SCHEDULE = "schedule"


@dataclass(slots=True)
class AUTitleSummary:
    title_id: str
    title: str
    year: int
    number: int | None
    status: str
    collection: str
    series_type: str
    legislation_type: AULegislationType

    @property
    def uri(self) -> str:
        return f"{AU_WEB_BASE_URL}/{self.title_id}"


@dataclass(slots=True)
class AULegislationSection:
    id: str
    uri: str
    legislation_id: str
    register_id: str
    title: str
    text: str
    number: str
    provision_type: AUProvisionType
    order: int
    year: int
    legislation_number: int | None
    legislation_type: AULegislationType
    chapter: str | None = None
    part: str | None = None
    division: str | None = None

    def get_embedding_text(self) -> str:
        return f"{self.title}\n\n{self.text}".strip()

    def to_vectorize_metadata(self) -> dict[str, Any]:
        return _compact_dict(
            {
                "id": self.id,
                "title": self.title,
                "legislation_id": self.legislation_id,
                "register_id": self.register_id,
                "number": self.number,
                "type": self.legislation_type.value,
                "year": self.year,
                "legislation_number": self.legislation_number,
                "provision_type": self.provision_type.value,
                "chapter": self.chapter,
                "part": self.part,
                "division": self.division,
                "order": self.order,
            }
        )


@dataclass(slots=True)
class AULegislation:
    id: str
    uri: str
    title: str
    description: str
    text: str
    year: int
    number: int | None
    type: AULegislationType
    status: str
    collection: str
    series_type: str
    register_id: str
    version_label: str
    compilation_number: str | None
    making_date: str | None
    registered_at: str | None
    start_date: str | None
    retrospective_start_date: str | None
    end_date: str | None
    administering_departments: list[str] = field(default_factory=list)
    sections: list[AULegislationSection] = field(default_factory=list)

    def get_embedding_text(self) -> str:
        return f"{self.title}\n\n{self.description}\n\n{self.text}".strip()

    def to_vectorize_metadata(self) -> dict[str, Any]:
        return _compact_dict(
            {
                "id": self.id,
                "title": self.title,
                "register_id": self.register_id,
                "type": self.type.value,
                "year": self.year,
                "number": self.number,
                "status": self.status,
                "collection": self.collection,
                "series_type": self.series_type,
                "version_label": self.version_label,
                "compilation_number": self.compilation_number,
                "administering_departments": self.administering_departments,
                "number_of_provisions": len(self.sections),
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def slugify_fragment(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "provision"


def parse_title_id(title_id: str) -> tuple[int | None, int | None]:
    match = re.match(r"^[CF](?P<year>\d{4})[ALNC](?P<number>\d{5})$", title_id)
    if not match:
        return None, None
    return int(match.group("year")), int(match.group("number"))
