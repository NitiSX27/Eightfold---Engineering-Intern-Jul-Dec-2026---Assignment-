"""
Pipeline orchestrator.

detect -> extract -> normalize -> cluster/merge -> confidence -> project -> validate -> emit

File-role detection is filename-pattern based (documented in README):
  *.csv                              -> recruiter CSV adapter
  *ats*.json                         -> ATS JSON adapter
  *github*.json                      -> GitHub fixture adapter
  *notes*.txt                        -> recruiter notes adapter
  *.pdf, *.docx, other *.txt         -> resume adapter
A file that doesn't match any pattern, doesn't exist, or fails to parse
is skipped with a warning — it never crashes the run.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from src.models import RawRecord
from src.sources import csv_source, ats_json_source, github_source, resume_source, notes_source
from src.normalize_pass import apply_normalization
from src.merge import build_canonical_profiles
from src.project import project, validate_against_config, ProjectionError

logger = logging.getLogger("pipeline")

DEFAULT_SCHEMA_CONFIG = {
    "fields": [{"path": k} for k in (
        "candidate_id", "full_name", "emails", "phones", "location", "links",
        "headline", "years_experience", "skills", "experience", "education",
        "overall_confidence",
    )],
    "include_confidence": False,   # overall_confidence already included explicitly above
    "include_provenance": True,
}


def classify_file(path: Path) -> str | None:
    name = path.name.lower()
    if path.suffix.lower() == ".csv":
        return "csv"
    if path.suffix.lower() == ".json":
        if "ats" in name:
            return "ats_json"
        if "github" in name:
            return "github"
        return "ats_json"  # best-effort default for an unlabeled JSON blob
    if path.suffix.lower() == ".txt" and "notes" in name:
        return "notes"
    if path.suffix.lower() in (".pdf", ".docx", ".txt"):
        return "resume"
    return None


def extract_all(input_dir: str) -> tuple[list[RawRecord], list[str]]:
    records: list[RawRecord] = []
    warnings: list[str] = []
    base = Path(input_dir)
    if not base.exists():
        warnings.append(f"input dir not found: {input_dir}")
        return records, warnings

    for path in sorted(base.iterdir()):
        if not path.is_file():
            continue
        role = classify_file(path)
        if role is None:
            warnings.append(f"skipped unrecognized file: {path.name}")
            continue
        try:
            if role == "csv":
                new = csv_source.load(str(path))
            elif role == "ats_json":
                new = ats_json_source.load(str(path))
            elif role == "github":
                new = github_source.load(str(path))
            elif role == "notes":
                new = notes_source.load(str(path))
            elif role == "resume":
                new = resume_source.load(str(path))
            else:
                new = []
        except Exception as e:  # noqa: BLE001 - a broken source must never crash the run
            warnings.append(f"failed to parse {path.name} ({role}): {e}")
            continue

        if not new:
            warnings.append(f"no records extracted from {path.name} ({role})")
        for rec in new:
            warnings.extend(f"{path.name}: {w}" for w in rec.warnings)
            if not rec.fields:
                warnings.append(f"{path.name}: produced no usable fields, excluded from clustering")
                continue
            records.append(rec)

    return records, warnings


def run_pipeline(input_dir: str, custom_config: dict | None = None) -> dict:
    raw_records, warnings = extract_all(input_dir)
    raw_records = apply_normalization(raw_records)
    profiles = build_canonical_profiles(raw_records)

    default_output = []
    for p in profiles:
        default_output.append(project(p, DEFAULT_SCHEMA_CONFIG))

    custom_output = None
    custom_errors = []
    if custom_config:
        custom_output = []
        for p in profiles:
            try:
                projected = project(p, custom_config)
            except ProjectionError as e:
                custom_errors.append(str(e))
                continue
            custom_errors.extend(validate_against_config(projected, custom_config))
            custom_output.append(projected)

    return {
        "default_output": default_output,
        "custom_output": custom_output,
        "custom_validation_errors": custom_errors,
        "warnings": warnings,
        "candidate_count": len(profiles),
        "source_record_count": len(raw_records),
    }


def load_config(path: str | None) -> dict | None:
    if not path:
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)
