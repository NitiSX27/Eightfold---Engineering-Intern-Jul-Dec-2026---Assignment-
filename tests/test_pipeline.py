import json
import os
import tempfile

from src.pipeline import run_pipeline


def test_pipeline_on_sample_inputs_produces_expected_candidate_count():
    result = run_pipeline("sample_inputs")
    # Jane Doe, John Smith, Amit Kumar, Alex Rivera, unidentified referral = 5
    assert result["candidate_count"] == 5
    names = {c["full_name"] for c in result["default_output"]}
    assert {"Jane Doe", "John Smith", "Amit Kumar", "Alex Rivera"} <= names
    assert None in names  # the unidentified referral has no name


def test_pipeline_skips_malformed_json_without_crashing():
    result = run_pipeline("sample_inputs")
    assert any("malformed_ats_export.json" in w for w in result["warnings"])


def test_pipeline_skips_corrupt_resume_without_crashing():
    result = run_pipeline("sample_inputs")
    assert any("resume_corrupted.pdf" in w for w in result["warnings"])


def test_pipeline_missing_input_dir_does_not_crash():
    result = run_pipeline("sample_inputs/does_not_exist")
    assert result["candidate_count"] == 0
    assert result["warnings"]


def test_pipeline_is_deterministic_across_runs():
    r1 = run_pipeline("sample_inputs")
    r2 = run_pipeline("sample_inputs")
    assert json.dumps(r1["default_output"], sort_keys=True) == json.dumps(r2["default_output"], sort_keys=True)


def test_pipeline_with_custom_config_produces_schema_valid_output():
    config = {
        "fields": [
            {"path": "full_name", "type": "string"},
            {"path": "primary_email", "from": "emails[0]", "type": "string"},
        ],
        "on_missing": "null",
    }
    result = run_pipeline("sample_inputs", config)
    assert result["custom_output"] is not None
    for row in result["custom_output"]:
        assert set(row.keys()) <= {"full_name", "primary_email"}


def test_pipeline_handles_completely_empty_input_dir():
    with tempfile.TemporaryDirectory() as d:
        result = run_pipeline(d)
        assert result["candidate_count"] == 0
        assert result["warnings"] == []
