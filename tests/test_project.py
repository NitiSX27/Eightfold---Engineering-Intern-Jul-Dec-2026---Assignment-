import pytest
from src.models import CanonicalProfile, SkillEntry
from src.project import project, ProjectionError, validate_against_config


def _profile():
    p = CanonicalProfile(candidate_id="cand_1", full_name="Jane Doe")
    p.emails = ["jane@example.com"]
    p.phones = ["+14155550199"]
    p.skills = [SkillEntry(name="Python", confidence=0.9, sources=["x"])]
    p.overall_confidence = 0.8
    return p


def test_field_subset_and_rename():
    config = {
        "fields": [
            {"path": "name", "from": "full_name", "type": "string"},
            {"path": "primary_email", "from": "emails[0]", "type": "string"},
        ],
        "on_missing": "null",
    }
    out = project(_profile(), config)
    assert out == {"name": "Jane Doe", "primary_email": "jane@example.com"}


def test_on_missing_omit_drops_key():
    config = {
        "fields": [
            {"path": "name", "from": "full_name"},
            {"path": "linkedin", "from": "links.linkedin"},
        ],
        "on_missing": "omit",
    }
    out = project(_profile(), config)
    assert "linkedin" not in out


def test_on_missing_error_raises_for_required_field():
    config = {
        "fields": [{"path": "linkedin", "from": "links.linkedin", "required": True}],
        "on_missing": "error",
    }
    with pytest.raises(ProjectionError):
        project(_profile(), config)


def test_skills_path_mapping_and_canonical_normalize():
    config = {
        "fields": [{"path": "skills", "from": "skills[].name", "type": "string[]", "normalize": "canonical"}],
        "on_missing": "null",
    }
    out = project(_profile(), config)
    assert out["skills"] == ["Python"]


def test_include_confidence_toggle():
    config = {"fields": [{"path": "name", "from": "full_name"}], "include_confidence": True}
    out = project(_profile(), config)
    assert out["overall_confidence"] == 0.8


def test_validate_against_config_flags_missing_required():
    projected = {"name": None}
    config = {"fields": [{"path": "name", "required": True}]}
    errors = validate_against_config(projected, config)
    assert errors
