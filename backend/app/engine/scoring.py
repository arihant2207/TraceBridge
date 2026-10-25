"""Scoring, gate, requirement coverage, and finding ID assignment for TraceBridge.

Pure Python functions: no FastAPI, database, or filesystem imports.
Uses decimal.Decimal for all numeric calculations, never float.
"""

from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from typing import Any

from app.engine.models import CheckScore, Evaluation, Finding, RowData, ScoreResult
from app.engine.rules import _extract_rows, _is_valid_decimal_number

# The 11 scored checks per SPEC section 6 (R09 is excluded)
SCORED_RULES = ["R01", "R02", "R03", "R04", "R05", "R06", "R07", "R08", "R10", "R11", "R12"]


def compute_score(
    req_rows: Any,
    test_rows: Any,
    tel_rows: Any,
    findings: list[Finding],
    evaluations: list[Evaluation],
) -> ScoreResult:
    """Compute the 11-check quality score per SPEC section 6.

    Args:
        req_rows: LoadedDataset or list of RowData from requirements.csv
        test_rows: LoadedDataset or list of RowData from test_results.csv
        tel_rows: LoadedDataset or list of RowData from telemetry.csv
        findings: All validation and evaluation findings
        evaluations: Test evaluations from pipeline

    Returns:
        ScoreResult with per-check breakdown and overall Decimal score.
    """
    reqs = _extract_rows(req_rows)
    tests = _extract_rows(test_rows)
    telemetry = _extract_rows(tel_rows)

    # Index findings by rule_id
    findings_by_rule: dict[str, list[Finding]] = {}
    finding_by_id: dict[str, Finding] = {}
    for f in findings:
        findings_by_rule.setdefault(f.rule_id, []).append(f)
        if f.id:
            finding_by_id[f.id] = f

    # Telemetry distinct series (run_id, signal_name) and runs
    tel_series: set[tuple[str, str]] = set()
    tel_runs: set[str] = set()
    for t in telemetry:
        r_id = t.get("run_id", "").strip()
        sig = t.get("signal_name", "").strip()
        if r_id:
            tel_runs.add(r_id)
            if sig:
                tel_series.add((r_id, sig))

    # Test rows map by test_id
    test_by_id: dict[str, RowData] = {}
    for t in tests:
        tid = t.get("test_id", "").strip()
        if tid and tid not in test_by_id:
            test_by_id[tid] = t

    checks: dict[str, CheckScore] = {}

    # -------------------------------------------------------------------------
    # R01-R04: applicable = requirement rows + test rows + telemetry series
    # failing = distinct entities with that rule's finding
    # -------------------------------------------------------------------------
    app_r01_r04 = len(reqs) + len(tests) + len(tel_series)

    for r_id in ("R01", "R02", "R03", "R04"):
        failing_entities: set[tuple[str, Any]] = set()
        for f in findings_by_rule.get(r_id, []):
            if f.source_refs:
                for ref in f.source_refs:
                    if ref.file == "requirements.csv":
                        failing_entities.add(("requirements", ref.row_number))
                    elif ref.file == "test_results.csv":
                        failing_entities.add(("test_results", ref.row_number))
                    elif ref.file == "telemetry.csv":
                        r_name = ref.fields.get("run_id") or (
                            ref.record_id.split(":")[0] if ":" in ref.record_id else ""
                        )
                        s_name = ref.fields.get("signal_name") or (
                            ref.record_id.split(":")[1] if ":" in ref.record_id else ""
                        )
                        failing_entities.add(("telemetry", r_name, s_name))
            else:
                if ":" in f.entity_key:
                    parts = f.entity_key.split(":", 1)
                    failing_entities.add(("telemetry", parts[0], parts[1]))
                else:
                    failing_entities.add(("entity", f.entity_key))

        fail_count = len(failing_entities)
        pass_rate = (
            Decimal(app_r01_r04 - fail_count) / Decimal(app_r01_r04)
            if app_r01_r04 > 0
            else None
        )
        checks[r_id] = CheckScore(
            rule_id=r_id,
            applicable=app_r01_r04,
            failing=fail_count,
            pass_rate=pass_rate,
        )

    # -------------------------------------------------------------------------
    # R05: test rows with non-blank requirement_id
    # -------------------------------------------------------------------------
    app_r05 = len([t for t in tests if t.get("requirement_id", "").strip()])
    r05_failing: set[Any] = set()
    for f in findings_by_rule.get("R05", []):
        for ref in f.source_refs:
            if ref.file == "test_results.csv":
                r05_failing.add(ref.row_number)
        if not f.source_refs:
            r05_failing.add(f.entity_key)
    fail_r05 = len(r05_failing)
    pass_rate_r05 = (
        Decimal(app_r05 - fail_r05) / Decimal(app_r05) if app_r05 > 0 else None
    )
    checks["R05"] = CheckScore(
        rule_id="R05",
        applicable=app_r05,
        failing=fail_r05,
        pass_rate=pass_rate_r05,
    )

    # -------------------------------------------------------------------------
    # R06: distinct telemetry run_ids
    # -------------------------------------------------------------------------
    app_r06 = len(tel_runs)
    r06_failing = {f.entity_key for f in findings_by_rule.get("R06", [])}
    fail_r06 = len(r06_failing)
    pass_rate_r06 = (
        Decimal(app_r06 - fail_r06) / Decimal(app_r06) if app_r06 > 0 else None
    )
    checks["R06"] = CheckScore(
        rule_id="R06",
        applicable=app_r06,
        failing=fail_r06,
        pass_rate=pass_rate_r06,
    )

    # -------------------------------------------------------------------------
    # R07: requirements
    # -------------------------------------------------------------------------
    known_req_ids = {
        r.get("requirement_id", "").strip()
        for r in reqs
        if r.get("requirement_id", "").strip()
    }
    app_r07 = len(known_req_ids)
    r07_failing = {f.entity_key for f in findings_by_rule.get("R07", [])}
    fail_r07 = len(r07_failing)
    pass_rate_r07 = (
        Decimal(app_r07 - fail_r07) / Decimal(app_r07) if app_r07 > 0 else None
    )
    checks["R07"] = CheckScore(
        rule_id="R07",
        applicable=app_r07,
        failing=fail_r07,
        pass_rate=pass_rate_r07,
    )

    # Helper to determine which rule blocked an inconclusive evaluation
    def get_blocking_rule_prefix(blocked_by_ref: str) -> str:
        if ":" in blocked_by_ref:
            return blocked_by_ref.split(":", 1)[0]
        # If it was resolved to a finding_id
        target = finding_by_id.get(blocked_by_ref)
        if target:
            return target.rule_id
        return ""

    # -------------------------------------------------------------------------
    # R08: executed tests passing S1 and S2
    # -------------------------------------------------------------------------
    tests_passing_s1_s2: list[Evaluation] = []
    for e in evaluations:
        if e.outcome in ("SATISFIED", "VIOLATED"):
            tests_passing_s1_s2.append(e)
        elif e.outcome == "INCONCLUSIVE":
            # Passed S1 and S2 if blocked by R08 or R11
            blocking_rules = {get_blocking_rule_prefix(b) for b in e.blocked_by}
            if blocking_rules.intersection({"R08", "R11"}):
                tests_passing_s1_s2.append(e)

    app_r08 = len(tests_passing_s1_s2)
    r08_failing = {f.entity_key for f in findings_by_rule.get("R08", [])}
    fail_r08 = len(r08_failing)
    pass_rate_r08 = (
        Decimal(app_r08 - fail_r08) / Decimal(app_r08) if app_r08 > 0 else None
    )
    checks["R08"] = CheckScore(
        rule_id="R08",
        applicable=app_r08,
        failing=fail_r08,
        pass_rate=pass_rate_r08,
    )

    # -------------------------------------------------------------------------
    # R10: conclusive evaluations
    # -------------------------------------------------------------------------
    conclusive_evals = [e for e in evaluations if e.outcome in ("SATISFIED", "VIOLATED")]
    app_r10 = len(conclusive_evals)
    r10_failing = {f.entity_key for f in findings_by_rule.get("R10", [])}
    fail_r10 = len(r10_failing)
    pass_rate_r10 = (
        Decimal(app_r10 - fail_r10) / Decimal(app_r10) if app_r10 > 0 else None
    )
    checks["R10"] = CheckScore(
        rule_id="R10",
        applicable=app_r10,
        failing=fail_r10,
        pass_rate=pass_rate_r10,
    )

    # -------------------------------------------------------------------------
    # R11: tests passing S1 to S3
    # -------------------------------------------------------------------------
    tests_passing_s1_s3: list[Evaluation] = []
    for e in evaluations:
        if e.outcome in ("SATISFIED", "VIOLATED"):
            tests_passing_s1_s3.append(e)
        elif e.outcome == "INCONCLUSIVE":
            blocking_rules = {get_blocking_rule_prefix(b) for b in e.blocked_by}
            if "R11" in blocking_rules:
                tests_passing_s1_s3.append(e)

    app_r11 = len(tests_passing_s1_s3)
    r11_failing = {f.entity_key for f in findings_by_rule.get("R11", [])}
    fail_r11 = len(r11_failing)
    pass_rate_r11 = (
        Decimal(app_r11 - fail_r11) / Decimal(app_r11) if app_r11 > 0 else None
    )
    checks["R11"] = CheckScore(
        rule_id="R11",
        applicable=app_r11,
        failing=fail_r11,
        pass_rate=pass_rate_r11,
    )

    # -------------------------------------------------------------------------
    # R12: conclusive evaluations with a valid actual_result
    # -------------------------------------------------------------------------
    conclusive_with_valid_actual = [
        e
        for e in conclusive_evals
        if _is_valid_decimal_number(test_by_id.get(e.test_id, {}).get("actual_result", ""))
    ]
    app_r12 = len(conclusive_with_valid_actual)
    r12_failing = {f.entity_key for f in findings_by_rule.get("R12", [])}
    fail_r12 = len(r12_failing)
    pass_rate_r12 = (
        Decimal(app_r12 - fail_r12) / Decimal(app_r12) if app_r12 > 0 else None
    )
    checks["R12"] = CheckScore(
        rule_id="R12",
        applicable=app_r12,
        failing=fail_r12,
        pass_rate=pass_rate_r12,
    )

    # -------------------------------------------------------------------------
    # Overall score = 100 * mean(pass_rate) over applicable checks
    # -------------------------------------------------------------------------
    active_checks = [c for c in checks.values() if c.pass_rate is not None]
    if not active_checks:
        overall_score = Decimal("0.0")
    else:
        mean_rate = sum(c.pass_rate for c in active_checks) / Decimal(len(active_checks))
        overall_score = (mean_rate * Decimal("100")).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        )

    return ScoreResult(
        score=overall_score,
        checks=checks,
        applicable_checks_count=len(active_checks),
    )


def compute_gate(findings: list[Finding], evaluations: list[Evaluation]) -> str:
    """Compute blocking gate per SPEC section 6.

    Gate:
    - BLOCKED_CRITICAL if any non-OBSERVATION Critical finding exists.
    - Else BLOCKED_HIGH if any non-OBSERVATION High finding exists or any evaluation is INCONCLUSIVE.
    - Else NOT_BLOCKED.
    Review status never changes the gate. OBSERVATION never blocks.
    """
    for f in findings:
        if f.finding_class != "OBSERVATION" and f.severity.lower() == "critical":
            return "BLOCKED_CRITICAL"

    has_non_obs_high = any(
        f.finding_class != "OBSERVATION" and f.severity.lower() == "high"
        for f in findings
    )
    has_inconclusive_eval = any(e.outcome == "INCONCLUSIVE" for e in evaluations)

    if has_non_obs_high or has_inconclusive_eval:
        return "BLOCKED_HIGH"

    return "NOT_BLOCKED"


def compute_coverage(
    req_rows: Any,
    test_rows: Any,
    findings: list[Finding],
    evaluations: list[Evaluation],
) -> dict[str, str]:
    """Compute requirement coverage per SPEC locked decision U13.

    Precedence:
    NOT_COVERED, NOT_EXECUTED, then CONTRADICTORY > VIOLATED > INCONCLUSIVE > SATISFIED.
    """
    reqs = _extract_rows(req_rows)
    tests = _extract_rows(test_rows)

    # Index R07 findings by requirement_id
    r07_by_req: dict[str, Finding] = {}
    for f in findings:
        if f.rule_id == "R07":
            r07_by_req[f.entity_key] = f

    # Index R10 findings by test_id
    r10_tests = {f.entity_key for f in findings if f.rule_id == "R10"}

    # Index evaluations by test_id
    eval_by_test_id: dict[str, Evaluation] = {e.test_id: e for e in evaluations}

    # Group test rows by requirement_id
    tests_by_req: dict[str, list[RowData]] = {}
    for t in tests:
        rid = t.get("requirement_id", "").strip()
        if rid:
            tests_by_req.setdefault(rid, []).append(t)

    coverage: dict[str, str] = {}
    seen_req_ids: set[str] = set()

    for r in reqs:
        req_id = r.get("requirement_id", "").strip()
        if not req_id or req_id in seen_req_ids:
            continue
        seen_req_ids.add(req_id)

        # 1. Check R07 findings
        r07 = r07_by_req.get(req_id)
        if r07 is not None:
            if r07.variant == "NO_TEST":
                coverage[req_id] = "NOT_COVERED"
                continue
            elif r07.variant == "NOT_EXECUTED":
                coverage[req_id] = "NOT_EXECUTED"
                continue

        # 2. Executed tests linking to this requirement
        linked_tests = tests_by_req.get(req_id, [])
        executed_tests = [
            t for t in linked_tests if t.get("status", "").strip() in ("Pass", "Fail")
        ]

        if not executed_tests:
            # Fallback if no executed tests and no R07
            coverage[req_id] = "NOT_COVERED"
            continue

        # Map each executed test to its coverage outcome
        test_outcomes: list[str] = []
        for t in executed_tests:
            tid = t.get("test_id", "").strip()
            if tid in r10_tests:
                test_outcomes.append("CONTRADICTORY")
            else:
                ev = eval_by_test_id.get(tid)
                if ev is not None:
                    test_outcomes.append(ev.outcome)
                else:
                    test_outcomes.append("INCONCLUSIVE")

        # Precedence: CONTRADICTORY > VIOLATED > INCONCLUSIVE > SATISFIED
        if "CONTRADICTORY" in test_outcomes:
            coverage[req_id] = "CONTRADICTORY"
        elif "VIOLATED" in test_outcomes:
            coverage[req_id] = "VIOLATED"
        elif "INCONCLUSIVE" in test_outcomes:
            coverage[req_id] = "INCONCLUSIVE"
        elif "SATISFIED" in test_outcomes:
            coverage[req_id] = "SATISFIED"
        else:
            coverage[req_id] = "INCONCLUSIVE"

    return coverage


def assign_finding_ids(
    findings: list[Finding],
    evaluations: list[Evaluation],
    analysis_id: str,
) -> tuple[list[Finding], list[Evaluation]]:
    """Sort findings by (rule_id, entity_key), assign IDs, and resolve blocked_by references.

    Args:
        findings: Findings list to sort and number
        evaluations: Evaluation list with temporary blocked_by references
        analysis_id: Prefix for finding IDs (<analysis_id>-F0001...)

    Returns:
        (ordered_numbered_findings, resolved_evaluations)
    """
    # Deterministic sort per SPEC section 3
    sorted_findings = sorted(findings, key=lambda f: (f.rule_id, f.entity_key, f.variant or ""))

    # Assign IDs
    finding_map: dict[str, str] = {}
    for i, f in enumerate(sorted_findings, start=1):
        f.id = f"{analysis_id}-F{i:04d}"
        finding_map[f"{f.rule_id}:{f.entity_key}"] = f.id

    # Resolve temporary references in evaluation blocked_by
    for e in evaluations:
        resolved_refs: list[str] = []
        for ref in e.blocked_by:
            resolved_refs.append(finding_map.get(ref, ref))
        e.blocked_by = resolved_refs

    return sorted_findings, evaluations


def compute_findings_digest(findings: list[Finding]) -> str:
    """Compute SHA-256 digest of canonical findings JSON.

    Excludes IDs, timestamps, and reviews per SPEC section 3.
    """
    sorted_findings = sorted(findings, key=lambda f: (f.rule_id, f.entity_key, f.variant or ""))

    digest_records: list[dict[str, Any]] = []
    for f in sorted_findings:
        digest_records.append(
            {
                "rule_id": f.rule_id,
                "variant": f.variant,
                "severity": f.severity,
                "finding_class": f.finding_class,
                "entity_key": f.entity_key,
                "description": f.description,
                "expected": f.expected,
                "actual": f.actual,
                "source_refs": [
                    {
                        "file": r.file,
                        "row_number": r.row_number,
                        "record_id": r.record_id,
                        "fields": r.fields,
                    }
                    for r in f.source_refs
                ],
                "truncated": f.truncated,
            }
        )

    canonical_json = json.dumps(digest_records, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
