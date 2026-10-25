"""Tests for evaluation pipeline S1 to S6 and rules R07 to R12."""

from decimal import Decimal
import json
from pathlib import Path
import pytest

from app.engine.evaluate import evaluate_pipeline
from app.engine.models import Finding, RowData, SourceRef
from app.engine.rules import (
    UNIT_REGISTRY,
    check_r01,
    check_r02,
    check_r03,
    check_r04,
    check_r05,
    check_r06,
    check_r07,
    check_r11_unit,
    find_extremum,
)
from app.ingestion.loader import load_dataset


def load_csv(path: Path, kind: str):
    return load_dataset(path.read_bytes(), path.name, kind)

RULESET_PATH = Path(__file__).resolve().parent.parent / "app" / "engine" / "ruleset.json"
with open(RULESET_PATH, "r", encoding="utf-8") as f:
    RULESET = json.load(f)

FAULT_DIR = Path(__file__).resolve().parent.parent / "samples" / "fault"
CLEAN_DIR = Path(__file__).resolve().parent.parent / "samples" / "clean"


def make_req_row(
    row_num: int = 1,
    requirement_id: str = "REQ-01",
    description: str = "Test req",
    signal_name: str = "temp",
    operator: str = "<=",
    threshold_value: str = "85",
    unit: str = "°C",
) -> RowData:
    return RowData(
        row_number=row_num,
        requirement_id=requirement_id,
        description=description,
        signal_name=signal_name,
        operator=operator,
        threshold_value=threshold_value,
        unit=unit,
    )


def make_test_row(
    row_num: int = 1,
    test_id: str = "TST-01",
    requirement_id: str = "REQ-01",
    run_id: str = "RUN-01",
    status: str = "Pass",
    started_at: str = "2026-10-01T10:00:00Z",
    completed_at: str = "2026-10-01T10:02:00Z",
    actual_result: str = "75.0",
    unit: str = "°C",
) -> RowData:
    return RowData(
        row_number=row_num,
        test_id=test_id,
        requirement_id=requirement_id,
        run_id=run_id,
        status=status,
        started_at=started_at,
        completed_at=completed_at,
        actual_result=actual_result,
        unit=unit,
    )


def make_tel_row(
    row_num: int = 1,
    run_id: str = "RUN-01",
    timestamp: str = "2026-10-01T10:01:00Z",
    signal_name: str = "temp",
    value: str = "75.0",
    unit: str = "°C",
) -> RowData:
    return RowData(
        row_number=row_num,
        run_id=run_id,
        timestamp=timestamp,
        signal_name=signal_name,
        value=value,
        unit=unit,
    )


# =============================================================================
# Rule R07: Missing requirement-to-test link
# =============================================================================
def test_r07_positive_no_test():
    """Pos 1: REQ-PWR-009 has zero links -> NO_TEST variant."""
    r = make_req_row(requirement_id="REQ-PWR-009")
    findings = check_r07([r], [], RULESET)
    assert len(findings) == 1
    assert findings[0].rule_id == "R07"
    assert findings[0].variant == "NO_TEST"
    assert findings[0].entity_key == "REQ-PWR-009"
    assert findings[0].severity == "high"
    assert findings[0].finding_class == "MISSING_EVIDENCE"


def test_r07_positive_not_executed():
    """Pos 2: REQ-THM-015 has test row with status 'Not Run' -> NOT_EXECUTED variant."""
    r = make_req_row(requirement_id="REQ-THM-015")
    t = make_test_row(requirement_id="REQ-THM-015", status="Not Run")
    findings = check_r07([r], [t], RULESET)
    assert len(findings) == 1
    assert findings[0].rule_id == "R07"
    assert findings[0].variant == "NOT_EXECUTED"
    assert findings[0].entity_key == "REQ-THM-015"


def test_r07_negative():
    """Neg: Requirement with one Pass test produces zero R07 findings."""
    r = make_req_row(requirement_id="REQ-01")
    t = make_test_row(requirement_id="REQ-01", status="Pass")
    findings = check_r07([r], [t], RULESET)
    assert len(findings) == 0


def test_r07_edge_nonexistent_req():
    """Edge 1: A test pointing to a nonexistent requirement links nothing."""
    r = make_req_row(requirement_id="REQ-01")
    t = make_test_row(requirement_id="REQ-99", status="Pass")
    findings = check_r07([r], [t], RULESET)
    assert len(findings) == 1
    assert findings[0].entity_key == "REQ-01"
    assert findings[0].variant == "NO_TEST"


def test_r07_edge_evaluated_once_per_id():
    """Edge 2: Requirement evaluated once per ID even if duplicate requirement rows exist."""
    r1 = make_req_row(row_num=1, requirement_id="REQ-01")
    r2 = make_req_row(row_num=2, requirement_id="REQ-01")
    findings = check_r07([r1, r2], [], RULESET)
    assert len(findings) == 1
    assert findings[0].entity_key == "REQ-01"


def test_r07_edge_fail_status_counts_as_executed():
    """Edge 3: Fail status counts as executed and covers requirement."""
    r = make_req_row(requirement_id="REQ-01")
    t = make_test_row(requirement_id="REQ-01", status="Fail")
    findings = check_r07([r], [t], RULESET)
    assert len(findings) == 0


def test_r07_edge_invalid_enum_is_not_executed():
    """Edge 4: Test with invalid status (e.g. lowercase 'pass') triggers NOT_EXECUTED."""
    r = make_req_row(requirement_id="REQ-01")
    t = make_test_row(requirement_id="REQ-01", status="pass")
    findings = check_r07([r], [t], RULESET)
    assert len(findings) == 1
    assert findings[0].variant == "NOT_EXECUTED"


# =============================================================================
# Rule R08: Missing required telemetry evidence
# =============================================================================
def test_r08_positive():
    """Pos: TST-007 has zero in-window telemetry for its signal."""
    req = make_req_row(requirement_id="REQ-PWR-002", signal_name="battery_voltage")
    test = make_test_row(test_id="TST-007", requirement_id="REQ-PWR-002", run_id="RUN-0007")
    # Telemetry has different signal
    tel = make_tel_row(run_id="RUN-0007", signal_name="motor_current")
    evals, findings = evaluate_pipeline([req], [test], [tel], ruleset=RULESET)
    r08 = [f for f in findings if f.rule_id == "R08"]
    assert len(r08) == 1
    assert r08[0].entity_key == "TST-007"
    assert evals[0].outcome == "INCONCLUSIVE"
    assert evals[0].blocked_by == ["R08:TST-007"]


def test_r08_negative():
    """Neg: Test with in-window telemetry does not emit R08."""
    req = make_req_row(signal_name="temp")
    test = make_test_row(test_id="TST-001", run_id="RUN-0001")
    tel = make_tel_row(run_id="RUN-0001", signal_name="temp", timestamp="2026-10-01T10:01:00Z")
    evals, findings = evaluate_pipeline([req], [test], [tel], ruleset=RULESET)
    r08 = [f for f in findings if f.rule_id == "R08"]
    assert len(r08) == 0
    assert evals[0].n_in_window == 1


def test_r08_edge_inclusive_window():
    """Edge 1: Samples exactly at started_at and completed_at count as in-window."""
    req = make_req_row(signal_name="temp")
    test = make_test_row(
        test_id="TST-01",
        run_id="RUN-01",
        started_at="2026-10-01T10:00:00Z",
        completed_at="2026-10-01T10:02:00Z",
    )
    t1 = make_tel_row(run_id="RUN-01", signal_name="temp", timestamp="2026-10-01T10:00:00Z")
    t2 = make_tel_row(run_id="RUN-01", signal_name="temp", timestamp="2026-10-01T10:02:00Z")
    evals, findings = evaluate_pipeline([req], [test], [t1, t2], ruleset=RULESET)
    assert not any(f.rule_id == "R08" for f in findings)
    assert evals[0].n_in_window == 2
    assert evals[0].n_out_of_window == 0


def test_r08_edge_samples_only_outside_window():
    """Edge 2: Telemetry rows only outside window still trigger R08 and show out-of-window count."""
    req = make_req_row(signal_name="temp")
    test = make_test_row(
        test_id="TST-01",
        run_id="RUN-01",
        started_at="2026-10-01T10:00:00Z",
        completed_at="2026-10-01T10:02:00Z",
    )
    t_before = make_tel_row(
        run_id="RUN-01", signal_name="temp", timestamp="2026-10-01T09:59:59Z"
    )
    t_after = make_tel_row(
        run_id="RUN-01", signal_name="temp", timestamp="2026-10-01T10:02:01Z"
    )
    evals, findings = evaluate_pipeline([req], [test], [t_before, t_after], ruleset=RULESET)
    r08 = [f for f in findings if f.rule_id == "R08"]
    assert len(r08) == 1
    assert evals[0].n_in_window == 0
    assert evals[0].n_out_of_window == 2
    assert "2 out of window" in r08[0].actual


# =============================================================================
# Rule R09: Threshold violation
# =============================================================================
def test_r09_positive_max_violation():
    """Pos: <= 85 with max 91.0 produces R09 OBSERVATION."""
    req = make_req_row(operator="<=", threshold_value="85", signal_name="temp")
    test = make_test_row(test_id="TST-001", run_id="RUN-0001", status="Fail")
    tel = [
        make_tel_row(row_num=1, run_id="RUN-0001", signal_name="temp", value="61.2"),
        make_tel_row(row_num=2, run_id="RUN-0001", signal_name="temp", value="91.0"),
    ]
    evals, findings = evaluate_pipeline([req], [test], tel, ruleset=RULESET)
    r09 = [f for f in findings if f.rule_id == "R09"]
    assert len(r09) == 1
    assert r09[0].entity_key == "TST-001"
    assert r09[0].severity == "high"
    assert r09[0].finding_class == "OBSERVATION"
    assert evals[0].outcome == "VIOLATED"
    assert evals[0].aggregate == "91.0"


def test_r09_negative():
    """Neg: <= 85 with max 78.4 does not produce R09."""
    req = make_req_row(operator="<=", threshold_value="85", signal_name="temp")
    test = make_test_row(test_id="TST-001", run_id="RUN-0001", status="Pass")
    tel = [make_tel_row(run_id="RUN-0001", signal_name="temp", value="78.4")]
    evals, findings = evaluate_pipeline([req], [test], tel, ruleset=RULESET)
    assert not any(f.rule_id == "R09" for f in findings)
    assert evals[0].outcome == "SATISFIED"


def test_r09_edge_boundary_comparisons():
    """Edge 1 & 2: 85.0 <= 85 is satisfied, but 85.0 < 85 is violated."""
    req_le = make_req_row(operator="<=", threshold_value="85", signal_name="temp")
    req_lt = make_req_row(operator="<", threshold_value="85", signal_name="temp")
    test = make_test_row(test_id="TST-01", run_id="RUN-01", status="Pass")
    tel = [make_tel_row(run_id="RUN-01", signal_name="temp", value="85.0")]

    evals_le, findings_le = evaluate_pipeline([req_le], [test], tel, ruleset=RULESET)
    assert evals_le[0].outcome == "SATISFIED"
    assert not any(f.rule_id == "R09" for f in findings_le)

    evals_lt, findings_lt = evaluate_pipeline([req_lt], [test], tel, ruleset=RULESET)
    assert evals_lt[0].outcome == "VIOLATED"
    assert any(f.rule_id == "R09" for f in findings_lt)


def test_r09_edge_negatives():
    """Edge 3: Negative numbers comparison."""
    req = make_req_row(operator=">=", threshold_value="-10.0", signal_name="temp")
    test = make_test_row(test_id="TST-01", run_id="RUN-01", status="Pass")
    # min is -15.0 which violates >= -10.0
    tel = [
        make_tel_row(row_num=1, run_id="RUN-01", signal_name="temp", value="-5.0"),
        make_tel_row(row_num=2, run_id="RUN-01", signal_name="temp", value="-15.0"),
    ]
    evals, findings = evaluate_pipeline([req], [test], tel, ruleset=RULESET)
    assert evals[0].outcome == "VIOLATED"
    assert evals[0].aggregate == "-15.0"
    assert any(f.rule_id == "R09" for f in findings)


def test_r09_edge_tie_earliest_timestamp():
    """Edge 4: Ties list earliest timestamp in source_refs."""
    req = make_req_row(operator="<=", threshold_value="80", signal_name="temp")
    test = make_test_row(test_id="TST-01", run_id="RUN-01", status="Fail")
    tel = [
        make_tel_row(
            row_num=5,
            run_id="RUN-01",
            timestamp="2026-10-01T10:01:30Z",
            signal_name="temp",
            value="90.0",
        ),
        make_tel_row(
            row_num=2,
            run_id="RUN-01",
            timestamp="2026-10-01T10:00:30Z",
            signal_name="temp",
            value="90.0",
        ),
    ]
    evals, findings = evaluate_pipeline([req], [test], tel, ruleset=RULESET)
    r09 = [f for f in findings if f.rule_id == "R09"][0]
    # Extremum telemetry ref should be row_num 2 (earlier timestamp)
    tel_ref = [ref for ref in r09.source_refs if ref.file == "telemetry.csv"][0]
    assert tel_ref.row_number == 2


# =============================================================================
# Rule R10: Status vs measurement contradiction
# =============================================================================
def test_r10_positive_pass_with_violated():
    """Pos 1: Test status Pass with outcome VIOLATED triggers R10 Critical."""
    req = make_req_row(operator="<=", threshold_value="85", signal_name="temp")
    test = make_test_row(test_id="TST-001", run_id="RUN-0001", status="Pass")
    tel = [make_tel_row(run_id="RUN-0001", signal_name="temp", value="91.0")]
    evals, findings = evaluate_pipeline([req], [test], tel, ruleset=RULESET)
    r10 = [f for f in findings if f.rule_id == "R10"]
    assert len(r10) == 1
    assert r10[0].severity == "critical"
    assert r10[0].finding_class == "VALIDATION_FAILURE"
    assert r10[0].entity_key == "TST-001"


def test_r10_positive_fail_with_satisfied():
    """Pos 2: Test status Fail with outcome SATISFIED triggers R10 Critical."""
    req = make_req_row(operator=">=", threshold_value="20", signal_name="volt", unit="V")
    test = make_test_row(
        test_id="TST-005", run_id="RUN-0005", status="Fail", unit="V", actual_result="21.6"
    )
    tel = [make_tel_row(run_id="RUN-0005", signal_name="volt", value="21.6", unit="V")]
    evals, findings = evaluate_pipeline([req], [test], tel, ruleset=RULESET)
    r10 = [f for f in findings if f.rule_id == "R10"]
    assert len(r10) == 1
    assert r10[0].entity_key == "TST-005"


def test_r10_negative_fail_with_violated():
    """Neg: Test status Fail with outcome VIOLATED has no contradiction."""
    req = make_req_row(operator="<=", threshold_value="30", signal_name="curr", unit="A")
    test = make_test_row(
        test_id="TST-002", run_id="RUN-0002", status="Fail", unit="A", actual_result="32.4"
    )
    tel = [make_tel_row(run_id="RUN-0002", signal_name="curr", value="32.4", unit="A")]
    evals, findings = evaluate_pipeline([req], [test], tel, ruleset=RULESET)
    assert not any(f.rule_id == "R10" for f in findings)


def test_r10_edge_inconclusive_never_triggers():
    """Edge 1: Inconclusive evaluation never triggers R10."""
    req = make_req_row(signal_name="temp")
    test = make_test_row(test_id="TST-01", run_id="RUN-01", status="Pass")
    # No telemetry -> R08 emitted, evaluation INCONCLUSIVE
    evals, findings = evaluate_pipeline([req], [test], [], ruleset=RULESET)
    assert evals[0].outcome == "INCONCLUSIVE"
    assert not any(f.rule_id == "R10" for f in findings)


def test_r10_edge_not_run_excluded():
    """Edge 2: Not Run tests have no evaluation and never trigger R10."""
    req = make_req_row(signal_name="temp")
    test = make_test_row(test_id="TST-01", run_id="RUN-01", status="Not Run")
    tel = [make_tel_row(run_id="RUN-01", signal_name="temp", value="99.0")]
    evals, findings = evaluate_pipeline([req], [test], tel, ruleset=RULESET)
    assert len(evals) == 0
    assert not any(f.rule_id == "R10" for f in findings)


# =============================================================================
# Rule R11: Invalid unit combination
# =============================================================================
def test_r11_positive_unit_mismatch():
    """Pos: req=A, test=A, tel=mA -> UNIT_MISMATCH."""
    req = make_req_row(signal_name="curr", unit="A")
    test = make_test_row(test_id="TST-004", run_id="RUN-0004", unit="A")
    tel = [make_tel_row(run_id="RUN-0004", signal_name="curr", unit="mA")]
    evals, findings = evaluate_pipeline([req], [test], tel, ruleset=RULESET)
    r11 = [f for f in findings if f.rule_id == "R11"]
    assert len(r11) == 1
    assert r11[0].variant == "UNIT_MISMATCH"
    assert r11[0].entity_key == "TST-004"
    assert evals[0].outcome == "INCONCLUSIVE"
    assert evals[0].blocked_by == ["R11:TST-004"]


def test_r11_negative():
    """Neg: All units equal and valid -> no R11."""
    req = make_req_row(signal_name="curr", unit="A")
    test = make_test_row(test_id="TST-01", run_id="RUN-01", unit="A")
    tel = [make_tel_row(run_id="RUN-01", signal_name="curr", unit="A")]
    evals, findings = evaluate_pipeline([req], [test], tel, ruleset=RULESET)
    assert not any(f.rule_id == "R11" for f in findings)


def test_r11_edge_unknown_unit():
    """Edge 1: Unknown unit triggers UNKNOWN_UNIT (e.g. ℃, a, volts)."""
    assert check_r11_unit("℃", "°C", ["°C"]) == "UNKNOWN_UNIT"
    assert check_r11_unit("°C", "a", ["°C"]) == "UNKNOWN_UNIT"
    assert check_r11_unit("°C", "°C", ["volts"]) == "UNKNOWN_UNIT"


def test_r11_edge_dimension_mismatch():
    """Edge 2: Dimension mismatch (e.g. °C vs A)."""
    assert check_r11_unit("°C", "A", ["°C"]) == "DIMENSION_MISMATCH"


def test_r11_edge_same_dimension_unit_mismatch():
    """Edge 3: Same dimension different unit is UNIT_MISMATCH (°C vs K)."""
    assert check_r11_unit("°C", "K", ["°C"]) == "UNIT_MISMATCH"
    assert check_r11_unit("V", "mV", ["V"]) == "UNIT_MISMATCH"


# =============================================================================
# Rule R12: Reported value inconsistent with source
# =============================================================================
def test_r12_positive():
    """Pos: 78.4 reported vs 91.0 aggregate -> diff 12.6 > 0.05 triggers R12."""
    req = make_req_row(signal_name="temp")
    test = make_test_row(
        test_id="TST-001", run_id="RUN-0001", status="Pass", actual_result="78.4"
    )
    tel = [make_tel_row(run_id="RUN-0001", signal_name="temp", value="91.0")]
    evals, findings = evaluate_pipeline([req], [test], tel, ruleset=RULESET)
    r12 = [f for f in findings if f.rule_id == "R12"]
    assert len(r12) == 1
    assert r12[0].entity_key == "TST-001"
    assert r12[0].severity == "high"
    assert r12[0].finding_class == "VALIDATION_FAILURE"


def test_r12_negative():
    """Neg: 21.6 reported vs 21.6 aggregate -> diff 0 <= 0.05 does not trigger R12."""
    req = make_req_row(operator=">=", threshold_value="20", signal_name="volt", unit="V")
    test = make_test_row(
        test_id="TST-005", run_id="RUN-0005", status="Pass", unit="V", actual_result="21.6"
    )
    tel = [make_tel_row(run_id="RUN-0005", signal_name="volt", value="21.6", unit="V")]
    evals, findings = evaluate_pipeline([req], [test], tel, ruleset=RULESET)
    assert not any(f.rule_id == "R12" for f in findings)


def test_r12_edge_exact_tolerance():
    """Edge 1: Difference of exactly 0.05 passes (strictly greater)."""
    req = make_req_row(operator="<=", threshold_value="80", signal_name="temp")
    test = make_test_row(
        test_id="TST-01", run_id="RUN-01", status="Pass", actual_result="75.05"
    )
    tel = [make_tel_row(run_id="RUN-01", signal_name="temp", value="75.00")]
    evals, findings = evaluate_pipeline([req], [test], tel, ruleset=RULESET)
    assert not any(f.rule_id == "R12" for f in findings)


def test_r12_edge_strictly_greater():
    """Edge 2: Difference of 0.05001 triggers R12."""
    req = make_req_row(operator="<=", threshold_value="80", signal_name="temp")
    test = make_test_row(
        test_id="TST-01", run_id="RUN-01", status="Pass", actual_result="75.051"
    )
    tel = [make_tel_row(run_id="RUN-01", signal_name="temp", value="75.00")]
    evals, findings = evaluate_pipeline([req], [test], tel, ruleset=RULESET)
    assert any(f.rule_id == "R12" for f in findings)


def test_r12_edge_trailing_zero_equivalence():
    """Edge 3: 21.60 equals 21.6."""
    req = make_req_row(operator="<=", threshold_value="80", signal_name="temp")
    test = make_test_row(
        test_id="TST-01", run_id="RUN-01", status="Pass", actual_result="21.60"
    )
    tel = [make_tel_row(run_id="RUN-01", signal_name="temp", value="21.6")]
    evals, findings = evaluate_pipeline([req], [test], tel, ruleset=RULESET)
    assert not any(f.rule_id == "R12" for f in findings)


# =============================================================================
# Pipeline Stop Points S1 through S6
# =============================================================================
def test_stop_point_s1_test_defect():
    """S1 stop point: Test row defect (e.g. invalid timestamp R04) stops at S1."""
    req = make_req_row()
    test = make_test_row(test_id="TST-003", started_at="2026-10-01 12:00:00")
    m2_findings = check_r04([req], [test], [], RULESET)
    evals, findings = evaluate_pipeline([req], [test], [], m2_findings, ruleset=RULESET)
    assert len(evals) == 1
    assert evals[0].outcome == "INCONCLUSIVE"
    assert evals[0].blocked_by == ["R04:TST-003"]
    # Does not produce R08..R12
    assert not any(f.rule_id in ("R08", "R09", "R10", "R11", "R12") for f in findings)


def test_stop_point_s1_duplicate_test_id():
    """S1 stop point: Duplicate test_id (R02) causes S1 to fail for both rows."""
    req = make_req_row()
    t1 = make_test_row(row_num=10, test_id="TST-010", run_id="RUN-0009")
    t2 = make_test_row(row_num=11, test_id="TST-010", run_id="RUN-0010")
    m2_findings = check_r02([req], [t1, t2], [], RULESET)
    evals, findings = evaluate_pipeline([req], [t1, t2], [], m2_findings, ruleset=RULESET)
    assert len(evals) == 2
    assert evals[0].test_id == "TST-010"
    assert evals[0].outcome == "INCONCLUSIVE"
    assert evals[0].blocked_by == ["R02:TST-010"]
    assert evals[1].test_id == "TST-010"
    assert evals[1].outcome == "INCONCLUSIVE"
    assert evals[1].blocked_by == ["R02:TST-010"]


def test_stop_point_s1_unknown_req():
    """S1 stop point: Unknown requirement reference (R05) stops at S1."""
    req = make_req_row(requirement_id="REQ-THM-011")
    test = make_test_row(test_id="TST-009", requirement_id="REQ-THM-099")
    m2_findings = check_r05([req], [test], RULESET)
    evals, findings = evaluate_pipeline([req], [test], [], m2_findings, ruleset=RULESET)
    assert len(evals) == 1
    assert evals[0].outcome == "INCONCLUSIVE"
    assert evals[0].blocked_by == ["R05:TST-009"]


def test_stop_point_s2_telemetry_defect():
    """S2 stop point: Selected telemetry row has R03 (n/a value) -> stops at S2."""
    req = make_req_row(requirement_id="REQ-ELC-004", signal_name="motor_current")
    test = make_test_row(test_id="TST-002", requirement_id="REQ-ELC-004", run_id="RUN-0002")
    tel = make_tel_row(run_id="RUN-0002", signal_name="motor_current", value="n/a")
    m2_findings = check_r03([req], [test], [tel], RULESET)
    evals, findings = evaluate_pipeline([req], [test], [tel], m2_findings, ruleset=RULESET)
    assert len(evals) == 1
    assert evals[0].outcome == "INCONCLUSIVE"
    assert evals[0].blocked_by == ["R03:RUN-0002:motor_current"]
    assert not any(f.rule_id in ("R08", "R09", "R10", "R11", "R12") for f in findings)


def test_stop_point_s3_zero_in_window():
    """S3 stop point: No in-window telemetry -> stops at S3, emits R08."""
    req = make_req_row(signal_name="motor_current")
    test = make_test_row(test_id="TST-007", run_id="RUN-0007")
    evals, findings = evaluate_pipeline([req], [test], [], ruleset=RULESET)
    assert len(evals) == 1
    assert evals[0].outcome == "INCONCLUSIVE"
    assert evals[0].blocked_by == ["R08:TST-007"]
    assert any(f.rule_id == "R08" for f in findings)


def test_stop_point_s4_unit_mismatch():
    """S4 stop point: Unit mismatch -> stops at S4, emits R11."""
    req = make_req_row(signal_name="motor_current", unit="A")
    test = make_test_row(test_id="TST-004", run_id="RUN-0004", unit="A")
    tel = [make_tel_row(run_id="RUN-0004", signal_name="motor_current", unit="mA")]
    evals, findings = evaluate_pipeline([req], [test], tel, ruleset=RULESET)
    assert len(evals) == 1
    assert evals[0].outcome == "INCONCLUSIVE"
    assert evals[0].blocked_by == ["R11:TST-004"]
    assert any(f.rule_id == "R11" for f in findings)


def test_stop_point_s5_reaches_conclusive():
    """S5 reaches conclusive evaluation: SATISFIED with no R09."""
    req = make_req_row(operator="<=", threshold_value="85", signal_name="temp")
    test = make_test_row(test_id="TST-01", run_id="RUN-01", status="Pass", actual_result="70.0")
    tel = [make_tel_row(run_id="RUN-01", signal_name="temp", value="70.0")]
    evals, findings = evaluate_pipeline([req], [test], tel, ruleset=RULESET)
    assert evals[0].outcome == "SATISFIED"
    assert evals[0].aggregate == "70.0"
    assert len(evals[0].blocked_by) == 0


def test_stop_point_s6_cross_checks():
    """S6 cross-checks: Contradiction and reported value check."""
    req = make_req_row(operator="<=", threshold_value="85", signal_name="temp")
    test = make_test_row(
        test_id="TST-001", run_id="RUN-0001", status="Pass", actual_result="78.4"
    )
    tel = [make_tel_row(run_id="RUN-0001", signal_name="temp", value="91.0")]
    evals, findings = evaluate_pipeline([req], [test], tel, ruleset=RULESET)
    assert evals[0].outcome == "VIOLATED"
    rule_ids = {f.rule_id for f in findings}
    assert "R09" in rule_ids
    assert "R10" in rule_ids
    assert "R12" in rule_ids


# =============================================================================
# Full Sample Datasets Tests
# =============================================================================
def _run_m2_all(req_ds, test_ds, tel_ds):
    findings = []
    findings.extend(check_r01(req_ds, test_ds, tel_ds, RULESET))
    findings.extend(check_r02(req_ds, test_ds, tel_ds, RULESET))
    findings.extend(check_r03(req_ds, test_ds, tel_ds, RULESET))
    findings.extend(check_r04(req_ds, test_ds, tel_ds, RULESET))
    findings.extend(check_r05(req_ds, test_ds, RULESET))
    findings.extend(check_r06(test_ds, tel_ds, RULESET))
    return findings


def test_fault_dataset_m2_m3():
    """Running M2 + M3 on backend/samples/fault must produce exact expected findings for R07-R12."""
    req_ds = load_csv(FAULT_DIR / "requirements.csv", "requirements")
    test_ds = load_csv(FAULT_DIR / "test_results.csv", "test_results")
    tel_ds = load_csv(FAULT_DIR / "telemetry.csv", "telemetry")

    m2_findings = _run_m2_all(req_ds, test_ds, tel_ds)
    evals, m3_findings = evaluate_pipeline(req_ds, test_ds, tel_ds, m2_findings, ruleset=RULESET)

    # Filter to R07-R12 only
    m3_only = [f for f in m3_findings if f.rule_id in ("R07", "R08", "R09", "R10", "R11", "R12")]

    actual_tuples = [
        (f.rule_id, f.variant, f.entity_key)
        for f in m3_only
    ]

    expected_tuples = [
        ("R07", "NO_TEST", "REQ-PWR-009"),
        ("R07", "NOT_EXECUTED", "REQ-THM-015"),
        ("R08", None, "TST-007"),
        ("R09", None, "TST-001"),
        ("R10", None, "TST-001"),
        ("R10", None, "TST-005"),
        ("R11", "UNIT_MISMATCH", "TST-004"),
        ("R12", None, "TST-001"),
    ]

    assert sorted(actual_tuples) == sorted(expected_tuples)

    # Must NOT produce:
    # R08 to R12 for TST-002, TST-003, TST-006, TST-010
    forbidden_r08_r12 = {"TST-002", "TST-003", "TST-006", "TST-010"}
    for f in m3_only:
        if f.rule_id in ("R08", "R09", "R10", "R11", "R12"):
            assert f.entity_key not in forbidden_r08_r12

    # Must NOT produce R09 for TST-007 or TST-009
    r09_entities = {f.entity_key for f in m3_only if f.rule_id == "R09"}
    assert "TST-007" not in r09_entities
    assert "TST-009" not in r09_entities

    # Must NOT produce R12 for TST-005
    r12_entities = {f.entity_key for f in m3_only if f.rule_id == "R12"}
    assert "TST-005" not in r12_entities


def test_clean_dataset_m2_m3():
    """Running M2 + M3 on backend/samples/clean must produce only R09 for TST-002."""
    req_ds = load_csv(CLEAN_DIR / "requirements.csv", "requirements")
    test_ds = load_csv(CLEAN_DIR / "test_results.csv", "test_results")
    tel_ds = load_csv(CLEAN_DIR / "telemetry.csv", "telemetry")

    m2_findings = _run_m2_all(req_ds, test_ds, tel_ds)
    assert len(m2_findings) == 0

    evals, m3_findings = evaluate_pipeline(req_ds, test_ds, tel_ds, m2_findings, ruleset=RULESET)

    m3_only = [f for f in m3_findings if f.rule_id in ("R07", "R08", "R09", "R10", "R11", "R12")]
    assert len(m3_only) == 1
    assert m3_only[0].rule_id == "R09"
    assert m3_only[0].entity_key == "TST-002"
    assert m3_only[0].finding_class == "OBSERVATION"
