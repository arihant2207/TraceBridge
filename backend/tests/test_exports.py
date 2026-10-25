"""Tests for export generation, formatting, and persistence (Milestone M5)."""

import csv
import hashlib
import io
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.db.database import get_db_connection, init_db
from app.main import app
from app.reporting.exports import export_csv, export_json, export_markdown


@pytest.fixture(autouse=True)
def isolate_test_environment(tmp_path, monkeypatch):
    """Ensure tests run with an isolated temporary SQLite DB and upload directory."""
    test_db = tmp_path / "test.db"
    test_uploads = tmp_path / "uploads"
    test_uploads.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("TRACEBRIDGE_DB_PATH", str(test_db))
    monkeypatch.setenv("TRACEBRIDGE_UPLOAD_DIR", str(test_uploads))

    init_db(test_db)
    yield


@pytest.fixture
def client():
    return TestClient(app)


# =============================================================================
# 1. Export Parity & Formatting Tests (Sample = Fault)
# =============================================================================
def test_export_parity_and_content_fault(client):
    """Verify export parity across MD, CSV, and JSON for fault dataset (14 findings).

    Checks:
    - Markdown has every finding ID.
    - Markdown places quality score beside the gate.
    - Markdown contains UNRESOLVED section listing both required engineering questions.
    - CSV row count equals finding count (14 findings).
    - JSON findings equal the API response from /analyses/{id}/findings.
    - Database exports table records format, SHA-256, and byte size.
    """
    # Create analysis with fault sample
    resp = client.post("/api/v1/analyses?sample=fault")
    assert resp.status_code == 201
    analysis_data = resp.json()
    analysis_id = analysis_data["id"]

    # Retrieve findings via API
    api_findings = client.get(f"/api/v1/analyses/{analysis_id}/findings").json()
    assert len(api_findings) == 14
    finding_ids = [f["id"] for f in api_findings]

    # --- A. Markdown Export ---
    md_resp = client.get(f"/api/v1/analyses/{analysis_id}/export?format=md")
    assert md_resp.status_code == 200
    assert "text/markdown" in md_resp.headers["content-type"]
    assert f'filename="tracebridge_report_{analysis_id}.md"' in md_resp.headers["content-disposition"]
    md_content = md_resp.text

    # 1. Score beside the gate
    assert "73.3" in md_content
    assert "BLOCKED_CRITICAL" in md_content
    assert "**Quality Score:** 73.3 / 100.0 | **Gate Status:** BLOCKED_CRITICAL" in md_content

    # 2. Every finding ID present in Markdown
    for fid in finding_ids:
        assert fid in md_content, f"Finding {fid} missing from Markdown export"

    # 3. UNRESOLVED section listing required questions
    assert "## UNRESOLVED" in md_content
    assert "recorded under the required ambient conditions?" in md_content
    assert "does the test actually verify the requirement?" in md_content

    # --- B. CSV Export ---
    csv_resp = client.get(f"/api/v1/analyses/{analysis_id}/export?format=csv")
    assert csv_resp.status_code == 200
    assert "text/csv" in csv_resp.headers["content-type"]
    assert f'filename="tracebridge_findings_{analysis_id}.csv"' in csv_resp.headers["content-disposition"]
    csv_content = csv_resp.text

    # Parse CSV and verify row count
    reader = list(csv.reader(io.StringIO(csv_content)))
    header = reader[0]
    data_rows = reader[1:]
    assert "finding_id" in header
    assert len(data_rows) == 14, f"Expected 14 CSV rows, got {len(data_rows)}"

    csv_finding_ids = [row[0] for row in data_rows]
    assert csv_finding_ids == finding_ids

    # --- C. JSON Export ---
    json_resp = client.get(f"/api/v1/analyses/{analysis_id}/export?format=json")
    assert json_resp.status_code == 200
    assert "application/json" in json_resp.headers["content-type"]
    assert f'filename="tracebridge_report_{analysis_id}.json"' in json_resp.headers["content-disposition"]
    json_export = json_resp.json()

    assert "analysis" in json_export
    assert "datasets" in json_export
    assert "findings" in json_export
    assert json_export["findings"] == api_findings

    # --- D. Database Persistence in exports table ---
    conn = get_db_connection()
    export_rows = conn.execute(
        "SELECT format, sha256, byte_size FROM exports WHERE analysis_id = ? ORDER BY format;",
        (analysis_id,),
    ).fetchall()
    conn.close()

    assert len(export_rows) == 3
    exports_by_format = {row["format"]: row for row in export_rows}

    # Verify Markdown export record
    md_record = exports_by_format["md"]
    md_bytes = md_content.encode("utf-8")
    assert md_record["byte_size"] == len(md_bytes)
    assert md_record["sha256"] == hashlib.sha256(md_bytes).hexdigest()

    # Verify CSV export record
    csv_record = exports_by_format["csv"]
    csv_bytes = csv_content.encode("utf-8")
    assert csv_record["byte_size"] == len(csv_bytes)
    assert csv_record["sha256"] == hashlib.sha256(csv_bytes).hexdigest()

    # Verify JSON export record
    json_record = exports_by_format["json"]
    json_bytes = json_resp.text.encode("utf-8")
    assert json_record["byte_size"] == len(json_bytes)
    assert json_record["sha256"] == hashlib.sha256(json_bytes).hexdigest()


# =============================================================================
# 2. Export Parity (Sample = Clean)
# =============================================================================
def test_export_parity_clean(client):
    """Verify export parity for clean sample (1 finding, score 100.0, gate NOT_BLOCKED)."""
    resp = client.post("/api/v1/analyses?sample=clean")
    assert resp.status_code == 201
    analysis_id = resp.json()["id"]

    api_findings = client.get(f"/api/v1/analyses/{analysis_id}/findings").json()
    assert len(api_findings) == 1
    fid = api_findings[0]["id"]

    # Markdown
    md_resp = client.get(f"/api/v1/analyses/{analysis_id}/export?format=md")
    assert md_resp.status_code == 200
    assert "**Quality Score:** 100.0 / 100.0 | **Gate Status:** NOT_BLOCKED" in md_resp.text
    assert fid in md_resp.text
    assert "recorded under the required ambient conditions?" in md_resp.text
    assert "does the test actually verify the requirement?" in md_resp.text

    # CSV
    csv_resp = client.get(f"/api/v1/analyses/{analysis_id}/export?format=csv")
    assert csv_resp.status_code == 200
    reader = list(csv.reader(io.StringIO(csv_resp.text)))
    assert len(reader) == 2  # 1 header + 1 finding
    assert reader[1][0] == fid

    # JSON
    json_resp = client.get(f"/api/v1/analyses/{analysis_id}/export?format=json")
    assert json_resp.status_code == 200
    assert json_resp.json()["findings"] == api_findings


# =============================================================================
# 3. Pure Functions Export Tests
# =============================================================================
def test_pure_export_functions():
    """Verify pure export functions operate directly on analysis state without side effects."""
    mock_analysis = {
        "id": "ANL-TEST-001",
        "created_at": "2026-10-25T12:00:00+00:00",
        "quality_score": "95.5",
        "gate": "NOT_BLOCKED",
        "finding_count": 1,
        "records_processed": 10,
        "findings_digest": "abcdef1234567890",
        "input_fingerprint": "1234567890abcdef",
        "coverage": {"REQ-001": "SATISFIED"},
    }
    mock_datasets = [
        {
            "kind": "requirements",
            "original_filename": "req.csv",
            "row_count": 1,
            "size_bytes": 100,
            "sha256": "aaaa1111",
        }
    ]
    mock_findings = [
        {
            "id": "ANL-TEST-001-F0001",
            "rule_id": "R09",
            "variant": None,
            "severity": "low",
            "finding_class": "OBSERVATION",
            "entity_key": "TST-001",
            "description": "Boundary reading",
            "expected": "<= 80",
            "actual": "80",
            "review_status": "unreviewed",
            "reviewer_note": "",
        }
    ]

    # Markdown
    md = export_markdown(mock_analysis, mock_findings, mock_datasets)
    assert "ANL-TEST-001" in md
    assert "**Quality Score:** 95.5 / 100.0 | **Gate Status:** NOT_BLOCKED" in md
    assert "ANL-TEST-001-F0001" in md
    assert "recorded under the required ambient conditions?" in md
    assert "does the test actually verify the requirement?" in md

    # CSV
    csv_out = export_csv(mock_findings)
    assert "ANL-TEST-001-F0001" in csv_out
    lines = [line for line in csv_out.splitlines() if line.strip()]
    assert len(lines) == 2

    # JSON
    json_out = export_json(mock_analysis, mock_findings, mock_datasets)
    parsed = json.loads(json_out)
    assert parsed["analysis"]["id"] == "ANL-TEST-001"
    assert len(parsed["findings"]) == 1
    assert parsed["findings"][0]["id"] == "ANL-TEST-001-F0001"
