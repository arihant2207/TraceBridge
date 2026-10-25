"""Tests for API endpoints under /api/v1 (Milestone M5)."""

import io
import json
from pathlib import Path
import zipfile

from fastapi.testclient import TestClient
import pytest

from app.db.database import get_db_connection, init_db
from app.main import app

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"
CLEAN_DIR = SAMPLES_DIR / "clean"
FAULT_DIR = SAMPLES_DIR / "fault"


@pytest.fixture(autouse=True)
def isolate_test_environment(tmp_path, monkeypatch):
    """Ensure every test runs with an isolated temporary SQLite DB and upload directory."""
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


def assert_schema_error(resp, allowed_codes):
    """422 with the standard error envelope, naming at least one allowed SCH code.

    The code may be in error.code or inside error.details, so the whole error
    body is searched. This keeps the test independent of the details layout.
    """
    assert resp.status_code == 422
    body = resp.json()
    assert "error" in body
    assert "code" in body["error"]
    assert "message" in body["error"]
    assert isinstance(body["error"]["details"], list)
    text = json.dumps(body["error"], ensure_ascii=False)
    assert any(code in text for code in allowed_codes), (
        f"expected one of {allowed_codes} in error body, got: {text}"
    )


def assert_no_analysis_left(tmp_path):
    """No analysis row in the DB and no analysis folder under uploads."""
    conn = get_db_connection()
    count = conn.execute("SELECT COUNT(*) FROM analyses;").fetchone()[0]
    conn.close()
    assert count == 0
    upload_dir = tmp_path / "uploads"
    if upload_dir.exists():
        assert len(list(upload_dir.iterdir())) == 0


# =============================================================================
# 1. POST /analyses & GET /analyses (Clean & Fault Samples)
# =============================================================================
def test_post_analysis_clean_sample(client):
    """POST /analyses?sample=clean returns 1 finding, score 100.0, gate NOT_BLOCKED."""
    resp = client.post("/api/v1/analyses?sample=clean")
    assert resp.status_code == 201
    data = resp.json()

    assert data["quality_score"] == "100.0"
    assert data["gate"] == "NOT_BLOCKED"
    assert data["finding_count"] == 1
    assert data["records_processed"] == 15
    analysis_id = data["id"]

    # GET /analyses lists the created analysis
    list_resp = client.get("/api/v1/analyses")
    assert list_resp.status_code == 200
    analyses = list_resp.json()
    assert any(a["id"] == analysis_id for a in analyses)

    # GET /analyses/{id} returns detail
    get_resp = client.get(f"/api/v1/analyses/{analysis_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == analysis_id

    # GET /analyses/{id}/findings returns exactly R09 on TST-002
    findings_resp = client.get(f"/api/v1/analyses/{analysis_id}/findings")
    assert findings_resp.status_code == 200
    findings = findings_resp.json()
    assert len(findings) == 1
    assert findings[0]["rule_id"] == "R09"
    assert findings[0]["entity_key"] == "TST-002"

    # GET /analyses/{id}/coverage returns clean coverage with per-test outcomes
    cov_resp = client.get(f"/api/v1/analyses/{analysis_id}/coverage")
    assert cov_resp.status_code == 200
    cov = cov_resp.json()
    assert cov["REQ-THM-011"]["status"] == "SATISFIED"
    assert cov["REQ-THM-011"]["test_outcomes"] == [
        {"test_id": "TST-001", "outcome": "SATISFIED", "blocked_by": []}
    ]
    assert cov["REQ-ELC-004"]["status"] == "VIOLATED"
    assert cov["REQ-ELC-004"]["test_outcomes"] == [
        {"test_id": "TST-002", "outcome": "VIOLATED", "blocked_by": []}
    ]
    assert cov["REQ-PWR-002"]["status"] == "SATISFIED"
    assert cov["REQ-PWR-002"]["test_outcomes"] == [
        {"test_id": "TST-003", "outcome": "SATISFIED", "blocked_by": []}
    ]


def test_coverage_endpoint_per_test_outcomes_fault(client):
    """GET /analyses/{id}/coverage returns per-test outcomes with findings for fault sample."""
    resp = client.post("/api/v1/analyses", data={"sample": "fault"})
    assert resp.status_code == 201
    analysis_id = resp.json()["id"]

    cov_resp = client.get(f"/api/v1/analyses/{analysis_id}/coverage")
    assert cov_resp.status_code == 200
    cov = cov_resp.json()

    # Status assertions per expected_fault.json and SPEC U13
    assert cov["REQ-THM-011"]["status"] == "CONTRADICTORY"
    assert cov["REQ-PWR-002"]["status"] == "CONTRADICTORY"
    assert cov["REQ-ELC-004"]["status"] == "INCONCLUSIVE"
    assert cov["REQ-THM-015"]["status"] == "NOT_EXECUTED"
    assert "REQ-PWR-009" in cov
    assert cov["REQ-PWR-009"]["status"] == "NOT_COVERED"
    assert cov["REQ-PWR-009"]["test_outcomes"] == []

    # REQ-THM-011 has TST-001 VIOLATED
    assert any(
        t["test_id"] == "TST-001" and t["outcome"] == "VIOLATED"
        for t in cov["REQ-THM-011"]["test_outcomes"]
    )

    # REQ-ELC-004 has TST-002 INCONCLUSIVE with finding references
    tst_002 = next((t for t in cov["REQ-ELC-004"]["test_outcomes"] if t["test_id"] == "TST-002"), None)
    assert tst_002 is not None
    assert tst_002["outcome"] == "INCONCLUSIVE"
    assert len(tst_002["blocked_by"]) > 0

    # Every executed test under REQ-ELC-004 stops before S5 (SPEC section 5)
    for t in cov["REQ-ELC-004"]["test_outcomes"]:
        assert t["outcome"] == "INCONCLUSIVE"
        assert len(t["blocked_by"]) > 0

    # REQ-PWR-002: TST-005 is SATISFIED (Fail + satisfied = R10); TST-006 and
    # TST-007 stop earlier and are INCONCLUSIVE
    pwr = {t["test_id"]: t["outcome"] for t in cov["REQ-PWR-002"]["test_outcomes"]}
    assert pwr["TST-005"] == "SATISFIED"
    assert pwr["TST-006"] == "INCONCLUSIVE"
    assert pwr["TST-007"] == "INCONCLUSIVE"

    # REQ-THM-015 only has a Not Run test, which has no evaluation
    assert cov["REQ-THM-015"]["test_outcomes"] == []


def test_post_analysis_fault_sample(client):
    """POST /analyses?sample=fault returns 14 findings, 2 critical, gate BLOCKED_CRITICAL."""
    resp = client.post("/api/v1/analyses", data={"sample": "fault"})
    assert resp.status_code == 201
    data = resp.json()

    assert data["quality_score"] == "73.3"
    assert data["gate"] == "BLOCKED_CRITICAL"
    assert data["finding_count"] == 14
    assert data["records_processed"] == 35
    analysis_id = data["id"]

    # Filter findings by severity=critical -> exactly 2 findings
    crit_resp = client.get(f"/api/v1/analyses/{analysis_id}/findings?severity=critical")
    assert crit_resp.status_code == 200
    crit_findings = crit_resp.json()
    assert len(crit_findings) == 2
    assert {f["entity_key"] for f in crit_findings} == {"TST-001", "TST-005"}

    # Filter findings by rule_id=R01 -> exactly 1 finding (TST-006)
    r01_resp = client.get(f"/api/v1/analyses/{analysis_id}/findings?rule_id=R01")
    assert r01_resp.status_code == 200
    assert len(r01_resp.json()) == 1
    assert r01_resp.json()[0]["entity_key"] == "TST-006"

    # Filter findings by class=OBSERVATION -> exactly 1 finding (R09 on TST-001)
    obs_resp = client.get(f"/api/v1/analyses/{analysis_id}/findings?class=OBSERVATION")
    assert obs_resp.status_code == 200
    assert len(obs_resp.json()) == 1
    assert obs_resp.json()[0]["rule_id"] == "R09"


def test_post_analysis_multipart_upload(client):
    """POST /analyses with multipart file uploads succeeds."""
    files = {
        "requirements": ("req.csv", (CLEAN_DIR / "requirements.csv").read_bytes(), "text/csv"),
        "test_results": ("tests.csv", (CLEAN_DIR / "test_results.csv").read_bytes(), "text/csv"),
        "telemetry": ("tel.csv", (CLEAN_DIR / "telemetry.csv").read_bytes(), "text/csv"),
    }
    resp = client.post("/api/v1/analyses", files=files)
    assert resp.status_code == 201
    assert resp.json()["quality_score"] == "100.0"


# =============================================================================
# 2. Schema Rejection Cases (Return 422 and leave analyses table empty)
# =============================================================================
@pytest.mark.parametrize(
    "case_name,req_filename,req_content,test_content,tel_content,allowed_codes",
    [
        (
            "missing_column",
            "req.csv",
            b"signal_name,operator,threshold_value,unit\ntemp,<=,80,\xC2\xB0C\n",  # missing requirement_id (SCH-004)
            (CLEAN_DIR / "test_results.csv").read_bytes(),
            (CLEAN_DIR / "telemetry.csv").read_bytes(),
            ("SCH-004",),
        ),
        (
            "wrong_extension",
            "req.txt",  # wrong extension (SCH-001)
            (CLEAN_DIR / "requirements.csv").read_bytes(),
            (CLEAN_DIR / "test_results.csv").read_bytes(),
            (CLEAN_DIR / "telemetry.csv").read_bytes(),
            ("SCH-001",),
        ),
        (
            "non_csv_or_nul",
            "req.csv",
            b"requirement_id,signal_name,operator,threshold_value,unit\x00\n",  # NUL byte (SCH-001)
            (CLEAN_DIR / "test_results.csv").read_bytes(),
            (CLEAN_DIR / "telemetry.csv").read_bytes(),
            ("SCH-001",),
        ),
        (
            "empty_file",
            "req.csv",
            b"",  # empty file: no header at all, the exact code depends on the loader
            (CLEAN_DIR / "test_results.csv").read_bytes(),
            (CLEAN_DIR / "telemetry.csv").read_bytes(),
            ("SCH-003", "SCH-004", "SCH-006"),
        ),
        (
            "duplicate_columns",
            "req.csv",
            b"requirement_id,signal_name,signal_name,operator,threshold_value,unit\n",  # duplicate column (SCH-005)
            (CLEAN_DIR / "test_results.csv").read_bytes(),
            (CLEAN_DIR / "telemetry.csv").read_bytes(),
            ("SCH-005",),
        ),
        (
            "zero_data_rows",
            "req.csv",
            b"requirement_id,signal_name,operator,threshold_value,unit\n",  # 0 data rows (SCH-006)
            (CLEAN_DIR / "test_results.csv").read_bytes(),
            (CLEAN_DIR / "telemetry.csv").read_bytes(),
            ("SCH-006",),
        ),
        (
            "ragged_rows",
            "req.csv",
            b"requirement_id,signal_name,operator,threshold_value,unit\nREQ-01,temp,<=,80\n",  # 4 fields instead of 5 (SCH-007)
            (CLEAN_DIR / "test_results.csv").read_bytes(),
            (CLEAN_DIR / "telemetry.csv").read_bytes(),
            ("SCH-007",),
        ),
        (
            "non_utf8",
            "req.csv",
            b"\xFF\xFE\x00\x00invalid utf8",  # invalid UTF-8; also contains NUL bytes, so SCH-001 or SCH-003
            (CLEAN_DIR / "test_results.csv").read_bytes(),
            (CLEAN_DIR / "telemetry.csv").read_bytes(),
            ("SCH-001", "SCH-003"),
        ),
    ],
)
def test_schema_reject_cases_leave_db_and_uploads_empty(
    client, tmp_path, case_name, req_filename, req_content, test_content, tel_content, allowed_codes
):
    """Each schema-reject case returns 422 and leaves the analyses table and upload folder empty."""
    files = {
        "requirements": (req_filename, req_content, "text/csv"),
        "test_results": ("tests.csv", test_content, "text/csv"),
        "telemetry": ("tel.csv", tel_content, "text/csv"),
    }
    resp = client.post("/api/v1/analyses", files=files)
    assert_schema_error(resp, allowed_codes)
    assert_no_analysis_left(tmp_path)


def test_schema_reject_oversize_leaves_db_and_uploads_empty(client, tmp_path):
    """Oversize file (>5MB) returns 422 and leaves analyses table and upload folder empty (SCH-002)."""
    oversize_content = b"requirement_id,signal_name,operator,threshold_value,unit\n" + b"X" * (5 * 1024 * 1024 + 100)
    files = {
        "requirements": ("req.csv", oversize_content, "text/csv"),
        "test_results": ("tests.csv", (CLEAN_DIR / "test_results.csv").read_bytes(), "text/csv"),
        "telemetry": ("tel.csv", (CLEAN_DIR / "telemetry.csv").read_bytes(), "text/csv"),
    }
    resp = client.post("/api/v1/analyses", files=files)
    assert_schema_error(resp, ("SCH-002",))
    assert_no_analysis_left(tmp_path)


# =============================================================================
# 3. Path Safety: Traversal Filename
# =============================================================================
def test_path_safety_filename_never_influences_path(client, tmp_path):
    """A filename like ../../x.csv is stored only under the server-generated path."""
    files = {
        "requirements": ("../../malicious.csv", (CLEAN_DIR / "requirements.csv").read_bytes(), "text/csv"),
        "test_results": ("tests.csv", (CLEAN_DIR / "test_results.csv").read_bytes(), "text/csv"),
        "telemetry": ("telemetry.csv", (CLEAN_DIR / "telemetry.csv").read_bytes(), "text/csv"),
    }
    resp = client.post("/api/v1/analyses", files=files)
    assert resp.status_code == 201
    analysis_id = resp.json()["id"]

    # Verify files are stored at <uploads>/<analysis_id>/requirements.csv
    upload_dir = tmp_path / "uploads"
    analysis_dir = upload_dir / analysis_id
    assert analysis_dir.exists()
    assert (analysis_dir / "requirements.csv").exists()
    assert not (tmp_path / "malicious.csv").exists()
    assert not Path("malicious.csv").exists()


# =============================================================================
# 4. PATCH /findings/{id}/review Isolation
# =============================================================================
def test_patch_review_isolation(client):
    """PATCH review changes only finding_reviews; findings rows, digest and gate stay identical."""
    resp = client.post("/api/v1/analyses?sample=clean")
    analysis_id = resp.json()["id"]
    orig_digest = resp.json()["findings_digest"]
    orig_gate = resp.json()["gate"]

    findings_resp = client.get(f"/api/v1/analyses/{analysis_id}/findings")
    finding = findings_resp.json()[0]
    finding_id = finding["id"]
    assert finding["review_status"] == "unreviewed"
    assert finding["reviewer_note"] == ""

    # Apply review
    patch_resp = client.patch(
        f"/api/v1/findings/{finding_id}/review",
        json={"review_status": "reviewed", "reviewer_note": "Reviewed by lead engineer"},
    )
    assert patch_resp.status_code == 200
    review_data = patch_resp.json()
    assert review_data["finding_id"] == finding_id
    assert review_data["review_status"] == "reviewed"
    assert review_data["reviewer_note"] == "Reviewed by lead engineer"

    # Check analysis: findings_digest and gate are completely identical
    anl_resp = client.get(f"/api/v1/analyses/{analysis_id}")
    assert anl_resp.json()["findings_digest"] == orig_digest
    assert anl_resp.json()["gate"] == orig_gate

    # Check findings row in DB: immutable (finding data untouched)
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM findings WHERE id = ?;", (finding_id,)).fetchone()
    conn.close()
    assert row["entity_key"] == "TST-002"
    assert row["rule_id"] == "R09"

    # Check review filtering
    reviewed_list = client.get(f"/api/v1/analyses/{analysis_id}/findings?review_status=reviewed").json()
    assert len(reviewed_list) == 1
    assert reviewed_list[0]["id"] == finding_id

    unreviewed_list = client.get(f"/api/v1/analyses/{analysis_id}/findings?review_status=unreviewed").json()
    assert len(unreviewed_list) == 0

    # Validation: note > 2000 chars rejected with 422
    toolong_resp = client.patch(
        f"/api/v1/findings/{finding_id}/review",
        json={"review_status": "reviewed", "reviewer_note": "x" * 2001},
    )
    assert toolong_resp.status_code == 422
    assert "error" in toolong_resp.json()

    # Validation: invalid review_status rejected with 422
    invalid_status_resp = client.patch(
        f"/api/v1/findings/{finding_id}/review",
        json={"review_status": "invalid_status", "reviewer_note": "note"},
    )
    assert invalid_status_resp.status_code == 422


# =============================================================================
# 5. GET /analyses/{id}/datasets/{kind}/preview
# =============================================================================
def test_dataset_preview_endpoint(client):
    """GET preview returns parsed rows up to limit."""
    resp = client.post("/api/v1/analyses?sample=clean")
    analysis_id = resp.json()["id"]

    prev_resp = client.get(f"/api/v1/analyses/{analysis_id}/datasets/requirements/preview?limit=2")
    assert prev_resp.status_code == 200
    prev = prev_resp.json()
    assert prev["kind"] == "requirements"
    assert len(prev["rows"]) == 2
    assert prev["total_rows"] == 3
    assert "requirement_id" in prev["columns"]

    # Invalid kind returns 404
    bad_kind = client.get(f"/api/v1/analyses/{analysis_id}/datasets/nonexistent/preview")
    assert bad_kind.status_code == 404


# =============================================================================
# 6. GET /samples/{clean|fault}.zip Download
# =============================================================================
def test_samples_zip_download(client):
    """Both sample zips download successfully and contain the 3 CSV files."""
    for sample in ("clean", "fault"):
        resp = client.get(f"/api/v1/samples/{sample}.zip")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"
        assert f'filename="{sample}.zip"' in resp.headers["content-disposition"]

        with zipfile.ZipFile(io.BytesIO(resp.content), "r") as zf:
            namelist = zf.namelist()
            assert "requirements.csv" in namelist
            assert "test_results.csv" in namelist
            assert "telemetry.csv" in namelist

    # Nonexistent sample returns 404
    bad_resp = client.get("/api/v1/samples/invalid.zip")
    assert bad_resp.status_code == 404
    assert "error" in bad_resp.json()