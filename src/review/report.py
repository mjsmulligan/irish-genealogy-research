"""
GRA — Genealogy Research Assistant
Review layer: ReportItem and Report dataclasses.

These are the output structures produced by the review runner and consumed by
the Markdown/JSON serialisers.  Nothing in this module touches the database.

Data structures
---------------
ReportItem  — a single finding surfaced by one findings function
Report      — the assembled set of items for one run, with metadata
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime


# ---------------------------------------------------------------------------
# ReportItem
# ---------------------------------------------------------------------------

@dataclass
class ReportItem:
    """A single researcher-facing finding."""

    # Controlled vocabulary: one of the finding_type values defined in ROADMAP §5.9.
    # Naming convention: <category>_<specificity> (snake_case).
    finding_type: str

    # 1 = highest priority.  Assigned by priority.py at assembly time.
    priority: int

    # Conclusion-layer FKs.  At least one of person_id, relationship_id, event_id
    # must be non-None; a finding always anchors to at least one conclusion object.
    person_id: int | None
    relationship_id: int | None
    event_id: int | None

    # Evidence Records underpinning this finding.  May be empty for findings
    # derived purely from the conclusion layer (e.g. birth_singularity_violation).
    record_ids: list[int]

    # Human-readable content.
    title: str       # one-line summary suitable for Markdown heading
    detail: str      # full explanation; must include actual DB values so the
                     # researcher can evaluate without additional queries

    # Optional: what the researcher should do.  May be None when the recommended
    # action is obvious from the finding_type (e.g. merge_error_candidate).
    recommended_action: str | None

    def to_dict(self) -> dict:
        """Serialise to a plain dict for JSON output."""
        return {
            "finding_type":       self.finding_type,
            "priority":           self.priority,
            "person_id":          self.person_id,
            "relationship_id":    self.relationship_id,
            "event_id":           self.event_id,
            "record_ids":         self.record_ids,
            "title":              self.title,
            "detail":             self.detail,
            "recommended_action": self.recommended_action,
        }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

@dataclass
class Report:
    """The assembled findings for one review run."""

    generated_at: datetime

    # Items sorted by priority ascending (1 = highest) at assembly time.
    items: list[ReportItem] = field(default_factory=list)

    # Count of items per finding_type, for the summary section.
    summary: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialise to a plain dict for JSON output."""
        return {
            "generated_at": self.generated_at.isoformat(),
            "total_findings": len(self.items),
            "summary": self.summary,
            "items": [item.to_dict() for item in self.items],
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialise the full report to a JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def to_markdown(self) -> str:
        """Render the report as a human-readable Markdown string."""
        lines: list[str] = []
        ts = self.generated_at.strftime("%d %B %Y %H:%M")
        lines.append(f"# GRA Research Report — {ts}")
        lines.append("")
        lines.append("## Summary")
        lines.append("")
        if not self.items:
            lines.append("No findings — database passes all v1.0 review checks.")
        else:
            for ftype, count in sorted(self.summary.items()):
                lines.append(f"- **{ftype}**: {count}")
            lines.append(f"- **Total**: {len(self.items)}")
        lines.append("")
        lines.append("## Findings")
        lines.append("")

        for i, item in enumerate(self.items, start=1):
            ftype_display = item.finding_type.upper()
            anchor_parts = []
            if item.person_id is not None:
                anchor_parts.append(f"Person {item.person_id}")
            if item.relationship_id is not None:
                anchor_parts.append(f"Relationship {item.relationship_id}")
            if item.event_id is not None:
                anchor_parts.append(f"Event {item.event_id}")
            anchor = " / ".join(anchor_parts) if anchor_parts else "–"

            lines.append(f"### {i}. [{ftype_display}] {anchor}")
            lines.append("")
            lines.append(f"**Priority:** {item.priority}")
            lines.append("")
            lines.append(f"**{item.title}**")
            lines.append("")
            lines.append(item.detail)
            if item.record_ids:
                ids_str = ", ".join(str(r) for r in item.record_ids)
                lines.append("")
                lines.append(f"*Evidence records: {ids_str}*")
            if item.recommended_action:
                lines.append("")
                lines.append(f"*Recommended action: {item.recommended_action}*")
            lines.append("")

        return "\n".join(lines)
