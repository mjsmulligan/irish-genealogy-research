"""
GRA — Genealogy Research Assistant
Review layer: report runner.

Assembles findings into a Report, assigns priorities, and writes paired
output files (JSON + Markdown) to the reports/ directory.

Entry point
-----------
    from src.review.runner import run_review
    report = run_review(conn)

CLI usage (via src.cli):
    python -m src.cli review
"""

from __future__ import annotations

import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import psycopg2.extensions

from src.review.findings import run_all_findings
from src.review.priority import assign_priorities
from src.review.report import Report, ReportItem

# Output directory — relative to project root (working directory at runtime)
_REPORTS_DIR = Path("reports")


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def _build_summary(items: list[ReportItem]) -> dict[str, int]:
    """Count items by finding_type."""
    c: Counter[str] = Counter(item.finding_type for item in items)
    return dict(sorted(c.items()))


def run_review(conn: psycopg2.extensions.connection) -> Report:
    """
    Run all v1.0 finding functions, assign priorities, and return the assembled Report.
    Does not write any files — call write_report() for file output.
    """
    print("  [review] Running findings...")
    items = run_all_findings(conn)

    print(f"  [review] {len(items)} raw finding(s) found. Assigning priorities...")
    items = assign_priorities(conn, items)

    summary = _build_summary(items)

    return Report(
        generated_at=datetime.now(tz=timezone.utc),
        items=items,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# File output
# ---------------------------------------------------------------------------

def write_report(report: Report, reports_dir: Path = _REPORTS_DIR) -> tuple[Path, Path]:
    """
    Write paired JSON and Markdown files to reports_dir.

    Returns (json_path, md_path) of the written files.
    The reports_dir is created if it does not exist.
    """
    reports_dir.mkdir(parents=True, exist_ok=True)

    ts = report.generated_at.strftime("%Y%m%d_%H%M%S")
    json_path = reports_dir / f"report_{ts}.json"
    md_path   = reports_dir / f"report_{ts}.md"

    json_path.write_text(report.to_json(), encoding="utf-8")
    md_path.write_text(report.to_markdown(), encoding="utf-8")

    return json_path, md_path


# ---------------------------------------------------------------------------
# CLI helper (called by src.cli._cmd_review)
# ---------------------------------------------------------------------------

def run_and_print(conn: psycopg2.extensions.connection) -> None:
    """
    Run the review, write output files, and print a summary to stdout.
    Intended for use by the 'review' CLI subcommand.
    """
    print("\nRunning research review...")
    report = run_review(conn)
    json_path, md_path = write_report(report)

    print()
    print("=" * 60)
    print("  GRA — Research Report")
    print("=" * 60)
    print()

    if not report.items:
        print("  No findings — database passes all v1.0 review checks.")
    else:
        print("  SUMMARY")
        for ftype, count in sorted(report.summary.items()):
            print(f"    {ftype:<40} {count:>4}")
        print(f"    {'Total':<40} {len(report.items):>4}")
        print()
        print(f"  TOP FINDINGS (priority 1–{min(10, len(report.items))})")
        for item in report.items[:10]:
            anchor = f"Person {item.person_id}" if item.person_id else "–"
            print(f"    [{item.priority:>3}] [{item.finding_type}] {anchor}")
            print(f"           {item.title[:72]}")

    print()
    print(f"  JSON: {json_path}")
    print(f"  MD:   {md_path}")
    print()
    print("=" * 60)
    print()
