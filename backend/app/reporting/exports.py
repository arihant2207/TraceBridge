"""Pure export formatting functions for TraceBridge analysis reports."""

import csv
import io
import json
from typing import Any


def export_markdown(
    analysis: dict[str, Any],
    findings: list[dict[str, Any]],
    datasets: list[dict[str, Any]],
) -> str:
    """Generate Markdown report per SPEC sections 9 and 11.

    Requirements:
    - Score beside the gate.
    - Every finding ID present.
    - UNRESOLVED section listing:
      - "recorded under the required ambient conditions?"
      - "does the test actually verify the requirement?"
    """
    lines: list[str] = []
    lines.append(f"# TraceBridge Validation Report: {analysis['id']}")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append("")
    # Score beside the gate
    lines.append(
        f"**Quality Score:** {analysis['quality_score']} / 100.0 | "
        f"**Gate Status:** {analysis['gate']}"
    )
    lines.append("")
    lines.append(f"- **Analysis ID:** `{analysis['id']}`")
    lines.append(f"- **Created At:** {analysis['created_at']}")
    lines.append(f"- **Records Processed:** {analysis['records_processed']}")
    lines.append(f"- **Total Findings:** {analysis['finding_count']}")
    lines.append(f"- **Findings Digest:** `{analysis['findings_digest']}`")
    lines.append(f"- **Input Fingerprint:** `{analysis['input_fingerprint']}`")
    lines.append("")

    lines.append("## Datasets")
    lines.append("")
    lines.append("| Kind | Original Filename | Rows | Size (bytes) | SHA-256 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for ds in datasets:
        lines.append(
            f"| {ds['kind']} | {ds['original_filename']} | {ds['row_count']} | "
            f"{ds['size_bytes']} | `{ds['sha256']}` |"
        )
    lines.append("")

    lines.append("## Requirement Coverage")
    lines.append("")
    lines.append("| Requirement ID | Coverage Status |")
    lines.append("| --- | --- |")
    for req_id, status in sorted(analysis.get("coverage", {}).items()):
        lines.append(f"| {req_id} | {status} |")
    lines.append("")

    lines.append("## Findings")
    lines.append("")
    if not findings:
        lines.append("No findings recorded.")
    else:
        lines.append(
            "| Finding ID | Rule | Severity | Class | Entity Key | Description | Review Status |"
        )
        lines.append(
            "| --- | --- | --- | --- | --- | --- | --- |"
        )
        for f in findings:
            fid = f.get("id", "")
            rule = f.get("rule_id", "")
            if f.get("variant"):
                rule += f" ({f['variant']})"
            sev = f.get("severity", "")
            cls = f.get("finding_class", "")
            key = f.get("entity_key", "")
            desc = f.get("description", "").replace("|", "\\|")
            review = f.get("review_status", "unreviewed")
            lines.append(f"| {fid} | {rule} | {sev} | {cls} | {key} | {desc} | {review} |")
    lines.append("")

    # UNRESOLVED section per SPEC Locked Decision U1 and limitation section 12
    lines.append("## UNRESOLVED")
    lines.append("")
    lines.append(
        "The following engineering verification questions cannot be established from "
        "this schema and are reported as UNRESOLVED:"
    )
    lines.append("1. recorded under the required ambient conditions?")
    lines.append("2. does the test actually verify the requirement?")
    lines.append("")

    return "\n".join(lines)


def export_json(
    analysis: dict[str, Any],
    findings: list[dict[str, Any]],
    datasets: list[dict[str, Any]],
) -> str:
    """Generate JSON export containing full analysis state."""
    export_obj = {
        "analysis": analysis,
        "datasets": datasets,
        "findings": findings,
    }
    return json.dumps(export_obj, indent=2)


def export_csv(findings: list[dict[str, Any]]) -> str:
    """Generate CSV export listing every finding ID.

    CSV row count (excluding header) equals the finding count.
    """
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        [
            "finding_id",
            "rule_id",
            "variant",
            "severity",
            "finding_class",
            "entity_key",
            "description",
            "expected",
            "actual",
            "review_status",
            "reviewer_note",
        ]
    )

    for f in findings:
        writer.writerow(
            [
                f.get("id", ""),
                f.get("rule_id", ""),
                f.get("variant") or "",
                f.get("severity", ""),
                f.get("finding_class", ""),
                f.get("entity_key", ""),
                f.get("description", ""),
                f.get("expected") or "",
                f.get("actual") or "",
                f.get("review_status", "unreviewed"),
                f.get("reviewer_note", ""),
            ]
        )

    return output.getvalue()
