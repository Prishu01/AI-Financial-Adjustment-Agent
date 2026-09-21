"""
Required-fields validator.

Checks that every journal entry supplies:
  id, description, date, source, lines (non-empty list).

This is purely deterministic — no LLM involved.
"""

from __future__ import annotations

import re
from typing import Any

from app.models.schemas import IssueSeverity, ValidationIssue

# ISO-8601 date: YYYY-MM-DD
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_required_fields(raw: dict[str, Any]) -> list[ValidationIssue]:
    """
    Validate required top-level fields on a raw journal entry dict.

    Returns a (possibly empty) list of ValidationIssue objects.
    Never raises — malformed input produces issues, not exceptions.
    """
    issues: list[ValidationIssue] = []
    entry_id = str(raw.get("id", "")).strip() or "<missing-id>"

    # ── id ──────────────────────────────────────────────────────────
    if not raw.get("id") or not str(raw["id"]).strip():
        issues.append(ValidationIssue(
            severity=IssueSeverity.ERROR,
            validator="FieldValidator",
            message="Missing required field: 'id'.",
        ))

    # ── description ─────────────────────────────────────────────────
    if not raw.get("description") or not str(raw["description"]).strip():
        issues.append(ValidationIssue(
            severity=IssueSeverity.ERROR,
            validator="FieldValidator",
            message=f"[{entry_id}] Missing required field: 'description'.",
        ))

    # ── date ────────────────────────────────────────────────────────
    date_val = raw.get("date")
    if not date_val or not str(date_val).strip():
        issues.append(ValidationIssue(
            severity=IssueSeverity.ERROR,
            validator="FieldValidator",
            message=f"[{entry_id}] Missing required field: 'date'.",
        ))
    elif not _DATE_RE.match(str(date_val).strip()):
        issues.append(ValidationIssue(
            severity=IssueSeverity.ERROR,
            validator="FieldValidator",
            message=(
                f"[{entry_id}] Field 'date' is not a valid ISO-8601 date "
                f"(expected YYYY-MM-DD, got '{date_val}')."
            ),
        ))

    # ── source ──────────────────────────────────────────────────────
    if not raw.get("source") or not str(raw["source"]).strip():
        issues.append(ValidationIssue(
            severity=IssueSeverity.ERROR,
            validator="FieldValidator",
            message=f"[{entry_id}] Missing required field: 'source'.",
        ))

    # ── lines ───────────────────────────────────────────────────────
    lines = raw.get("lines")
    if lines is None:
        issues.append(ValidationIssue(
            severity=IssueSeverity.ERROR,
            validator="FieldValidator",
            message=f"[{entry_id}] Missing required field: 'lines'.",
        ))
    elif not isinstance(lines, list) or len(lines) == 0:
        issues.append(ValidationIssue(
            severity=IssueSeverity.ERROR,
            validator="FieldValidator",
            message=f"[{entry_id}] 'lines' must be a non-empty list.",
        ))
    else:
        # At least 2 lines needed for a double-entry
        if len(lines) < 2:
            issues.append(ValidationIssue(
                severity=IssueSeverity.ERROR,
                validator="FieldValidator",
                message=(
                    f"[{entry_id}] A journal entry requires at least 2 lines "
                    f"(found {len(lines)})."
                ),
            ))

    return issues
