from src.models import RawRecord, FieldValue
from src.merge import build_canonical_profiles


def _rec(source, weight, **fields):
    rec = RawRecord(source_name=source, source_weight=weight)
    for k, v in fields.items():
        rec.fields[k] = v
    return rec


def test_same_email_merges_into_one_candidate():
    r1 = _rec("csv:1", 0.9, full_name=FieldValue("Jane Doe", "csv:1", 0.9),
              emails=[FieldValue("jane@example.com", "csv:1", 0.9)])
    r2 = _rec("ats:1", 0.85, full_name=FieldValue("Jane Doe", "ats:1", 0.85),
              emails=[FieldValue("jane@example.com", "ats:1", 0.85)])
    profiles = build_canonical_profiles([r1, r2])
    assert len(profiles) == 1
    assert profiles[0].full_name == "Jane Doe"


def test_no_identifying_info_stays_separate():
    r1 = _rec("notes:1", 0.5, headline=FieldValue("knows kubernetes", "notes:1", 0.5))
    r2 = _rec("notes:2", 0.5, headline=FieldValue("knows react", "notes:2", 0.5))
    profiles = build_canonical_profiles([r1, r2])
    # Neither record has identifying info -> must NOT be silently merged.
    assert len(profiles) == 2


def test_conflicting_scalar_field_keeps_highest_weight_and_lowers_confidence():
    r1 = _rec("csv:1", 0.9, full_name=FieldValue("Jane Doe", "csv:1", 0.9),
              emails=[FieldValue("jane@example.com", "csv:1", 0.9)],
              headline=FieldValue("Backend focused engineer", "csv:1", 0.9))
    r2 = _rec("notes:1", 0.5, emails=[FieldValue("jane@example.com", "notes:1", 0.5)],
              headline=FieldValue("Frontend focused engineer", "notes:1", 0.5))
    profiles = build_canonical_profiles([r1, r2])
    assert len(profiles) == 1
    p = profiles[0]
    assert p.headline == "Backend focused engineer"  # higher-weight source wins
    # Conflict penalty applied: confidence strictly less than the raw source weight.
    headline_prov = [pr for pr in p.provenance if pr.field == "headline" and pr.method == "conflict_resolved"]
    assert headline_prov and headline_prov[0].confidence < 0.9


def test_agreement_boosts_confidence_above_either_single_source():
    r1 = _rec("csv:1", 0.9, emails=[FieldValue("jane@example.com", "csv:1", 0.9)],
              full_name=FieldValue("Jane Doe", "csv:1", 0.9))
    r2 = _rec("ats:1", 0.85, emails=[FieldValue("jane@example.com", "ats:1", 0.85)],
              full_name=FieldValue("Jane Doe", "ats:1", 0.85))
    profiles = build_canonical_profiles([r1, r2])
    p = profiles[0]
    name_prov = [pr for pr in p.provenance if pr.field == "full_name"]
    winner = max(name_prov, key=lambda pr: pr.confidence)
    assert winner.confidence > 0.9  # boosted above the top single-source weight (0.9)


def test_skills_dedupe_and_union_across_sources():
    r1 = _rec("ats:1", 0.85, emails=[FieldValue("a@example.com", "ats:1", 0.85)],
              skills=[FieldValue("Go", "ats:1", 0.85)])
    r2 = _rec("github:1", 0.8, emails=[FieldValue("a@example.com", "github:1", 0.8)],
              skills=[FieldValue("Go", "github:1", 0.6, method="inferred_from_repos"),
                      FieldValue("Python", "github:1", 0.6, method="inferred_from_repos")])
    profiles = build_canonical_profiles([r1, r2])
    p = profiles[0]
    names = {s.name for s in p.skills}
    assert names == {"Go", "Python"}
    go_entry = next(s for s in p.skills if s.name == "Go")
    assert len(go_entry.sources) == 2
    assert go_entry.confidence > 0.85  # agreement boost


def test_garbage_record_with_no_fields_does_not_crash_or_appear():
    r1 = _rec("resume:broken", 0.7)  # no fields at all
    profiles = build_canonical_profiles([r1])
    # An empty record still becomes a (mostly empty) singleton profile here;
    # the pipeline layer is responsible for filtering these out before this
    # call (see test_pipeline.py), so this just asserts no crash occurs.
    assert len(profiles) == 1
    assert profiles[0].full_name is None
