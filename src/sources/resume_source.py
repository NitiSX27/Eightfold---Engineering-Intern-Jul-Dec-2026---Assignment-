"""
Resume adapter (unstructured source: PDF / DOCX / plain text prose).

Resumes are free text, so extraction here is heuristic by nature:
  - email / phone via regex
  - skills via keyword scan against the known skill-alias table
  - experience via a light "Company — Title (date - date)" line pattern

This is intentionally conservative: if a heuristic doesn't confidently
match, we leave the field out rather than emitting a guess. Documented
as a known limitation in the README (a production system would use an
NER/resume-parsing model here).
"""
from __future__ import annotations

import re
from src.models import RawRecord, FieldValue
from src.normalize import _SKILL_ALIASES, normalize_email

SOURCE_WEIGHT = 0.7
INFERRED_SKILL_WEIGHT = 0.55

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(\+?\d[\d\-\.\s\(\)]{8,}\d)")
_EXP_LINE_RE = re.compile(
    r"^(?P<title>[A-Za-z0-9&/.,\- ]+?)\s*[\u2014\-|@]\s*(?P<company>[A-Za-z0-9&.,\- ]+?)"
    r"\s*\(?(?P<start>[A-Za-z]{3,9}\.?\s*\d{4}|\d{4})\s*[\u2013\-to]+\s*"
    r"(?P<end>[A-Za-z]{3,9}\.?\s*\d{4}|\d{4}|Present|Current)\)?\s*$",
    re.IGNORECASE,
)


def extract_text(path: str) -> str:
    if path.lower().endswith(".pdf"):
        import pdfplumber
        text = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text.append(page.extract_text() or "")
        return "\n".join(text)
    if path.lower().endswith(".docx"):
        import docx
        d = docx.Document(path)
        return "\n".join(p.text for p in d.paragraphs)
    with open(path, encoding="utf-8", errors="ignore") as f:
        return f.read()


def load(path: str) -> list[RawRecord]:
    source_id = f"resume:{path.split('/')[-1]}"
    rec = RawRecord(source_name=source_id, source_weight=SOURCE_WEIGHT)
    try:
        text = extract_text(path)
    except Exception as e:
        rec.warnings.append(f"unreadable resume file: {e}")
        return [rec]

    if not text or not text.strip():
        rec.warnings.append("resume produced no extractable text")
        return [rec]

    email_match = _EMAIL_RE.search(text)
    if email_match and normalize_email(email_match.group(0)):
        rec.fields["emails"] = [FieldValue(email_match.group(0), source_id, SOURCE_WEIGHT)]

    phone_match = _PHONE_RE.search(text)
    if phone_match:
        rec.fields["phones"] = [FieldValue(phone_match.group(0), source_id, SOURCE_WEIGHT)]

    # First non-empty line is frequently the candidate's name on a resume.
    first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), None)
    if first_line and len(first_line.split()) <= 5 and not _EMAIL_RE.search(first_line):
        rec.fields["full_name"] = FieldValue(first_line, source_id, SOURCE_WEIGHT, method="first_line_heuristic")

    found_skills = []
    lower_text = text.lower()
    for alias, canonical in _SKILL_ALIASES.items():
        pattern = r"\b" + re.escape(alias) + r"\b"
        if re.search(pattern, lower_text):
            if canonical not in [s for s in found_skills]:
                found_skills.append(canonical)
    if found_skills:
        rec.fields["skills"] = [
            FieldValue(s, source_id, INFERRED_SKILL_WEIGHT, method="regex_keyword_scan")
            for s in found_skills
        ]

    experience_entries = []
    for line in text.splitlines():
        m = _EXP_LINE_RE.match(line.strip())
        if m:
            experience_entries.append({
                "company": FieldValue(m.group("company").strip(), source_id, SOURCE_WEIGHT),
                "title": FieldValue(m.group("title").strip(), source_id, SOURCE_WEIGHT),
                "start": FieldValue(m.group("start").strip(), source_id, SOURCE_WEIGHT),
                "end": FieldValue(
                    None if m.group("end").lower() in ("present", "current") else m.group("end").strip(),
                    source_id, SOURCE_WEIGHT,
                ),
                "summary": FieldValue(None, source_id, SOURCE_WEIGHT),
            })
    if experience_entries:
        rec.fields["experience"] = experience_entries

    return [rec]
