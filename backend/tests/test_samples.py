"""Golden dataset tests and M4 scoring/gate/coverage/digest acceptance tests."""

from decimal import Decimal
import json
from pathlib import Path
import pytest

from app.engine.evaluate import evaluate_pipeline
from app.engine.models import Evaluation, Finding, RowData, SourceRef
from app.engine.rules import run_rules_m2
from app.engine.scoring import (
    assign_finding_ids,
    compute_coverage,
    compute_findings_digest,
    compute_gate,
    compute_score,
)
from app.ingestion.loader import load_dataset

RULESET_PATH = Path(__file__).resolve().parent.parent / "app" / "engine" / "ruleset.json"
RULESET = json.loads(RULESET_PATH.read_text(encoding="utf-8"))

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"
CLEAN_DIR = SAMPLES_DIR / "clean"
FAULT_DIR = SAMPLES_DIR / "fault"


def _load(path: Path, kind: str):
    return load_dataset(path.read_bytes(), path.name, kind)


# =============================================================================
# Clean Dataset Acceptance Test
# =============================================================================
def test_clean_dataset_end_to_end():
    """Clean: exactly 1 finding (R09 TST-002), score 100.0, gate NOT_BLOCKED, coverage per SPEC."""
    req_ds = _load(CLEAN_DIR / "requirements.csv", "requirements")
    test_ds = _load(CLEAN_DIR / "test_results.csv", "test_results")
    tel_ds = _load(CLEAN_DIR / "telemetry.csv", "telemetry")

    m2_findings = run_rules_m2(req_ds, test_ds, tel_ds, RULESET)
    assert len(m2_findings) == 0

    evals, m3_findings = evaluate_pipeline(req_ds, test_ds, tel_ds, m2_findings, ruleset=RULESET)
    all_findings = m2_findings + m3_findings

    findings, evals = assign_finding_ids(all_findings, evals, "clean-analysis")

    # Score
    score_res = compute_score(req_ds, test_ds, tel_ds, findings, evals)
    assert score_res.score == Decimal("100.0")

    # Gate
    gate = compute_gate(findings, evals)
    assert gate == "NOT_BLOCKED"

    # Coverage
    coverage = compute_coverage(req_ds, test_ds, findings, evals)
    expected_cov = {
        "REQ-THM-011": "SATISFIED",
        "REQ-ELC-004": "VIOLATED",
        "REQ-PWR-002": "SATISFIED",
    }
    assert coverage == expected_cov

    # Exactly 1 finding: R09 on TST-002
    assert len(findings) == 1
    assert findings[0].id == "clean-analysis-F0001"
    assert findings[0].rule_id == "R09"
    assert findings[0].entity_key == "TST-002"
    assert findings[0].finding_class == "OBSERVATION"


# =============================================================================
# Fault Dataset Acceptance Test
# =============================================================================
def test_fault_dataset_end_to_end():
    """Fault: compare against expected_fault.json exactly."""
    req_ds = _load(FAULT_DIR / "requirements.csv", "requirements")
    test_ds = _load(FAULT_DIR / "test_results.csv", "test_results")
    tel_ds = _load(FAULT_DIR / "telemetry.csv", "telemetry")

    expected_fault = json.loads((SAMPLES_DIR / "expected_fault.json").read_text(encoding="utf-8"))

    m2_findings = run_rules_m2(req_ds, test_ds, tel_ds, RULESET)
    evals, m3_findings = evaluate_pipeline(req_ds, test_ds, tel_ds, m2_findings, ruleset=RULESET)
    all_findings = m2_findings + m3_findings

    analysis_id = "fault-analysis"
    findings, evals = assign_finding_ids(all_findings, evals, analysis_id)

    # 1. Total findings count and breakdown by severity
    assert len(findings) == expected_fault["finding_count"]
    by_sev = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in findings:
        by_sev[f.severity.lower()] += 1
    assert by_sev == expected_fault["by_severity"]

    # 2. Gate
    gate = compute_gate(findings, evals)
    assert gate == expected_fault["gate"]

    # 3. Score must equal 73.3
    score_res = compute_score(req_ds, test_ds, tel_ds, findings, evals)
    assert str(score_res.score) == expected_fault["score"]
    assert score_res.score == Decimal("73.3")

    # 4. Coverage must match expected_fault.json
    coverage = compute_coverage(req_ds, test_ds, findings, evals)
    assert coverage == expected_fault["coverage"]

    # 5. Exact match of each expected finding
    # rule_id, variant, entity_key, severity, finding_class match exactly
    # expected source_refs must be a SUBSET of actual refs (file, row_number, record_id)
    actual_by_key = {(f.rule_id, f.entity_key): f for f in findings}
    assert len(actual_by_key) == len(expected_fault["findings"])

    for exp_f in expected_fault["findings"]:
        key = (exp_f["rule_id"], exp_f["entity_key"])
        assert key in actual_by_key, f"Missing finding for key {key}"
        act_f = actual_by_key[key]

        assert act_f.variant == exp_f["variant"]
        assert act_f.severity.lower() == exp_f["severity"].lower()
        assert act_f.finding_class == exp_f["finding_class"]

        # Check source_refs subset
        act_refs_set = {
            (r.file, r.row_number, r.record_id)
            for r in act_f.source_refs
        }
        for exp_ref in exp_f.get("source_refs", []):
            expected_tuple = (exp_ref["file"], exp_ref["row_number"], exp_ref["record_id"])
            assert expected_tuple in act_refs_set, (
                f"Expected source ref {expected_tuple} not in actual refs for {key}"
            )

    # 6. Must not produce rules / entities
    for mnp in expected_fault.get("must_not_produce", []):
        forbidden_rules = set(mnp["rules"])
        forbidden_entities = set(mnp["entities"])
        for f in findings:
            if f.rule_id in forbidden_rules:
                assert f.entity_key not in forbidden_entities, (
                    f"Forbidden finding produced: {f.rule_id} on {f.entity_key}"
                )

    # 7. Check blocked_by references resolved to real finding IDs
    finding_ids = {f.id for f in findings}
    for e in evals:
        for b in e.blocked_by:
            assert b in finding_ids, f"Blocked_by reference {b!r} not resolved to a real finding ID"


# =============================================================================
# Determinism Test
# =============================================================================
def test_determinism_across_runs():
    """Two runs on the same inputs give the same findings_digest and finding IDs."""
    req_ds = _load(FAULT_DIR / "requirements.csv", "requirements")
    test_ds = _load(FAULT_DIR / "test_results.csv", "test_results")
    tel_ds = _load(FAULT_DIR / "telemetry.csv", "telemetry")

    # Run 1
    m2_1 = run_rules_m2(req_ds, test_ds, tel_ds, RULESET)
    evals_1, m3_1 = evaluate_pipeline(req_ds, test_ds, tel_ds, m2_1, ruleset=RULESET)
    findings_1, evals_1 = assign_finding_ids(m2_1 + m3_1, evals_1, "det-analysis")
    digest_1 = compute_findings_digest(findings_1)

    # Run 2
    m2_2 = run_rules_m2(req_ds, test_ds, tel_ds, RULESET)
    evals_2, m3_2 = evaluate_pipeline(req_ds, test_ds, tel_ds, m2_2, ruleset=RULESET)
    findings_2, evals_2 = assign_finding_ids(m2_2 + m3_2, evals_2, "det-analysis")
    digest_2 = compute_findings_digest(findings_2)

    assert digest_1 == digest_2
    assert [f.id for f in findings_1] == [f.id for f in findings_2]
    assert [e.blocked_by for e in evals_1] == [e.blocked_by for e in evals_2]


# =============================================================================
# Unit Tests for Scoring Edge Cases
# =============================================================================
def test_score_na_check_excluded_from_mean():
    """N/A check (applicable == 0) is excluded from the mean score denominator."""
    # Create dataset with no telemetry at all
    reqs = [
        RowData(
            row_number=1,
            requirement_id="REQ-01",
            signal_name="temp",
            operator="<=",
            threshold_value="80",
            unit="°C",
        )
    ]
    tests = [
        RowData(
            row_number=1,
            test_id="TST-01",
            requirement_id="REQ-01",
            run_id="",
            status="Not Run",
            started_at="",
            completed_at="",
            actual_result="",
            unit="°C",
        )
    ]
    # No telemetry rows
    telemetry = []

    findings = [
        Finding(
            rule_id="R07",
            variant="NOT_EXECUTED",
            severity="high",
            finding_class="MISSING_EVIDENCE",
            entity_key="REQ-01",
            description="Not executed",
        )
    ]
    evals = []

    res = compute_score(reqs, tests, telemetry, findings, evals)
    # R06 (telemetry run_ids) has applicable == 0 -> N/A
    assert res.checks["R06"].applicable == 0
    assert res.checks["R06"].pass_rate is None

    # R08, R10, R11, R12 also have applicable == 0
    assert res.checks["R08"].applicable == 0
    assert res.checks["R10"].applicable == 0

    # Ensure applicable_checks_count < 11 and only applicable checks averaged
    assert res.applicable_checks_count < 11
    applicable_checks = [c for c in res.checks.values() if c.pass_rate is not None]
    expected_mean = sum(c.pass_rate for c in applicable_checks) / Decimal(len(applicable_checks))
    expected_score = (expected_mean * Decimal("100")).quantize(Decimal("0.1"))
    assert res.score == expected_score


def test_score_round_half_up():
    """Verify rounding half-up using Decimal (e.g. 73.35 -> 73.4)."""
    # 73.35 should round to 73.4 with Decimal ROUND_HALF_UP
    val = Decimal("73.35").quantize(Decimal("0.1"), rounding="ROUND_HALF_UP")
    assert val == Decimal("73.4")

    val_down = Decimal("73.34").quantize(Decimal("0.1"), rounding="ROUND_HALF_UP")
    assert val_down == Decimal("73.3")


# =============================================================================
# Unit Tests for Gate Logic
# =============================================================================
def test_gate_observation_never_blocks():
    """OBSERVATION findings never block the gate."""
    finding = Finding(
        rule_id="R09",
        severity="critical",  # even if critical!
        finding_class="OBSERVATION",
        entity_key="TST-01",
        description="Observation only",
    )
    evals = [
        Evaluation(test_id="TST-01", outcome="SATISFIED")
    ]
    gate = compute_gate([finding], evals)
    assert gate == "NOT_BLOCKED"


def test_gate_inconclusive_evaluation_blocks_without_high_finding():
    """An INCONCLUSIVE evaluation blocks as BLOCKED_HIGH even without any High finding."""
    # Findings only have Medium severity
    finding = Finding(
        rule_id="R04",
        severity="medium",
        finding_class="VALIDATION_FAILURE",
        entity_key="TST-01",
        description="Timestamp format",
    )
    evals = [
        Evaluation(test_id="TST-01", outcome="INCONCLUSIVE", blocked_by=["F0001"])
    ]
    gate = compute_gate([finding], evals)
    assert gate == "BLOCKED_HIGH"


def test_gate_critical_validation_failure_blocks_critical():
    """A non-OBSERVATION Critical finding triggers BLOCKED_CRITICAL."""
    finding = Finding(
        rule_id="R10",
        severity="critical",
        finding_class="VALIDATION_FAILURE",
        entity_key="TST-01",
        description="Contradiction",
    )
    evals = [
        Evaluation(test_id="TST-01", outcome="VIOLATED")
    ]
    gate = compute_gate([finding], evals)
    assert gate == "BLOCKED_CRITICAL"


# =============================================================================
# Unit Tests for Coverage Precedence
# =============================================================================
def test_coverage_precedence():
    """Precedence: CONTRADICTORY > VIOLATED > INCONCLUSIVE > SATISFIED."""
    req_rows = [
        RowData(row_number=1, requirement_id="REQ-01"),
        RowData(row_number=2, requirement_id="REQ-02"),
        RowData(row_number=3, requirement_id="REQ-03"),
    ]
    test_rows = [
        # REQ-01 has one CONTRADICTORY and one SATISFIED -> CONTRADICTORY
        RowData(row_number=1, test_id="T1", requirement_id="REQ-01", status="Pass"),
        RowData(row_number=2, test_id="T2", requirement_id="REQ-01", status="Pass"),
        # REQ-02 has one VIOLATED and one SATISFIED -> VIOLATED
        RowData(row_number=3, test_id="T3", requirement_id="REQ-02", status="Pass"),
        RowData(row_number=4, test_id="T4", requirement_id="REQ-02", status="Pass"),
        # REQ-03 has one INCONCLUSIVE and one SATISFIED -> INCONCLUSIVE
        RowData(row_number=5, test_id="T5", requirement_id="REQ-03", status="Pass"),
        RowData(row_number=6, test_id="T6", requirement_id="REQ-03", status="Pass"),
    ]
    evals = [
        Evaluation(test_id="T1", outcome="SATISFIED"),
        Evaluation(test_id="T2", outcome="VIOLATED"),
        Evaluation(test_id="T3", outcome="VIOLATED"),
        Evaluation(test_id="T4", outcome="SATISFIED"),
        Evaluation(test_id="T5", outcome="INCONCLUSIVE"),
        Evaluation(test_id="T6", outcome="SATISFIED"),
    ]
    # T1 has an R10 finding -> CONTRADICTORY
    findings = [
        Finding(
            rule_id="R10",
            severity="critical",
            finding_class="VALIDATION_FAILURE",
            entity_key="T1",
            description="Contradiction",
        )
    ]

    cov = compute_coverage(req_rows, test_rows, findings, evals)
    assert cov["REQ-01"] == "CONTRADICTORY"
    assert cov["REQ-02"] == "VIOLATED"
    assert cov["REQ-03"] == "INCONCLUSIVE"
