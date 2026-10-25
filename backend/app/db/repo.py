"""Repository functions for TraceBridge SQLite database."""

from datetime import datetime, timezone
import json
import sqlite3
from typing import Any


def insert_analysis_bundle(
    conn: sqlite3.Connection,
    analysis: dict[str, Any],
    datasets: list[dict[str, Any]],
    findings: list[dict[str, Any]],
) -> None:
    """Insert an entire analysis run (analysis, datasets, findings, and initial reviews) atomically."""
    with conn:
        conn.execute(
            """
            INSERT INTO analyses (
                id, created_at, versions_json, ruleset_sha256, input_fingerprint,
                findings_digest, records_processed, finding_count, gate,
                quality_score, score_json, coverage_json, evaluations_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                analysis["id"],
                analysis["created_at"],
                json.dumps(analysis["versions"]),
                analysis["ruleset_sha256"],
                analysis["input_fingerprint"],
                analysis["findings_digest"],
                analysis["records_processed"],
                analysis["finding_count"],
                analysis["gate"],
                analysis["quality_score"],
                json.dumps(analysis["score_breakdown"]),
                json.dumps(analysis["coverage"]),
                json.dumps(analysis.get("evaluations", [])),
            ),
        )

        for ds in datasets:
            conn.execute(
                """
                INSERT INTO datasets (
                    analysis_id, kind, original_filename, stored_path,
                    size_bytes, sha256, row_count, ignored_columns_json, trim_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    analysis["id"],
                    ds["kind"],
                    ds["original_filename"],
                    str(ds["stored_path"]),
                    ds["size_bytes"],
                    ds["sha256"],
                    ds["row_count"],
                    json.dumps(ds.get("ignored_columns", [])),
                    ds.get("trim_count", 0),
                ),
            )

        now_iso = datetime.now(timezone.utc).isoformat()
        for f in findings:
            conn.execute(
                """
                INSERT INTO findings (
                    id, analysis_id, rule_id, variant, severity,
                    finding_class, entity_key, description, expected,
                    actual, source_refs_json, truncated
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    f["id"],
                    analysis["id"],
                    f["rule_id"],
                    f.get("variant"),
                    f["severity"],
                    f["finding_class"],
                    f["entity_key"],
                    f["description"],
                    f.get("expected"),
                    f.get("actual"),
                    json.dumps(f.get("source_refs", [])),
                    1 if f.get("truncated") else 0,
                ),
            )
            # Create corresponding review row in separate table
            conn.execute(
                """
                INSERT INTO finding_reviews (
                    finding_id, review_status, reviewer_note, updated_at
                ) VALUES (?, ?, ?, ?);
                """,
                (
                    f["id"],
                    "unreviewed",
                    "",
                    now_iso,
                ),
            )


def get_analysis(conn: sqlite3.Connection, analysis_id: str) -> dict[str, Any] | None:
    """Retrieve analysis record by ID."""
    row = conn.execute(
        "SELECT * FROM analyses WHERE id = ?;", (analysis_id,)
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["versions"] = json.loads(d.pop("versions_json"))
    d["score_breakdown"] = json.loads(d.pop("score_json"))
    d["coverage"] = json.loads(d.pop("coverage_json"))
    d["evaluations"] = json.loads(d.pop("evaluations_json"))
    return d


def list_analyses(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Retrieve list of all analyses ordered by created_at DESC."""
    rows = conn.execute(
        "SELECT * FROM analyses ORDER BY created_at DESC;"
    ).fetchall()
    results = []
    for row in rows:
        d = dict(row)
        d["versions"] = json.loads(d.pop("versions_json"))
        d["score_breakdown"] = json.loads(d.pop("score_json"))
        d["coverage"] = json.loads(d.pop("coverage_json"))
        d["evaluations"] = json.loads(d.pop("evaluations_json"))
        results.append(d)
    return results


def get_datasets(conn: sqlite3.Connection, analysis_id: str) -> list[dict[str, Any]]:
    """Retrieve all datasets for an analysis."""
    rows = conn.execute(
        "SELECT * FROM datasets WHERE analysis_id = ? ORDER BY kind ASC;",
        (analysis_id,),
    ).fetchall()
    results = []
    for row in rows:
        d = dict(row)
        d["ignored_columns"] = json.loads(d.pop("ignored_columns_json"))
        results.append(d)
    return results


def get_dataset_by_kind(
    conn: sqlite3.Connection, analysis_id: str, kind: str
) -> dict[str, Any] | None:
    """Retrieve specific dataset by kind for an analysis."""
    row = conn.execute(
        "SELECT * FROM datasets WHERE analysis_id = ? AND kind = ?;",
        (analysis_id, kind),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["ignored_columns"] = json.loads(d.pop("ignored_columns_json"))
    return d


def get_findings(
    conn: sqlite3.Connection,
    analysis_id: str,
    severity: str | None = None,
    rule_id: str | None = None,
    finding_class: str | None = None,
    review_status: str | None = None,
) -> list[dict[str, Any]]:
    """Retrieve findings for an analysis with optional filters and review data."""
    query = """
        SELECT f.*, r.review_status, r.reviewer_note, r.updated_at AS review_updated_at
        FROM findings f
        LEFT JOIN finding_reviews r ON f.id = r.finding_id
        WHERE f.analysis_id = ?
    """
    params: list[Any] = [analysis_id]

    if severity:
        query += " AND LOWER(f.severity) = LOWER(?)"
        params.append(severity)
    if rule_id:
        query += " AND f.rule_id = ?"
        params.append(rule_id)
    if finding_class:
        query += " AND f.finding_class = ?"
        params.append(finding_class)
    if review_status:
        query += " AND r.review_status = ?"
        params.append(review_status)

    query += " ORDER BY f.id ASC;"

    rows = conn.execute(query, params).fetchall()
    results = []
    for row in rows:
        d = dict(row)
        d["source_refs"] = json.loads(d.pop("source_refs_json"))
        d["truncated"] = bool(d["truncated"])
        results.append(d)
    return results


def update_finding_review(
    conn: sqlite3.Connection,
    finding_id: str,
    review_status: str,
    reviewer_note: str,
) -> dict[str, Any] | None:
    """Update finding review status and note in the finding_reviews table only.

    The findings table is immutable and remains completely untouched.
    """
    # Check if finding exists
    finding_row = conn.execute(
        "SELECT id FROM findings WHERE id = ?;", (finding_id,)
    ).fetchone()
    if not finding_row:
        return None

    now_iso = datetime.now(timezone.utc).isoformat()
    with conn:
        conn.execute(
            """
            INSERT INTO finding_reviews (finding_id, review_status, reviewer_note, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(finding_id) DO UPDATE SET
                review_status = excluded.review_status,
                reviewer_note = excluded.reviewer_note,
                updated_at = excluded.updated_at;
            """,
            (finding_id, review_status, reviewer_note, now_iso),
        )

    row = conn.execute(
        "SELECT * FROM finding_reviews WHERE finding_id = ?;", (finding_id,)
    ).fetchone()
    return dict(row) if row else None


def insert_export(
    conn: sqlite3.Connection,
    analysis_id: str,
    export_format: str,
    sha256: str,
    byte_size: int,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Record an export in the exports table."""
    if created_at is None:
        created_at = datetime.now(timezone.utc).isoformat()

    with conn:
        cur = conn.execute(
            """
            INSERT INTO exports (analysis_id, format, sha256, byte_size, created_at)
            VALUES (?, ?, ?, ?, ?);
            """,
            (analysis_id, export_format, sha256, byte_size, created_at),
        )
        export_id = cur.lastrowid

    row = conn.execute("SELECT * FROM exports WHERE id = ?;", (export_id,)).fetchone()
    return dict(row) if row else {}


def get_exports(conn: sqlite3.Connection, analysis_id: str) -> list[dict[str, Any]]:
    """Retrieve all recorded exports for an analysis."""
    rows = conn.execute(
        "SELECT * FROM exports WHERE analysis_id = ? ORDER BY created_at DESC;",
        (analysis_id,),
    ).fetchall()
    return [dict(r) for r in rows]
