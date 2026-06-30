# Multi-Source Candidate Data Transformer

Turns messy, multi-source candidate data (recruiter CSV, ATS JSON, GitHub
profile, resume, recruiter notes) into one canonical, deduplicated,
confidence-scored profile per candidate — and projects it into whatever
shape a runtime config asks for.

See `<YourFullName>_<YourEmail>_Eightfold.pdf` for the one-page design
(pipeline diagram, schema, merge policy, config handling, edge cases).
**Rename that PDF and update `FULL_NAME`/`EMAIL` at the top of
`design/make_design_pdf.py`** before submitting — placeholders were used
since I don't have your name/email.

## Quick start

```bash
pip install -r requirements.txt

# Default-schema output only
python -m src.cli --input-dir sample_inputs

# Default schema + a custom runtime-config projection
python -m src.cli --input-dir sample_inputs \
  --config config/example_custom_config.json \
  --out-default output/default_output.json \
  --out-custom output/custom_output.json
```

Output is written to `output/default_output.json` (and
`output/custom_output.json` if `--config` is given). Warnings (skipped
files, dropped values, etc.) print to stdout; pass `--quiet` to suppress.

## Tests

```bash
pip install pytest
pytest tests/ -v
```
31 tests cover normalization, clustering/merge/conflict-resolution, the
projection layer, and end-to-end pipeline robustness (malformed JSON,
corrupt PDF, empty input dir, determinism).

## Pipeline

```
ingest -> extract -> normalize -> cluster & merge -> confidence -> project (config) -> validate -> emit
```

- **Extract**: each source has its own adapter in `src/sources/`. A
  broken/missing/garbage file is caught per-source and skipped with a
  logged warning — it never crashes the run.
- **Normalize** (`src/normalize.py`, `src/normalize_pass.py`): emails,
  phones (-> E.164), dates (-> `YYYY-MM`), countries (-> ISO-3166
  alpha-2), and skills (-> a canonical alias map) are normalized the same
  way regardless of which source they came from.
- **Cluster & merge** (`src/merge.py`): groups per-source records into
  one candidate via:
  1. normalized email (primary key),
  2. normalized full name + last-4 phone digits (fallback),
  3. a deliberately conservative third tier — a record with a name but no
     email/phone (typical of a bare GitHub profile) links to an
     already-identified cluster only if that exact name is unambiguous
     across all identified candidates; otherwise it's kept separate.

  A wrong merge silently contaminates a profile; an honestly-separate
  partial profile is easy to spot and fix. So when in doubt, we don't merge.
- **Confidence**: each source has a trust weight (recruiter CSV 0.9, ATS
  0.85, GitHub 0.8, resume 0.7, notes 0.5; GitHub skills *inferred* from
  repo languages and resume/notes skills from keyword scans get a further
  discount). Multiple sources agreeing on a value boosts confidence
  (capped at 0.99); a conflict keeps the highest-weight value but
  penalizes its confidence and records the conflict in `provenance[]` —
  it's never silently dropped.
- **Project** (`src/project.py`): the only place a runtime config can
  reshape the canonical record — field subset selection, dot-path
  renaming (`"from": "emails[0]"`), per-field `normalize` overrides,
  `include_confidence` / `include_provenance` toggles, and an
  `on_missing` policy (`null` / `omit` / `error`). The canonical record
  itself is never mutated.

## Sources implemented

| Source | Group | Notes |
|---|---|---|
| Recruiter CSV (`src/sources/csv_source.py`) | structured | `name,email,phone,current_company,title` |
| ATS JSON (`src/sources/ats_json_source.py`) | structured | its own field names (`candidate_name`, `contact.email`, `employer`, ...) mapped via an explicit internal table |
| GitHub profile (`src/sources/github_source.py`) | unstructured | real REST API adapter (`load_live`) + an offline fixture loader (`load_from_fixture`), since this sandbox has no outbound network. Skills inferred from repo languages get a confidence discount and `method="inferred_from_repos"` |
| Resume PDF/DOCX/TXT (`src/sources/resume_source.py`) | unstructured | regex/keyword heuristics for email, phone, name, skills, and a `Title — Company (start - end)` experience-line pattern |
| Recruiter notes `.txt` (`src/sources/notes_source.py`) | unstructured | lowest-trust source; fills gaps, never authoritative for identity fields |
| LinkedIn | unstructured | **deliberately not implemented** — no legitimate public API without auth/ToS issues. The adapter slot exists but is intentionally left unbuilt rather than faked. |

File-role detection in `src/pipeline.py::classify_file` is filename-pattern
based (`*.csv`, `*ats*.json`, `*github*.json`, `*notes*.txt`, else
`.pdf`/`.docx`/`.txt` -> resume). Documented there if you add new sample
files with different naming.

## Sample inputs (`sample_inputs/`)

Designed to exercise the merge policy and edge cases end-to-end:

- **Jane Doe** — appears in CSV + ATS + GitHub fixture + resume PDF +
  notes. Demonstrates: multi-source agreement boosting confidence
  (full_name, experience), a genuine conflict (GitHub bio vs. notes
  headline — GitHub wins, lower confidence, both recorded in
  provenance), phone format normalization agreement (`(415) 555-0199`
  vs `4155550199` -> same E.164), and skill canonicalization (`JS` in
  the resume merges with GitHub's inferred `JavaScript`).
- **John Smith** — CSV + resume DOCX, exercises the `.docx` extraction
  path and a second independent merge.
- **Amit Kumar** — ATS only, exercises Indian phone-number normalization
  and the `IN` country mapping.
- **Alex Rivera** — resume `.txt` only, no other source mentions them:
  a legitimate single-source, lower-confidence profile.
- **Unidentified referral notes** — free-text notes with no name, email,
  or phone: deliberately stays its own (mostly empty) candidate rather
  than being guessed into someone else's profile.
- **`malformed_ats_export.json`** and **`resume_corrupted.pdf`** —
  garbage/broken files that must be skipped with a warning, not crash
  the run.

## Known limitations / deliberately descoped

- **Phone/country normalization** is a small hand-written lookup, not
  `phonenumbers`/`pycountry` (no outbound network in this sandbox to
  install them). Swap-in point is `src/normalize.py`.
- **LinkedIn connector**: not implemented (see above).
- **Resume parsing** is regex/heuristic, not an NER/resume-parsing model
  — good enough for the sample inputs, will miss unusual resume layouts.
  Conservative by design: a heuristic that doesn't confidently match
  produces nothing rather than a guess.
- **Fuzzy/ML name matching**: intentionally not used, to keep merges
  deterministic and explainable (see Cluster & merge above).
- **GitHub adapter** supports the real API (`load_live`) but the demo
  runs against a fixture for reproducibility — live calls aren't
  reproducible in CI/offline grading.
- **Scale**: current implementation is in-memory and O(n) source records
  per run; fine for "thousands of candidates" per the brief, would need
  batching/streaming well beyond that.

## Repo layout

```
src/
  models.py        canonical schema dataclasses
  normalize.py      phone/date/country/skill/email normalization
  normalize_pass.py applies normalize.py to extracted records pre-merge
  merge.py          clustering, conflict resolution, confidence
  project.py        runtime-config projection + validation
  pipeline.py       orchestrator (detect -> extract -> ... -> emit)
  cli.py            command-line entrypoint
  sources/          one adapter per source type
config/example_custom_config.json
sample_inputs/      see table above
tests/              31 tests across normalize/merge/project/pipeline
output/             generated by running the CLI
```
