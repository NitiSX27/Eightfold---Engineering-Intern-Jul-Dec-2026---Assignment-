"""
Recruiter notes adapter (.txt free text).

Lowest-trust source: useful for filling gaps (a mentioned skill, a
headline-ish summary line) but never treated as authoritative for
identity fields like email/phone unless nothing else has them.
"""
from __future__ import annotations

import re
from src.models import RawRecord, FieldValue
from src.normalize import _SKILL_ALIASES, normalize_email

SOURCE_WEIGHT = 0.5
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(\+?\d[\d\-\.\s\(\)]{8,}\d)")


def load(path: str) -> list[RawRecord]:
    source_id = f"recruiter_notes:{path.split('/')[-1]}"
    rec = RawRecord(source_name=source_id, source_weight=SOURCE_WEIGHT)
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            text = f.read()
    except FileNotFoundError:
        rec.warnings.append("notes file not found")
        return [rec]

    if not text.strip():
        rec.warnings.append("empty notes file")
        return [rec]

    email_match = _EMAIL_RE.search(text)
    if email_match and normalize_email(email_match.group(0)):
        rec.fields["emails"] = [FieldValue(email_match.group(0), source_id, SOURCE_WEIGHT)]

    phone_match = _PHONE_RE.search(text)
    if phone_match:
        rec.fields["phones"] = [FieldValue(phone_match.group(0), source_id, SOURCE_WEIGHT)]

    found_skills = []
    lower_text = text.lower()
    for alias, canonical in _SKILL_ALIASES.items():
        if re.search(r"\b" + re.escape(alias) + r"\b", lower_text) and canonical not in found_skills:
            found_skills.append(canonical)
    if found_skills:
        rec.fields["skills"] = [
            FieldValue(s, source_id, SOURCE_WEIGHT, method="freeform_notes_scan")
            for s in found_skills
        ]

    # Use first sentence as a low-confidence headline candidate.
    first_sentence = re.split(r"[.\n]", text.strip(), maxsplit=1)[0].strip()
    if first_sentence and len(first_sentence) < 140:
        rec.fields["headline"] = FieldValue(first_sentence, source_id, SOURCE_WEIGHT, method="freeform_notes")

    return [rec]
