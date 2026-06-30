"""
ATS JSON blob adapter (structured source).

This ATS's own schema does NOT match our canonical field names, so this
adapter owns an explicit internal field-mapping table. Expected shape
(one candidate object, or {"candidates": [...]}):

{
  "candidate_name": "...",
  "contact": {"email": "...", "mobile": "..."},
  "employer": "...",
  "role": "...",
  "address": {"town": "...", "state": "...", "nation": "..."},
  "skill_tags": ["...", "..."],
  "edu": [{"school": "...", "level": "...", "major": "...", "grad_year": 2020}],
  "headline": "..."
}
"""
from __future__ import annotations

import json
from src.models import RawRecord, FieldValue

SOURCE_WEIGHT = 0.85


def _parse_one(obj: dict, idx: int) -> RawRecord:
    source_id = f"ats_json:candidate_{idx}"
    rec = RawRecord(source_name=source_id, source_weight=SOURCE_WEIGHT)

    name = obj.get("candidate_name")
    if name:
        rec.fields["full_name"] = FieldValue(name, source_id, SOURCE_WEIGHT)

    contact = obj.get("contact") or {}
    email = contact.get("email")
    mobile = contact.get("mobile")
    if email:
        rec.fields["emails"] = [FieldValue(email, source_id, SOURCE_WEIGHT)]
    if mobile:
        rec.fields["phones"] = [FieldValue(mobile, source_id, SOURCE_WEIGHT)]

    employer = obj.get("employer")
    role = obj.get("role")
    if employer or role:
        rec.fields["experience"] = [{
            "company": FieldValue(employer, source_id, SOURCE_WEIGHT),
            "title": FieldValue(role, source_id, SOURCE_WEIGHT),
            "start": FieldValue(None, source_id, SOURCE_WEIGHT),
            "end": FieldValue(None, source_id, SOURCE_WEIGHT),
            "summary": FieldValue(None, source_id, SOURCE_WEIGHT),
        }]

    address = obj.get("address") or {}
    city, region, country = address.get("town"), address.get("state"), address.get("nation")
    if city or region or country:
        rec.fields["location"] = {
            "city": FieldValue(city, source_id, SOURCE_WEIGHT),
            "region": FieldValue(region, source_id, SOURCE_WEIGHT),
            "country": FieldValue(country, source_id, SOURCE_WEIGHT),
        }

    skill_tags = obj.get("skill_tags") or []
    if skill_tags:
        rec.fields["skills"] = [FieldValue(s, source_id, SOURCE_WEIGHT) for s in skill_tags if s]

    edu = obj.get("edu") or []
    edu_entries = []
    for e in edu:
        edu_entries.append({
            "institution": FieldValue(e.get("school"), source_id, SOURCE_WEIGHT),
            "degree": FieldValue(e.get("level"), source_id, SOURCE_WEIGHT),
            "field": FieldValue(e.get("major"), source_id, SOURCE_WEIGHT),
            "end_year": FieldValue(e.get("grad_year"), source_id, SOURCE_WEIGHT),
        })
    if edu_entries:
        rec.fields["education"] = edu_entries

    headline = obj.get("headline")
    if headline:
        rec.fields["headline"] = FieldValue(headline, source_id, SOURCE_WEIGHT)

    return rec


def load(path: str) -> list[RawRecord]:
    records: list[RawRecord] = []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return records

    if isinstance(data, dict) and "candidates" in data:
        items = data["candidates"]
    elif isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = [data]
    else:
        return records

    for i, obj in enumerate(items):
        if not isinstance(obj, dict):
            continue
        records.append(_parse_one(obj, i))
    return records
