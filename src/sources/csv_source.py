"""
Recruiter CSV export adapter.

Expected columns (per problem statement): name, email, phone,
current_company, title. Extra/missing columns are tolerated.
"""
from __future__ import annotations

import csv
from src.models import RawRecord, FieldValue

SOURCE_WEIGHT = 0.9


def load(path: str) -> list[RawRecord]:
    records: list[RawRecord] = []
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return records
            for i, row in enumerate(reader):
                source_id = f"recruiter_csv:row_{i + 2}"  # +2 = header + 1-index
                rec = RawRecord(source_name=source_id, source_weight=SOURCE_WEIGHT)

                name = (row.get("name") or "").strip()
                email = (row.get("email") or "").strip()
                phone = (row.get("phone") or "").strip()
                company = (row.get("current_company") or "").strip()
                title = (row.get("title") or "").strip()

                if not any([name, email, phone, company, title]):
                    rec.warnings.append("empty row, skipped")
                    continue

                if name:
                    rec.fields["full_name"] = FieldValue(name, source_id, SOURCE_WEIGHT)
                if email:
                    rec.fields["emails"] = [FieldValue(email, source_id, SOURCE_WEIGHT)]
                if phone:
                    rec.fields["phones"] = [FieldValue(phone, source_id, SOURCE_WEIGHT)]
                if company or title:
                    rec.fields["experience"] = [{
                        "company": FieldValue(company or None, source_id, SOURCE_WEIGHT),
                        "title": FieldValue(title or None, source_id, SOURCE_WEIGHT),
                        "start": FieldValue(None, source_id, SOURCE_WEIGHT),
                        "end": FieldValue(None, source_id, SOURCE_WEIGHT),  # current role
                        "summary": FieldValue(None, source_id, SOURCE_WEIGHT),
                    }]
                records.append(rec)
    except FileNotFoundError:
        pass
    except csv.Error:
        pass
    return records
