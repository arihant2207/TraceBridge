"""Tests for validation rules R01 through R06 (Milestone M2)."""

import json
from pathlib import Path
import pytest

from app.engine.models import RowData
from app.engine.rules import (
    check_r01,
    check_r02,
    check_r03,
    check_r04,
    check_r05,
    check_r06,
    run_rules_m2,
)
from app.ingestion.loader import load_dataset


# Load default ruleset configuration
RULESET_PATH = Path(__file__).resolve().parent.parent / "app" / "engine" / "ruleset.json"
RULESET = json.loads(RULESET_PATH.read_text(encoding="utf-8"))

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"
CLEAN_DIR = SAMPLES_DIR / "clean"
FAULT_DIR = SAMPLES_DIR / "fault"


# =============================================================================
# Helper fixture to create test RowData objects
# =============================================================================
def make_req_row(
    row_num: int = 1,
    req_id: str = "REQ-01",
    signal_name: str = "esc_temperature",
    operator: str = "<=",
    threshold_value: str = "85",
    unit: str = "°C",
) -> RowData:
    r = RowData()
    r["row_number"] = row_num
    r["requirement_id"] = req_id
    r["signal_name"] = signal_name
    r["operator"] = operator
    r["threshold_value"] = threshold_value
    r["unit"] = unit
    return r


def make_test_row(
    row_num: int = 1,
    test_id: str = "TST-01",
    req_id: str = "REQ-01",
    run_id: str = "RUN-01",
    status: str = "Pass",
    started_at: str = "2026-10-01T10:00:00Z",
    completed_at: str = "2026-10-01T10:02:00Z",
    actual_result: str = "78.4",
    unit: str = "°C",
) -> RowData:
    r = RowData()
    r["row_number"] = row_num
    r["test_id"] = test_id
    r["requirement_id"] = req_id
    r["run_id"] = run_id
    r["status"] = status
    r["started_at"] = started_at
    r["completed_at"] = completed_at
    r["actual_result"] = actual_result
    r["unit"] = unit
    return r


def make_tel_row(
    row_num: int = 1,
    run_id: str = "RUN-01",
    timestamp: str = "2026-10-01T10:00:00Z",
    signal_name: str = "esc_temperature",
    value: str = "61.2",
    unit: str = "°C",
) -> RowData:
    r = RowData()
    r["row_number"] = row_num
    r["run_id"] = run_id
    r["timestamp"] = timestamp
    r["signal_name"] = signal_name
    r["value"] = value
    r["unit"] = unit
    return r


# =============================================================================
# Rule R01 tests
# =============================================================================
def test_r01_positive_pass_test_blank_actual_result():
    """Pos: Pass test with blank actual_result produces R01 finding."""
    test_row = make_test_row(actual_result="")
    findings = check_r01([], [test_row], [], RULESET)
    assert len(findings) == 1
    assert findings[0].rule_id == "R01"
    assert findings[0].entity_key == "TST-01"
    assert findings[0].severity == "high"
    assert findings[0].finding_class == "MISSING_EVIDENCE"


def test_r01_negative_not_run_test_blank_fields():
    """Neg: Not Run test with blank run/timestamps/result is valid, no finding."""
    test_row = make_test_row(
        test_id="TST-08",
        req_id="REQ-01",
        run_id="",
        status="Not Run",
        started_at="",
        completed_at="",
        actual_result="",
        unit="",
    )
    findings = check_r01([], [test_row], [], RULESET)
    assert len(findings) == 0


def test_r01_edge_whitespace_only_is_empty():
    """Edge: Whitespace-only in required field is empty (MISSING)."""
    req_row = make_req_row(threshold_value="   ")
    findings = check_r01([req_row], [], [], RULESET)
    assert len(findings) == 1
    assert findings[0].rule_id == "R01"
    assert findings[0].entity_key == "REQ-01"


def test_r01_edge_lowercase_pass_is_invalid_enum():
    """Edge: Lowercase 'pass' is INVALID_ENUM."""
    test_row = make_test_row(status="pass")
    findings = check_r01([], [test_row], [], RULESET)
    assert len(findings) == 1
    assert findings[0].rule_id == "R01"
    assert findings[0].entity_key == "TST-01"
    assert "INVALID_ENUM" in findings[0].actual


def test_r01_edge_operator_invalid_enum():
    """Edge: Invalid operator (e.g. '==') is INVALID_ENUM."""
    req_row = make_req_row(operator="==")
    findings = check_r01([req_row], [], [], RULESET)
    assert len(findings) == 1
    assert findings[0].rule_id == "R01"
    assert "INVALID_ENUM" in findings[0].actual


def test_r01_edge_literal_na_is_value_not_missing():
    """Edge: Literal 'NA' or 'n/a' is a value, not missing (no R01 finding)."""
    test_row = make_test_row(actual_result="NA")
    findings = check_r01([], [test_row], [], RULESET)
    assert len(findings) == 0


def test_r01_telemetry_grouped_per_series():
    """Telemetry R01 findings are grouped per series (run_id:signal_name)."""
    t1 = make_tel_row(row_num=1, run_id="RUN-01", signal_name="temp", value="")
    t2 = make_tel_row(row_num=2, run_id="RUN-01", signal_name="temp", unit="")
    findings = check_r01([], [], [t1, t2], RULESET)
    assert len(findings) == 1
    assert findings[0].rule_id == "R01"
    assert findings[0].entity_key == "RUN-01:temp"
    assert len(findings[0].source_refs) == 2


# =============================================================================
# Rule R02 tests
# =============================================================================
def test_r02_positive_tst_010_twice():
    """Pos: TST-010 twice produces R02 finding listing all rows."""
    t1 = make_test_row(row_num=10, test_id="TST-010", run_id="RUN-0009")
    t2 = make_test_row(row_num=11, test_id="TST-010", run_id="RUN-0010")
    findings = check_r02([], [t1, t2], [], RULESET)
    assert len(findings) == 1
    assert findings[0].rule_id == "R02"
    assert findings[0].entity_key == "TST-010"
    assert len(findings[0].source_refs) == 2
    assert findings[0].source_refs[0].row_number == 10
    assert findings[0].source_refs[1].row_number == 11


def test_r02_positive_duplicate_requirement_id():
    """Duplicate requirement_id produces R02 finding."""
    r1 = make_req_row(row_num=1, req_id="REQ-01")
    r2 = make_req_row(row_num=2, req_id="REQ-01")
    findings = check_r02([r1, r2], [], [], RULESET)
    assert len(findings) == 1
    assert findings[0].rule_id == "R02"
    assert findings[0].entity_key == "REQ-01"


def test_r02_positive_duplicate_run_id_in_tests():
    """Duplicate non-blank run_id in tests produces R02 finding."""
    t1 = make_test_row(row_num=1, test_id="TST-01", run_id="RUN-01")
    t2 = make_test_row(row_num=2, test_id="TST-02", run_id="RUN-01")
    findings = check_r02([], [t1, t2], [], RULESET)
    assert len(findings) == 1
    assert findings[0].rule_id == "R02"
    assert findings[0].entity_key == "RUN-01"


def test_r02_positive_duplicate_telemetry_tuple():
    """Duplicate (run_id, timestamp, signal_name) in telemetry produces R02."""
    t1 = make_tel_row(row_num=1, run_id="RUN-01", timestamp="2026-10-01T10:00:00Z", signal_name="temp")
    t2 = make_tel_row(row_num=2, run_id="RUN-01", timestamp="2026-10-01T10:00:00Z", signal_name="temp")
    findings = check_r02([], [], [t1, t2], RULESET)
    assert len(findings) == 1
    assert findings[0].rule_id == "R02"
    assert findings[0].entity_key == "RUN-01:temp"


def test_r02_negative_same_run_id_across_many_telemetry_rows():
    """Neg: Same run_id across many telemetry rows is valid, no finding."""
    t1 = make_tel_row(row_num=1, run_id="RUN-01", timestamp="2026-10-01T10:00:00Z")
    t2 = make_tel_row(row_num=2, run_id="RUN-01", timestamp="2026-10-01T10:01:00Z")
    findings = check_r02([], [], [t1, t2], RULESET)
    assert len(findings) == 0


def test_r02_edge_identical_duplicate_rows_still_flagged():
    """Edge: Identical duplicate rows still flagged."""
    t1 = make_test_row(row_num=1, test_id="TST-01")
    t2 = make_test_row(row_num=2, test_id="TST-01")
    findings = check_r02([], [t1, t2], [], RULESET)
    assert len(findings) == 2  # duplicate test_id and duplicate run_id


def test_r02_edge_case_sensitive():
    """Edge: Identifier comparison is case-sensitive."""
    r1 = make_req_row(row_num=1, req_id="REQ-THM-011")
    r2 = make_req_row(row_num=2, req_id="req-thm-011")
    findings = check_r02([r1, r2], [], [], RULESET)
    assert len(findings) == 0


def test_r02_edge_several_not_run_rows_with_blank_run_id_not_duplicates():
    """Edge: Several Not Run rows with blank run_id are NOT duplicates."""
    t1 = make_test_row(row_num=1, test_id="TST-01", run_id="", status="Not Run")
    t2 = make_test_row(row_num=2, test_id="TST-02", run_id="", status="Not Run")
    findings = check_r02([], [t1, t2], [], RULESET)
    assert len(findings) == 0


# =============================================================================
# Rule R03 tests
# =============================================================================
def test_r03_positive_telemetry_value_na():
    """Pos: Telemetry value 'n/a' produces R03 finding."""
    t1 = make_tel_row(row_num=5, run_id="RUN-02", signal_name="motor_current", value="n/a")
    findings = check_r03([], [], [t1], RULESET)
    assert len(findings) == 1
    assert findings[0].rule_id == "R03"
    assert findings[0].entity_key == "RUN-02:motor_current"
    assert findings[0].severity == "medium"
    assert findings[0].finding_class == "VALIDATION_FAILURE"


def test_r03_negative_valid_number():
    """Neg: '-5.0' is a valid numeric value."""
    t1 = make_tel_row(value="-5.0")
    t2 = make_test_row(actual_result="85.5")
    r1 = make_req_row(threshold_value="+100")
    findings = check_r03([r1], [t2], [t1], RULESET)
    assert len(findings) == 0


@pytest.mark.parametrize("bad_val", ["NaN", "nan", "inf", "-inf", "1e3", "12,5"])
def test_r03_edge_rejected_numbers(bad_val: str):
    """Edge: NaN, inf, 1e3, 12,5 rejected."""
    t1 = make_tel_row(value=bad_val)
    findings = check_r03([], [], [t1], RULESET)
    assert len(findings) == 1
    assert findings[0].rule_id == "R03"


def test_r03_edge_blank_numeric_value_ignored():
    """Edge: Blank numeric value is ignored by R03 (handled by R01 if required)."""
    t1 = make_test_row(actual_result="", status="Not Run")
    findings = check_r03([], [t1], [], RULESET)
    assert len(findings) == 0


# =============================================================================
# Rule R04 tests
# =============================================================================
def test_r04_positive_space_separator_and_no_offset():
    """Pos: '2026-10-01 12:00:00' produces R04 finding."""
    t1 = make_test_row(started_at="2026-10-01 12:00:00")
    findings = check_r04([], [t1], [], RULESET)
    assert len(findings) == 1
    assert findings[0].rule_id == "R04"
    assert findings[0].entity_key == "TST-01"


def test_r04_negative_valid_timestamp_with_offset():
    """Neg: '2026-10-01T12:00:00+05:30' is valid."""
    t1 = make_test_row(
        started_at="2026-10-01T12:00:00+05:30",
        completed_at="2026-10-01T12:02:00+05:30",
    )
    findings = check_r04([], [t1], [], RULESET)
    assert len(findings) == 0


def test_r04_edge_equal_start_complete_allowed():
    """Edge: Equal start and complete allowed."""
    ts = "2026-10-01T12:00:00Z"
    t1 = make_test_row(started_at=ts, completed_at=ts)
    findings = check_r04([], [t1], [], RULESET)
    assert len(findings) == 0


def test_r04_edge_completed_before_started():
    """Edge: completed_at < started_at triggers R04 (reason ORDER)."""
    t1 = make_test_row(
        started_at="2026-10-01T12:05:00Z",
        completed_at="2026-10-01T12:00:00Z",
    )
    findings = check_r04([], [t1], [], RULESET)
    assert len(findings) == 1
    assert findings[0].rule_id == "R04"
    assert "ORDER" in findings[0].description


@pytest.mark.parametrize(
    "bad_ts",
    [
        "2026-10-01",                   # date-only
        "2026-02-30T12:00:00Z",         # Feb 30 invalid calendar
        "2026-10-01T24:00:00Z",         # 24:00:00 invalid hour
        "2026-10-01T12:00:00",          # missing offset
    ],
)
def test_r04_edge_invalid_timestamps(bad_ts: str):
    """Edge: Date-only, Feb 30, 24:00:00, and missing offset are invalid."""
    t1 = make_test_row(started_at=bad_ts)
    findings = check_r04([], [t1], [], RULESET)
    assert len(findings) == 1
    assert findings[0].rule_id == "R04"


def test_r04_edge_fractional_seconds_allowed():
    """Edge: Fractional seconds allowed."""
    t1 = make_test_row(
        started_at="2026-10-01T12:00:00.123456Z",
        completed_at="2026-10-01T12:02:00.654321Z",
    )
    findings = check_r04([], [t1], [], RULESET)
    assert len(findings) == 0


# =============================================================================
# Rule R05 tests
# =============================================================================
def test_r05_positive_unknown_requirement():
    """Pos: TST-009 -> REQ-THM-099 not in requirements produces R05 finding."""
    r1 = make_req_row(req_id="REQ-THM-011")
    t1 = make_test_row(test_id="TST-009", req_id="REQ-THM-099")
    findings = check_r05([r1], [t1], [], RULESET)
    assert len(findings) == 1
    assert findings[0].rule_id == "R05"
    assert findings[0].entity_key == "TST-009"
    assert findings[0].actual == "REQ-THM-099"


def test_r05_negative_not_run_pointing_to_existing_requirement():
    """Neg: Not Run test pointing to existing requirement is valid."""
    r1 = make_req_row(req_id="REQ-THM-011")
    t1 = make_test_row(test_id="TST-08", req_id="REQ-THM-011", status="Not Run")
    findings = check_r05([r1], [t1], [], RULESET)
    assert len(findings) == 0


def test_r05_edge_blank_is_r01_not_r05():
    """Edge: Blank requirement_id is R01 not R05."""
    r1 = make_req_row(req_id="REQ-THM-011")
    t1 = make_test_row(test_id="TST-01", req_id="")
    findings = check_r05([r1], [t1], [], RULESET)
    assert len(findings) == 0


def test_r05_edge_case_sensitive():
    """Edge: Requirement reference is case-sensitive."""
    r1 = make_req_row(req_id="REQ-THM-011")
    t1 = make_test_row(test_id="TST-01", req_id="req-thm-011")
    findings = check_r05([r1], [t1], [], RULESET)
    assert len(findings) == 1
    assert findings[0].rule_id == "R05"


# =============================================================================
# Rule R06 tests
# =============================================================================
def test_r06_positive_unknown_run():
    """Pos: RUN-0099 in telemetry not among test_results produces R06 finding."""
    t_test = make_test_row(run_id="RUN-0001")
    tel1 = make_tel_row(row_num=18, run_id="RUN-0099")
    tel2 = make_tel_row(row_num=19, run_id="RUN-0099")
    findings = check_r06([], [t_test], [tel1, tel2], RULESET)
    assert len(findings) == 1
    assert findings[0].rule_id == "R06"
    assert findings[0].entity_key == "RUN-0099"
    assert len(findings[0].source_refs) == 2


def test_r06_negative_defective_test_row_run_still_known():
    """Neg: Telemetry for run whose test row has other defects is still known."""
    # Test row has defective actual_result and bad operator, but run_id is known
    t_test = make_test_row(run_id="RUN-0002", actual_result="invalid_num")
    tel = make_tel_row(run_id="RUN-0002")
    findings = check_r06([], [t_test], [tel], RULESET)
    assert len(findings) == 0


def test_r06_edge_blank_run_id_skipped():
    """Edge: Blank run_id in telemetry is skipped by R06 (handled by R01)."""
    tel = make_tel_row(run_id="")
    findings = check_r06([], [], [tel], RULESET)
    assert len(findings) == 0


# =============================================================================
# Sample Datasets Acceptance Test
# =============================================================================
def test_clean_dataset_produces_no_r01_to_r06_findings():
    """Clean sample CSVs produce zero R01 to R06 findings."""
    req = load_dataset((CLEAN_DIR / "requirements.csv").read_bytes(), "requirements.csv", "requirements")
    test = load_dataset((CLEAN_DIR / "test_results.csv").read_bytes(), "test_results.csv", "test_results")
    tel = load_dataset((CLEAN_DIR / "telemetry.csv").read_bytes(), "telemetry.csv", "telemetry")

    findings = run_rules_m2(req, test, tel, RULESET)
    assert len(findings) == 0


def test_fault_dataset_produces_exact_r01_to_r06_findings():
    """Fault sample CSVs produce exactly the expected 6 (rule, entity) findings."""
    req = load_dataset((FAULT_DIR / "requirements.csv").read_bytes(), "requirements.csv", "requirements")
    test = load_dataset((FAULT_DIR / "test_results.csv").read_bytes(), "test_results.csv", "test_results")
    tel = load_dataset((FAULT_DIR / "telemetry.csv").read_bytes(), "telemetry.csv", "telemetry")

    findings = run_rules_m2(req, test, tel, RULESET)
    pairs = [(f.rule_id, f.entity_key) for f in findings]

    expected_pairs = [
        ("R01", "TST-006"),
        ("R02", "TST-010"),
        ("R03", "RUN-0002:motor_current"),
        ("R04", "TST-003"),
        ("R05", "TST-009"),
        ("R06", "RUN-0099"),
    ]
    assert pairs == expected_pairs
