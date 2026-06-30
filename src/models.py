"""
Canonical data model for the Multi-Source Candidate Data Transformer.

These dataclasses represent the *internal* canonical record. The
runtime-config-driven projection layer (project.py) is the only thing
allowed to reshape this into an output document, so this module stays
free of any output-format concerns.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Provenance:
    field: str          # dot-path into the canonical record, e.g. "phones[0]"
    source: str          # source identifier, e.g. "recruiter_csv:row_3"
    method: str          # how the value was produced, e.g. "direct", "normalized_e164",
                          # "merged_majority", "conflict_resolved", "inferred_from_repos",
                          # "unparsed_date"
    confidence: float = 0.0

    def to_dict(self):
        return asdict(self)


@dataclass
class SkillEntry:
    name: str
    confidence: float
    sources: list[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


@dataclass
class ExperienceEntry:
    company: Optional[str] = None
    title: Optional[str] = None
    start: Optional[str] = None   # YYYY-MM
    end: Optional[str] = None     # YYYY-MM or None for current
    summary: Optional[str] = None

    def to_dict(self):
        return asdict(self)


@dataclass
class EducationEntry:
    institution: Optional[str] = None
    degree: Optional[str] = None
    field: Optional[str] = None
    end_year: Optional[int] = None

    def to_dict(self):
        return asdict(self)


@dataclass
class Location:
    city: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None  # ISO-3166 alpha-2

    def to_dict(self):
        return asdict(self)


@dataclass
class Links:
    linkedin: Optional[str] = None
    github: Optional[str] = None
    portfolio: Optional[str] = None
    other: list[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


@dataclass
class CanonicalProfile:
    candidate_id: str
    full_name: Optional[str] = None
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    location: Location = field(default_factory=Location)
    links: Links = field(default_factory=Links)
    headline: Optional[str] = None
    years_experience: Optional[float] = None
    skills: list[SkillEntry] = field(default_factory=list)
    experience: list[ExperienceEntry] = field(default_factory=list)
    education: list[EducationEntry] = field(default_factory=list)
    provenance: list[Provenance] = field(default_factory=list)
    overall_confidence: float = 0.0

    def to_dict(self):
        return {
            "candidate_id": self.candidate_id,
            "full_name": self.full_name,
            "emails": self.emails,
            "phones": self.phones,
            "location": self.location.to_dict(),
            "links": self.links.to_dict(),
            "headline": self.headline,
            "years_experience": self.years_experience,
            "skills": [s.to_dict() for s in self.skills],
            "experience": [e.to_dict() for e in self.experience],
            "education": [e.to_dict() for e in self.education],
            "provenance": [p.to_dict() for p in self.provenance],
            "overall_confidence": round(self.overall_confidence, 3),
        }


@dataclass
class FieldValue:
    """A single candidate value for a field, contributed by one source."""
    value: object
    source: str
    weight: float
    method: str = "direct"


@dataclass
class RawRecord:
    """
    One source's view of (possibly) one candidate, prior to clustering.
    Field values are stored loosely as a dict of field-name -> FieldValue
    or list[FieldValue] (for array-shaped fields like skills/experience).
    """
    source_name: str
    source_weight: float
    fields: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
