"""
Projection layer: turns an internal CanonicalProfile into whatever shape
a runtime config asks for. This is the ONLY place that reshapes data for
output — the canonical record itself is never mutated.

Config shape (see config/example_custom_config.json):
{
  "fields": [
    {"path": "full_name", "type": "string", "required": true},
    {"path": "primary_email", "from": "emails[0]", "type": "string", "required": true},
    {"path": "phone", "from": "phones[0]", "type": "string", "normalize": "E164"},
    {"path": "skills", "from": "skills[].name", "type": "string[]", "normalize": "canonical"}
  ],
  "include_confidence": true,
  "include_provenance": false,
  "on_missing": "null"   // "null" | "omit" | "error"
}

`from` defaults to the same dot-path as `path` when omitted, so a config
that just wants the default schema can list bare field names.
"""
from __future__ import annotations

import re
from src.models import CanonicalProfile
from src import normalize as norm

_INDEX_RE = re.compile(r"^(?P<name>[a-zA-Z_]+)\[(?P<idx>\d*)\]$")


class ProjectionError(ValueError):
    pass


def _get_path(obj, path: str):
    """
    Resolves a dot-path against a (nested dict/list) canonical-profile
    dict. Supports `field[0]` (specific index) and `field[].attr` (map
    every item in the list and pull `attr` off each, returning a list).
    Returns None if anything along the path is missing.
    """
    parts = path.split(".")
    current = obj
    for i, part in enumerate(parts):
        m = _INDEX_RE.match(part)
        if m:
            name, idx = m.group("name"), m.group("idx")
            if not isinstance(current, dict) or name not in current:
                return None
            lst = current[name]
            if not isinstance(lst, list):
                return None
            if idx == "":
                # map remaining path over every element
                remainder = ".".join(parts[i + 1:])
                if not remainder:
                    return lst
                return [_get_path(item, remainder) for item in lst]
            try:
                current = lst[int(idx)]
            except (IndexError, ValueError):
                return None
        else:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
    return current


def _apply_normalize(value, normalize: str | None):
    if value is None or normalize is None:
        return value
    if normalize == "E164":
        return norm.normalize_phone(value) if isinstance(value, str) else value
    if normalize == "canonical":
        if isinstance(value, list):
            return [norm.canonical_skill(v) for v in value]
        return norm.canonical_skill(value)
    return value


def _check_type(value, declared_type: str | None) -> bool:
    if declared_type is None or value is None:
        return True
    if declared_type == "string":
        return isinstance(value, str)
    if declared_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if declared_type == "boolean":
        return isinstance(value, bool)
    if declared_type == "string[]":
        return isinstance(value, list) and all(isinstance(v, str) for v in value)
    if declared_type == "object":
        return isinstance(value, dict)
    return True  # unknown declared types are not enforced


def _set_path(out: dict, path: str, value):
    parts = path.split(".")
    current = out
    for p in parts[:-1]:
        current = current.setdefault(p, {})
    current[parts[-1]] = value


def project(profile: CanonicalProfile, config: dict) -> dict:
    profile_dict = profile.to_dict()
    fields_cfg = config.get("fields") or [
        {"path": k} for k in profile_dict.keys() if k != "provenance"
    ]
    on_missing = config.get("on_missing", "null")
    include_confidence = config.get("include_confidence", False)
    include_provenance = config.get("include_provenance", False)

    out: dict = {}
    for fc in fields_cfg:
        out_path = fc["path"]
        from_path = fc.get("from", out_path)
        required = fc.get("required", False)
        declared_type = fc.get("type")
        normalize_rule = fc.get("normalize")

        value = _get_path(profile_dict, from_path)
        value = _apply_normalize(value, normalize_rule)

        is_missing = value is None
        if is_missing:
            if required and on_missing == "error":
                raise ProjectionError(f"required field '{out_path}' (from '{from_path}') is missing "
                                       f"for candidate {profile.candidate_id}")
            if on_missing == "omit":
                continue
            # "null" (default): fall through and write None
            value = None
        else:
            if not _check_type(value, declared_type):
                if on_missing == "error":
                    raise ProjectionError(f"field '{out_path}' failed type check '{declared_type}' "
                                           f"for candidate {profile.candidate_id}")
                value = None if on_missing == "null" else value

        _set_path(out, out_path, value)

    if include_confidence:
        out["overall_confidence"] = profile_dict["overall_confidence"]
    if include_provenance:
        out["provenance"] = profile_dict["provenance"]

    return out


def validate_against_config(projected: dict, config: dict) -> list[str]:
    """Returns a list of validation error strings (empty == valid)."""
    errors = []
    fields_cfg = config.get("fields") or []
    for fc in fields_cfg:
        out_path = fc["path"]
        required = fc.get("required", False)
        value = _get_path(projected, out_path)
        if required and (value is None):
            errors.append(f"required field '{out_path}' missing in projected output")
        declared_type = fc.get("type")
        if value is not None and not _check_type(value, declared_type):
            errors.append(f"field '{out_path}' does not match declared type '{declared_type}'")
    return errors
