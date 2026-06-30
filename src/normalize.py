"""
Normalization helpers.

No external phone/country libraries are available in this environment
(no network access to install `phonenumbers` / `pycountry`), so these
are deliberately lightweight, deterministic, regex/table-based
implementations. In a production build these would be swapped for
`phonenumbers` and `pycountry` (noted in README as a known limitation).
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

# --------------------------------------------------------------------------
# Email
# --------------------------------------------------------------------------
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def normalize_email(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    val = raw.strip().lower()
    if not _EMAIL_RE.match(val):
        return None
    return val


# --------------------------------------------------------------------------
# Phone -> E.164-ish
# --------------------------------------------------------------------------
_COUNTRY_CALLING_CODES = {
    "US": "1", "CA": "1", "IN": "91", "GB": "44", "AU": "61",
    "DE": "49", "FR": "33", "SG": "65", "AE": "971",
}


def normalize_phone(raw: Optional[str], default_region: str = "US") -> Optional[str]:
    """
    Best-effort E.164 normalization without a phone metadata library.
    Returns None (never a guessed/invented number) if it can't confidently
    produce a plausible E.164 string.
    """
    if not raw:
        return None
    s = raw.strip()
    has_plus = s.startswith("+")
    digits = re.sub(r"\D", "", s)
    if not digits:
        return None

    if has_plus:
        if 8 <= len(digits) <= 15:
            return f"+{digits}"
        return None

    # No explicit country code given.
    default_cc = _COUNTRY_CALLING_CODES.get(default_region, "1")

    if default_cc == "1":
        # NANP: 10 digits, or 11 digits starting with 1
        if len(digits) == 11 and digits.startswith("1"):
            return f"+{digits}"
        if len(digits) == 10:
            return f"+1{digits}"
        return None

    if default_cc == "91":
        # India: 10 digit local number, drop leading 0 if present
        local = digits[1:] if digits.startswith("0") and len(digits) == 11 else digits
        if len(local) == 10:
            return f"+91{local}"
        return None

    # Generic fallback: trust length sanity check only
    if 8 <= len(digits) <= 12:
        return f"+{default_cc}{digits.lstrip('0')}"
    return None


# --------------------------------------------------------------------------
# Dates -> YYYY-MM
# --------------------------------------------------------------------------
_MONTHS = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
    "jul": "07", "aug": "08", "sep": "09", "sept": "09", "oct": "10", "nov": "11", "dec": "12",
}
_DATE_PATTERNS = [
    re.compile(r"^(?P<y>\d{4})-(?P<m>\d{1,2})$"),                       # 2020-01
    re.compile(r"^(?P<m>\d{1,2})/(?P<y>\d{4})$"),                       # 01/2020
    re.compile(r"^(?P<mon>[A-Za-z]{3,9})\.?\s+(?P<y>\d{4})$"),          # Jan 2020 / January 2020
    re.compile(r"^(?P<y>\d{4})$"),                                      # 2020 (year only -> ambiguous month)
]


def normalize_date(raw: Optional[str]) -> tuple[Optional[str], str]:
    """
    Returns (normalized_value_or_None, method).
    method is "normalized_date", "unparsed_date", or "year_only_no_month".
    Never invents a month that wasn't implied by the input.
    """
    if not raw or not str(raw).strip():
        return None, "missing"
    s = str(raw).strip()

    m = _DATE_PATTERNS[0].match(s)
    if m:
        return f"{m.group('y')}-{int(m.group('m')):02d}", "normalized_date"

    m = _DATE_PATTERNS[1].match(s)
    if m:
        return f"{m.group('y')}-{int(m.group('m')):02d}", "normalized_date"

    m = _DATE_PATTERNS[2].match(s)
    if m:
        mon_key = m.group("mon")[:3].lower()
        if mon_key in _MONTHS:
            return f"{m.group('y')}-{_MONTHS[mon_key]}", "normalized_date"

    m = _DATE_PATTERNS[3].match(s)
    if m:
        # Year only: we will NOT invent a month. Caller decides whether to
        # keep as null or as a partial year marker; we return None for the
        # canonical (strict YYYY-MM) field and flag the method.
        return None, "year_only_no_month"

    return None, "unparsed_date"


# --------------------------------------------------------------------------
# Country -> ISO-3166 alpha-2 (small lookup; not exhaustive, documented)
# --------------------------------------------------------------------------
_COUNTRY_MAP = {
    "united states": "US", "united states of america": "US", "usa": "US", "us": "US",
    "india": "IN", "in": "IN",
    "united kingdom": "GB", "uk": "GB", "great britain": "GB", "england": "GB",
    "canada": "CA", "ca": "CA",
    "australia": "AU", "au": "AU",
    "germany": "DE", "de": "DE",
    "france": "FR", "fr": "FR",
    "singapore": "SG", "sg": "SG",
    "united arab emirates": "AE", "uae": "AE",
}


def normalize_country(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    key = raw.strip().lower()
    if key.upper() in _COUNTRY_MAP.values() and len(raw.strip()) == 2:
        return raw.strip().upper()
    return _COUNTRY_MAP.get(key)


# --------------------------------------------------------------------------
# Skills canonicalization
# --------------------------------------------------------------------------
_SKILL_ALIASES = {
    "js": "JavaScript", "javascript": "JavaScript", "node": "Node.js", "nodejs": "Node.js",
    "node.js": "Node.js", "ts": "TypeScript", "typescript": "TypeScript",
    "py": "Python", "python": "Python", "python3": "Python",
    "react": "React", "reactjs": "React", "react.js": "React",
    "golang": "Go", "go": "Go",
    "postgres": "PostgreSQL", "postgresql": "PostgreSQL",
    "k8s": "Kubernetes", "kubernetes": "Kubernetes",
    "ml": "Machine Learning", "machine learning": "Machine Learning",
    "aws": "AWS", "amazon web services": "AWS",
    "c++": "C++", "cpp": "C++",
    "c#": "C#", "csharp": "C#",
    "sql": "SQL",
    "docker": "Docker",
    "java": "Java",
    "html": "HTML", "css": "CSS",
}


def canonical_skill(raw: Optional[str]) -> Optional[str]:
    if not raw or not raw.strip():
        return None
    key = raw.strip().lower()
    if key in _SKILL_ALIASES:
        return _SKILL_ALIASES[key]
    # Title-case unknown skills as a reasonable canonical default
    return raw.strip()


# --------------------------------------------------------------------------
# Name normalization (for fallback fuzzy-free matching)
# --------------------------------------------------------------------------
def normalize_name_key(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    key = re.sub(r"[^a-z\s]", "", raw.strip().lower())
    key = re.sub(r"\s+", " ", key).strip()
    return key or None
