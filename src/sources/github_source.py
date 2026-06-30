"""
GitHub profile adapter (unstructured source).

A real run would call the public REST API:
  GET https://api.github.com/users/{username}
  GET https://api.github.com/users/{username}/repos

For this take-home (sandboxed, no outbound network), `load()` accepts
either:
  - a fixture JSON file on disk shaped like the combined API response
    (see sample_inputs/github_octocat.json), or
  - if `allow_live=True` and `requests` succeeds, a live username.

Profile fields (name, bio, location) are higher trust than skills
*inferred* from repo languages, which get a lower confidence and are
tagged with method="inferred_from_repos" so they're never confused
with a skill the candidate explicitly claimed.
"""
from __future__ import annotations

import json
from src.models import RawRecord, FieldValue

SOURCE_WEIGHT = 0.8
INFERRED_SKILL_WEIGHT = 0.6


def _build_record(profile: dict, repos: list[dict], source_id: str) -> RawRecord:
    rec = RawRecord(source_name=source_id, source_weight=SOURCE_WEIGHT)

    name = profile.get("name")
    bio = profile.get("bio")
    location = profile.get("location")
    blog = profile.get("blog")
    login = profile.get("login")

    if name:
        rec.fields["full_name"] = FieldValue(name, source_id, SOURCE_WEIGHT)
    if bio:
        rec.fields["headline"] = FieldValue(bio, source_id, SOURCE_WEIGHT)
    if location:
        city, region = location, None
        if "," in location:
            parts = [p.strip() for p in location.split(",", 1)]
            if len(parts) == 2 and 2 <= len(parts[1]) <= 20:
                city, region = parts[0], parts[1]
        rec.fields["location"] = {
            "city": FieldValue(city, source_id, SOURCE_WEIGHT, method="parsed_location_string"),
            "region": FieldValue(region, source_id, SOURCE_WEIGHT, method="parsed_location_string"),
            "country": FieldValue(None, source_id, SOURCE_WEIGHT),
        }
    if login:
        rec.fields["links"] = {
            "github": FieldValue(f"https://github.com/{login}", source_id, SOURCE_WEIGHT)
        }
    if blog:
        rec.fields.setdefault("links", {})
        rec.fields["links"]["portfolio"] = FieldValue(blog, source_id, SOURCE_WEIGHT)

    languages = {}
    for r in repos:
        lang = r.get("language")
        if lang:
            languages[lang] = languages.get(lang, 0) + 1
    if languages:
        rec.fields["skills"] = [
            FieldValue(lang, source_id, INFERRED_SKILL_WEIGHT, method="inferred_from_repos")
            for lang in languages
        ]
    return rec


def load_from_fixture(path: str) -> list[RawRecord]:
    """fixture file shape: {"profile": {...}, "repos": [...]}"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    profile = data.get("profile") or {}
    repos = data.get("repos") or []
    if not profile:
        return []
    source_id = f"github:{profile.get('login', 'unknown')}"
    return [_build_record(profile, repos, source_id)]


def load_live(username: str, timeout: float = 5.0) -> list[RawRecord]:
    """Live REST API call. Requires outbound network access."""
    try:
        import requests
    except ImportError:
        return []
    try:
        p = requests.get(f"https://api.github.com/users/{username}", timeout=timeout)
        if p.status_code != 200:
            return []
        profile = p.json()
        r = requests.get(f"https://api.github.com/users/{username}/repos", timeout=timeout)
        repos = r.json() if r.status_code == 200 else []
    except Exception:
        return []
    source_id = f"github:{username}"
    return [_build_record(profile, repos, source_id)]


def load(path_or_username: str, allow_live: bool = False) -> list[RawRecord]:
    if path_or_username.endswith(".json"):
        return load_from_fixture(path_or_username)
    if allow_live:
        return load_live(path_or_username)
    return []
