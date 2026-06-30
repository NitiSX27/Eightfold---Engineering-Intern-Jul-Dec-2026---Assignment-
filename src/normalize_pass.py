"""
Applies field-level normalization to RawRecords extracted from sources,
*before* clustering/merge. Keeping this as a separate pass (rather than
baking normalization into each source adapter) means every source goes
through the same rules and the same is true for any new source added later.

Invalid values are dropped (never invented/guessed) and a warning is
recorded on the record so it's visible in logs/tests.
"""
from __future__ import annotations

from src.models import RawRecord, FieldValue
from src import normalize as norm


def _normalize_field_value(field_name: str, fv: FieldValue) -> FieldValue | None:
    if fv.value is None:
        return None
    if field_name == "emails":
        v = norm.normalize_email(fv.value)
        if v is None:
            return None
        return FieldValue(v, fv.source, fv.weight, method="normalized_email")
    if field_name == "phones":
        v = norm.normalize_phone(fv.value)
        if v is None:
            return None
        return FieldValue(v, fv.source, fv.weight, method="normalized_e164")
    if field_name == "skills":
        v = norm.canonical_skill(fv.value)
        if v is None:
            return None
        return FieldValue(v, fv.source, fv.weight, method=fv.method or "canonicalized_skill")
    return fv


def apply_normalization(records: list[RawRecord]) -> list[RawRecord]:
    for rec in records:
        # Scalar/array top-level fields handled generically.
        for field_name in ("emails", "phones", "skills"):
            values = rec.fields.get(field_name)
            if not values:
                continue
            normalized = []
            for fv in values:
                nv = _normalize_field_value(field_name, fv)
                if nv is None:
                    rec.warnings.append(f"dropped unparsable {field_name[:-1]}: {fv.value!r}")
                    continue
                normalized.append(nv)
            rec.fields[field_name] = normalized

        # location.country
        loc = rec.fields.get("location")
        if loc and "country" in loc and loc["country"].value:
            raw_country = loc["country"].value
            v = norm.normalize_country(raw_country)
            loc["country"] = FieldValue(v, loc["country"].source, loc["country"].weight,
                                         method="normalized_iso3166" if v else "unrecognized_country")
            if v is None:
                rec.warnings.append(f"unrecognized country: {raw_country!r}")

        # experience start/end dates
        exp = rec.fields.get("experience")
        if exp:
            for entry in exp:
                for date_field in ("start", "end"):
                    fv = entry.get(date_field)
                    if fv and fv.value:
                        normalized_val, method = norm.normalize_date(fv.value)
                        entry[date_field] = FieldValue(normalized_val, fv.source, fv.weight, method=method)
                        if normalized_val is None and method != "missing":
                            rec.warnings.append(f"{date_field} date not parsed: {fv.value!r} ({method})")

        # education end_year -> int
        edu = rec.fields.get("education")
        if edu:
            for entry in edu:
                fv = entry.get("end_year")
                if fv and fv.value not in (None, ""):
                    try:
                        entry["end_year"] = FieldValue(int(fv.value), fv.source, fv.weight, method="parsed_year")
                    except (ValueError, TypeError):
                        entry["end_year"] = FieldValue(None, fv.source, fv.weight, method="unparsed_year")
                        rec.warnings.append(f"end_year not parsed: {fv.value!r}")
    return records
