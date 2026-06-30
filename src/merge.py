"""
Clusters per-source RawRecords into one CanonicalProfile per real
candidate, resolves conflicts, and assigns confidence.

Match policy
------------
1. Primary key: normalized email. Any two records sharing a normalized
   email are the same candidate.
2. Fallback key: normalized full name + last 4 digits of a phone number.
   Used only when at least one of the two records has no email to match
   on (a record that already matched by email never also needs the
   fallback).
3. No match on either key -> kept as its own (separate) candidate. We
   deliberately do not do fuzzy/ML name matching: a wrong merge silently
   contaminates a profile, while two honestly-separate partial profiles
   are easy to spot and fix downstream.

This is implemented as union-find over record indices so matches are
transitive (A~B via email, B~C via name+phone => A,B,C one cluster).
"""
from __future__ import annotations

import hashlib
from src.models import RawRecord, FieldValue, CanonicalProfile, Provenance, SkillEntry, \
    ExperienceEntry, EducationEntry, Location, Links
from src.normalize import normalize_name_key

AGREEMENT_BONUS_PER_EXTRA_SOURCE = 0.1
CONFLICT_PENALTY = 0.8
MAX_CONFIDENCE = 0.99


class UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def _record_email_key(rec: RawRecord) -> str | None:
    emails = rec.fields.get("emails")
    if emails:
        return emails[0].value
    return None


def _record_namephone_key(rec: RawRecord) -> str | None:
    name_fv = rec.fields.get("full_name")
    phones = rec.fields.get("phones")
    if not name_fv or not phones:
        return None
    name_key = normalize_name_key(name_fv.value)
    if not name_key:
        return None
    last4 = "".join(ch for ch in phones[0].value if ch.isdigit())[-4:]
    if len(last4) < 4:
        return None
    return f"{name_key}|{last4}"


def cluster_records(records: list[RawRecord]) -> list[list[RawRecord]]:
    n = len(records)
    uf = UnionFind(n)

    email_groups: dict[str, list[int]] = {}
    namephone_groups: dict[str, list[int]] = {}
    for i, rec in enumerate(records):
        ek = _record_email_key(rec)
        if ek:
            email_groups.setdefault(ek, []).append(i)
        npk = _record_namephone_key(rec)
        if npk:
            namephone_groups.setdefault(npk, []).append(i)

    for group in list(email_groups.values()) + list(namephone_groups.values()):
        for idx in group[1:]:
            uf.union(group[0], idx)

    # Tier 3 (conservative): a record with a name but neither an email nor
    # a phone (typical of a bare GitHub profile) cannot use tiers 1/2 at
    # all. Rather than leave it permanently stranded, link it to an
    # already-identified cluster (one containing an email) IFF that exact
    # normalized name is unambiguous -- i.e. exactly one identified cluster
    # has a record with that name. If the name is shared by zero or by
    # more than one identified cluster, we deliberately do NOT merge:
    # a wrong merge is worse than an honestly-separate partial profile.
    root_names: dict[int, set[str]] = {}
    identified_roots: set[int] = set()
    for i, rec in enumerate(records):
        root = uf.find(i)
        name_fv = rec.fields.get("full_name")
        if name_fv:
            nk = normalize_name_key(name_fv.value)
            if nk:
                root_names.setdefault(root, set()).add(nk)
        if _record_email_key(rec) is not None:
            identified_roots.add(uf.find(i))

    name_to_identified_roots: dict[str, set[int]] = {}
    for root in identified_roots:
        for nk in root_names.get(root, ()):
            name_to_identified_roots.setdefault(nk, set()).add(root)

    for i, rec in enumerate(records):
        if _record_email_key(rec) is not None or _record_namephone_key(rec) is not None:
            continue  # already eligible for tier 1/2, leave as-is
        name_fv = rec.fields.get("full_name")
        if not name_fv:
            continue
        nk = normalize_name_key(name_fv.value)
        if not nk:
            continue
        candidates = name_to_identified_roots.get(nk, set())
        my_root = uf.find(i)
        candidates = candidates - {my_root}
        if len(candidates) == 1:
            uf.union(i, next(iter(candidates)))
            rec.warnings.append(
                f"linked to existing candidate via unambiguous name match on {name_fv.value!r}"
            )

    clusters: dict[int, list[RawRecord]] = {}
    for i, rec in enumerate(records):
        root = uf.find(i)
        clusters.setdefault(root, []).append(rec)
    return list(clusters.values())


def _candidate_id(cluster: list[RawRecord]) -> str:
    for rec in cluster:
        ek = _record_email_key(rec)
        if ek:
            return "cand_" + hashlib.sha1(ek.encode()).hexdigest()[:12]
    for rec in cluster:
        npk = _record_namephone_key(rec)
        if npk:
            return "cand_" + hashlib.sha1(npk.encode()).hexdigest()[:12]
    # No identifying info at all: stable-ish hash of source name so the
    # *same single source* re-run still gets the same id (determinism).
    seed = cluster[0].source_name if cluster else "unknown"
    return "cand_" + hashlib.sha1(seed.encode()).hexdigest()[:12]


def _merge_scalar(field_name: str, contributions: list[FieldValue]) -> tuple[object, float, list[Provenance]]:
    contributions = [c for c in contributions if c.value not in (None, "")]
    if not contributions:
        return None, 0.0, []

    # Group by normalized comparable form (case/whitespace-insensitive for strings).
    def norm_cmp(v):
        return v.strip().lower() if isinstance(v, str) else v

    groups: dict = {}
    for c in contributions:
        groups.setdefault(norm_cmp(c.value), []).append(c)

    if len(groups) == 1:
        group = next(iter(groups.values()))
        winner = max(group, key=lambda c: c.weight)
        confidence = min(MAX_CONFIDENCE, winner.weight + AGREEMENT_BONUS_PER_EXTRA_SOURCE * (len(group) - 1))
        prov = [Provenance(field_name, c.source, "merged_agreement" if len(group) > 1 else c.method, confidence
                            if c is winner else c.weight) for c in group]
        return winner.value, confidence, prov

    # Conflict: multiple distinct values. Highest-weight value wins, penalized.
    best_group_key = max(groups, key=lambda k: max(c.weight for c in groups[k]))
    winner = max(groups[best_group_key], key=lambda c: c.weight)
    confidence = round(winner.weight * CONFLICT_PENALTY, 3)
    prov = [Provenance(field_name, winner.source, "conflict_resolved", confidence)]
    for key, group in groups.items():
        if key == best_group_key:
            continue
        for c in group:
            prov.append(Provenance(field_name, c.source, "conflict_discarded", c.weight))
    return winner.value, confidence, prov


def _merge_array_unique(field_name: str, contributions: list[FieldValue]) -> tuple[list, list[Provenance]]:
    seen = {}
    for c in sorted(contributions, key=lambda c: -c.weight):
        if c.value in (None, ""):
            continue
        if c.value not in seen:
            seen[c.value] = c
    values = list(seen.keys())
    prov = [Provenance(field_name, c.source, "merged_union" if len(contributions) > 1 else c.method, c.weight)
            for c in seen.values()]
    return values, prov


def _merge_skills(contributions: list[FieldValue]) -> tuple[list[SkillEntry], list[Provenance]]:
    groups: dict[str, list[FieldValue]] = {}
    for c in contributions:
        if not c.value:
            continue
        groups.setdefault(c.value, []).append(c)
    entries, prov = [], []
    for name, group in groups.items():
        if len(group) == 1:
            conf = group[0].weight
        else:
            conf = min(MAX_CONFIDENCE, max(g.weight for g in group) + AGREEMENT_BONUS_PER_EXTRA_SOURCE * (len(group) - 1))
        sources = [g.source for g in group]
        entries.append(SkillEntry(name=name, confidence=round(conf, 3), sources=sources))
        for g in group:
            prov.append(Provenance("skills[]." + name, g.source, g.method, g.weight))
    entries.sort(key=lambda e: -e.confidence)
    return entries, prov


def _merge_nested_list(field_name: str, entries_lists: list[list[dict]], match_keys: tuple[str, str]) -> tuple[list, list[Provenance]]:
    """
    entries_lists: list of (list of dict[str, FieldValue]) — one list per
    contributing record. match_keys e.g. ("company", "title") for
    experience or ("institution", "degree") for education.
    """
    buckets: dict[tuple, list[dict]] = {}
    order: list[tuple] = []
    k1, k2 = match_keys
    for entries in entries_lists:
        for entry in entries:
            v1 = entry.get(k1)
            v2 = entry.get(k2)
            key = (
                (v1.value or "").strip().lower() if v1 and v1.value else "",
                (v2.value or "").strip().lower() if v2 and v2.value else "",
            )
            if key == ("", ""):
                key = (f"_singleton_{id(entry)}", "")
            if key not in buckets:
                buckets[key] = []
                order.append(key)
            buckets[key].append(entry)

    merged_entries = []
    prov_all = []
    for key in order:
        group = buckets[key]
        sub_field_names = set()
        for e in group:
            sub_field_names |= set(e.keys())
        merged = {}
        for sf in sub_field_names:
            contributions = [e[sf] for e in group if e.get(sf) is not None and e[sf].value not in (None, "")]
            if not contributions:
                merged[sf] = None
                continue
            value, conf, prov = _merge_scalar(f"{field_name}[].{sf}", contributions)
            merged[sf] = value
            prov_all.extend(prov)
        merged_entries.append(merged)
    return merged_entries, prov_all


def build_canonical_profiles(records: list[RawRecord]) -> list[CanonicalProfile]:
    clusters = cluster_records(records)
    profiles = []

    for cluster in clusters:
        candidate_id = _candidate_id(cluster)
        profile = CanonicalProfile(candidate_id=candidate_id)
        all_prov: list[Provenance] = []
        confidences: list[float] = []

        # full_name
        name_contribs = [r.fields["full_name"] for r in cluster if "full_name" in r.fields]
        value, conf, prov = _merge_scalar("full_name", name_contribs)
        profile.full_name = value
        all_prov.extend(prov)
        if value is not None:
            confidences.append(conf)

        # headline
        headline_contribs = [r.fields["headline"] for r in cluster if "headline" in r.fields]
        value, conf, prov = _merge_scalar("headline", headline_contribs)
        profile.headline = value
        all_prov.extend(prov)
        if value is not None:
            confidences.append(conf)

        # emails / phones
        email_contribs = [fv for r in cluster for fv in r.fields.get("emails", [])]
        emails, prov = _merge_array_unique("emails", email_contribs)
        profile.emails = emails
        all_prov.extend(prov)

        phone_contribs = [fv for r in cluster for fv in r.fields.get("phones", [])]
        phones, prov = _merge_array_unique("phones", phone_contribs)
        profile.phones = phones
        all_prov.extend(prov)

        # location
        loc_fields = {"city": [], "region": [], "country": []}
        for r in cluster:
            loc = r.fields.get("location")
            if not loc:
                continue
            for k in loc_fields:
                if k in loc and loc[k].value not in (None, ""):
                    loc_fields[k].append(loc[k])
        loc = Location()
        for k in ("city", "region", "country"):
            value, conf, prov = _merge_scalar(f"location.{k}", loc_fields[k])
            setattr(loc, k, value)
            all_prov.extend(prov)
            if value is not None:
                confidences.append(conf)
        profile.location = loc

        # links
        links = Links()
        link_contribs = {"linkedin": [], "github": [], "portfolio": []}
        other_vals = []
        for r in cluster:
            lk = r.fields.get("links")
            if not lk:
                continue
            for k in link_contribs:
                if k in lk and lk[k].value:
                    link_contribs[k].append(lk[k])
            if "other" in lk:
                other_vals.extend(v.value for v in lk["other"] if v.value)
        for k in ("linkedin", "github", "portfolio"):
            value, conf, prov = _merge_scalar(f"links.{k}", link_contribs[k])
            setattr(links, k, value)
            all_prov.extend(prov)
        links.other = sorted(set(other_vals))
        profile.links = links

        # years_experience
        ye_contribs = [r.fields["years_experience"] for r in cluster if "years_experience" in r.fields]
        value, conf, prov = _merge_scalar("years_experience", ye_contribs)
        profile.years_experience = value
        all_prov.extend(prov)
        if value is not None:
            confidences.append(conf)

        # skills
        skill_contribs = [fv for r in cluster for fv in r.fields.get("skills", [])]
        skills, prov = _merge_skills(skill_contribs)
        profile.skills = skills
        all_prov.extend(prov)
        confidences.extend(s.confidence for s in skills)

        # experience
        exp_lists = [r.fields["experience"] for r in cluster if "experience" in r.fields]
        # exp_lists entries are list[dict[str, FieldValue]] (already that shape from sources)
        merged_exp, prov = _merge_nested_list("experience", exp_lists, ("company", "title"))
        profile.experience = [
            ExperienceEntry(
                company=e.get("company"), title=e.get("title"),
                start=e.get("start"), end=e.get("end"), summary=e.get("summary"),
            ) for e in merged_exp
        ]
        all_prov.extend(prov)

        # education
        edu_lists = [r.fields["education"] for r in cluster if "education" in r.fields]
        merged_edu, prov = _merge_nested_list("education", edu_lists, ("institution", "degree"))
        profile.education = [
            EducationEntry(
                institution=e.get("institution"), degree=e.get("degree"),
                field=e.get("field"), end_year=e.get("end_year"),
            ) for e in merged_edu
        ]
        all_prov.extend(prov)

        profile.provenance = all_prov
        profile.overall_confidence = round(sum(confidences) / len(confidences), 3) if confidences else 0.0

        profiles.append(profile)

    profiles.sort(key=lambda p: p.candidate_id)
    return profiles
