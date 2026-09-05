# Archive: 27 June 2026 threshold-tuning session

This folder holds the working documents from one intensive debugging/tuning
session (27 June, plus one carried-over file from 28 June). It's kept for
historical traceability, not as reading material — if you're new to the
project, **you almost certainly don't need to open anything in here.**

## What actually came out of this session (read these instead)

- **Person resolution threshold settled at 0.45** — see
  [`../../analysis/THRESHOLD_DECISION_REPORT.md`](../../analysis/THRESHOLD_DECISION_REPORT.md)
  for the reasoning, or just `src/constants.py` /
  `PERSON_RESOLUTION_THRESHOLD` for the current value.
- **The Connell Harvey merge error** (Person linked across two households in
  the same census) led directly to the same-census-linking DB constraint —
  see migration `005_prevent_same_census_links.sql`.
- **Phase 3 (role consistency weighting)** — implemented, regressed, root
  caused, and fixed; the canonical account of this is
  [`../../changelog/changelog_summary.md`](../../changelog/changelog_summary.md),
  which links each stage of that story from `changelog/`.
- **Birth-year derivation with conflicting cross-census ages**
  (`AGE_REGRESSION_ANALYSIS.md` in this folder) — decided and implemented:
  primary birth Event takes priority over census-age backfill. Verified
  against current code (`src/review/findings.py::_derive_birth_year()`)
  during the onboarding pass that created this archive, September 2026.
  The file's own header still says "OPEN" — that's stale, ignore it; the
  "Solution (Decided 2026-06-28)" section further down is what happened.
- **Audit logging gaps** (`AUDIT_LOGGING_GAPS.md`) — described steps 2–5 of
  the conclusion pipeline missing audit logs. Also resolved: all conclusion
  modules now import and use `AuditLog`.

## Why this exists as an archive rather than being deleted

A handful of files here are pure intermediate steps in an investigate →
correct → re-investigate chain and were deleted outright rather than
archived (e.g. an early "root cause" doc that a later "corrected analysis"
doc fully superseded, or a threshold test result later found to be based on
a buggy measurement script). What's kept here still has some documentary
value — showing the actual investigative path, including some conclusions
that were later revised — without cluttering `analysis/` or `docs/` for
someone trying to understand the current system.
