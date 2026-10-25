"""Evaluation pipeline S1 through S6 for TraceBridge.

Pure Python functions: no FastAPI, database, or filesystem imports.
Uses decimal.Decimal for all numeric comparisons, never float.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from app.engine.models import Evaluation, Finding, RowData, SourceRef
from app.engine.rules import (
    UNIT_REGISTRY,
    _extract_rows,
    _get_rule_meta,
    _is_valid_decimal_number,
    _parse_iso_timestamp,
    check_r07,
    check_r11_unit,
    find_extremum,
)


def evaluate_pipeline(
    req_rows: Any,
    test_rows: Any,
    tel_rows: Any,
    m2_findings: list[Finding] | None = None,
    ruleset: dict[str, Any] | None = None,
) -> tuple[list[Evaluation], list[Finding]]:
    """Execute evaluation pipeline S1 to S6 for each executed test (status Pass or Fail).

    Args:
        req_rows: LoadedDataset or list of RowData from requirements.csv
        test_rows: LoadedDataset or list of RowData from test_results.csv
        tel_rows: LoadedDataset or list of RowData from telemetry.csv
        m2_findings: Validation findings from rules R01 through R06
        ruleset: Ruleset dictionary loaded from ruleset.json

    Returns:
        (evaluations, new_findings) where new_findings are from rules R07 to R12.
    """
    if m2_findings is None:
        m2_findings = []
    if ruleset is None:
        ruleset = {}

    reqs = _extract_rows(req_rows)
    tests = _extract_rows(test_rows)
    telemetry = _extract_rows(tel_rows)

    # 1. Evaluate Rule R07 across requirements
    r07_findings = check_r07(reqs, tests, ruleset)
    pipeline_findings: list[Finding] = list(r07_findings)

    # Index requirements by requirement_id
    reqs_by_id: dict[str, RowData] = {}
    for r in reqs:
        rid = r.get("requirement_id", "").strip()
        if rid and rid not in reqs_by_id:
            reqs_by_id[rid] = r

    # Group telemetry by (run_id, signal_name)
    tel_by_series: dict[tuple[str, str], list[RowData]] = {}
    tel_by_run: dict[str, list[RowData]] = {}
    for t in telemetry:
        run_id = t.get("run_id", "").strip()
        sig = t.get("signal_name", "").strip()
        if run_id:
            tel_by_run.setdefault(run_id, []).append(t)
            if sig:
                tel_by_series.setdefault((run_id, sig), []).append(t)

    # Index M2 findings by entity_key and by source row
    m2_by_test_row: dict[int, list[Finding]] = {}
    m2_by_req_row: dict[int, list[Finding]] = {}
    m2_by_tel_row: dict[int, list[Finding]] = {}
    m2_by_entity: dict[str, list[Finding]] = {}

    for f in m2_findings:
        m2_by_entity.setdefault(f.entity_key, []).append(f)
        for ref in f.source_refs:
            if ref.file == "test_results.csv":
                m2_by_test_row.setdefault(ref.row_number, []).append(f)
            elif ref.file == "requirements.csv":
                m2_by_req_row.setdefault(ref.row_number, []).append(f)
            elif ref.file == "telemetry.csv":
                m2_by_tel_row.setdefault(ref.row_number, []).append(f)

    evaluations: list[Evaluation] = []

    # Process tests in order per SPEC section 5
    for test_row in tests:
        status = test_row.get("status", "").strip()
        test_id = test_row.get("test_id", "").strip()

        # Not Run tests have no evaluation.
        # Only tests with status 'Pass' or 'Fail' are evaluated.
        if status not in ("Pass", "Fail"):
            continue

        # ---------------------------------------------------------------------
        # S1: Test row and requirement row preconditions
        # ---------------------------------------------------------------------
        s1_blocked_by: list[str] = []

        # Check if test row has R01, R02, R03, or R04 finding
        test_findings = m2_by_test_row.get(test_row.row_number, [])
        for f in test_findings:
            if f.rule_id in ("R01", "R02", "R03", "R04"):
                s1_blocked_by.append(f"{f.rule_id}:{f.entity_key}")

        # If test_id matches an R02 finding directly
        if test_id:
            for f in m2_by_entity.get(test_id, []):
                if f.rule_id == "R02":
                    s1_blocked_by.append(f"{f.rule_id}:{f.entity_key}")

        # Check requirement existence (no R05)
        for f in test_findings:
            if f.rule_id == "R05":
                s1_blocked_by.append(f"{f.rule_id}:{f.entity_key}")

        req_id = test_row.get("requirement_id", "").strip()
        req_row = reqs_by_id.get(req_id)

        # Check requirement row defects (R01, R02, R03)
        if req_row is not None:
            for f in m2_by_req_row.get(req_row.row_number, []):
                if f.rule_id in ("R01", "R02", "R03"):
                    s1_blocked_by.append(f"{f.rule_id}:{f.entity_key}")
            if req_id:
                for f in m2_by_entity.get(req_id, []):
                    if f.rule_id in ("R01", "R02", "R03"):
                        s1_blocked_by.append(f"{f.rule_id}:{f.entity_key}")
        elif not req_id:
            # Missing requirement reference is R01
            pass
        else:
            # If requirement is missing from reqs, R05 was flagged above
            pass

        if s1_blocked_by:
            deduped = sorted(list(dict.fromkeys(s1_blocked_by)))
            evaluations.append(
                Evaluation(
                    test_id=test_id,
                    requirement_id=req_id,
                    outcome="INCONCLUSIVE",
                    aggregate=None,
                    n_in_window=0,
                    n_out_of_window=0,
                    blocked_by=deduped,
                )
            )
            continue

        # If requirement row was not found despite no R05 finding (defensive)
        if req_row is None:
            evaluations.append(
                Evaluation(
                    test_id=test_id,
                    requirement_id=req_id,
                    outcome="INCONCLUSIVE",
                    aggregate=None,
                    n_in_window=0,
                    n_out_of_window=0,
                    blocked_by=[f"R05:{test_id}"],
                )
            )
            continue

        # ---------------------------------------------------------------------
        # S2: Telemetry preconditions
        # ---------------------------------------------------------------------
        run_id = test_row.get("run_id", "").strip()
        signal_name = req_row.get("signal_name", "").strip()
        selected_tel = tel_by_series.get((run_id, signal_name), [])

        s2_blocked_by: list[str] = []
        series_key = f"{run_id}:{signal_name}"
        for f in m2_by_entity.get(series_key, []):
            if f.rule_id in ("R01", "R03", "R04"):
                s2_blocked_by.append(f"{f.rule_id}:{f.entity_key}")

        for r in selected_tel:
            for f in m2_by_tel_row.get(r.row_number, []):
                if f.rule_id in ("R01", "R03", "R04"):
                    s2_blocked_by.append(f"{f.rule_id}:{f.entity_key}")

        if s2_blocked_by:
            deduped = sorted(list(dict.fromkeys(s2_blocked_by)))
            evaluations.append(
                Evaluation(
                    test_id=test_id,
                    requirement_id=req_id,
                    outcome="INCONCLUSIVE",
                    aggregate=None,
                    n_in_window=0,
                    n_out_of_window=0,
                    blocked_by=deduped,
                )
            )
            continue

        # ---------------------------------------------------------------------
        # S3: At least one in-window telemetry row, else R08
        # ---------------------------------------------------------------------
        start_dt = _parse_iso_timestamp(test_row.get("started_at", "").strip())
        complete_dt = _parse_iso_timestamp(test_row.get("completed_at", "").strip())

        in_window_rows: list[RowData] = []
        for r in selected_tel:
            ts = _parse_iso_timestamp(r.get("timestamp", "").strip())
            if ts and start_dt and complete_dt and start_dt <= ts <= complete_dt:
                in_window_rows.append(r)

        n_in_window = len(in_window_rows)
        n_out_of_window = len(selected_tel) - n_in_window

        if n_in_window == 0:
            r08_sev, r08_cls = _get_rule_meta(ruleset, "R08")
            other_run_rows = [
                r
                for r in tel_by_run.get(run_id, [])
                if r.get("signal_name", "").strip() != signal_name
            ]
            r08_refs = [
                SourceRef(
                    file="test_results.csv",
                    row_number=test_row.row_number,
                    record_id=test_id,
                    fields=dict(test_row),
                ),
                SourceRef(
                    file="requirements.csv",
                    row_number=req_row.row_number,
                    record_id=req_id,
                    fields=dict(req_row),
                ),
            ]
            for r in other_run_rows[:20]:
                r08_refs.append(
                    SourceRef(
                        file="telemetry.csv",
                        row_number=r.row_number,
                        record_id=f"{run_id}:{r.get('signal_name', '')}",
                        fields=dict(r),
                    )
                )

            r08_finding = Finding(
                rule_id="R08",
                variant=None,
                severity=r08_sev,
                finding_class=r08_cls,
                entity_key=test_id,
                description=(
                    f"Executed test {test_id} has zero in-window telemetry rows "
                    f"for signal {signal_name!r} ({n_out_of_window} out of window)"
                ),
                expected=(
                    f"At least one telemetry sample for signal {signal_name!r} "
                    f"in window [{test_row.get('started_at')}, {test_row.get('completed_at')}]"
                ),
                actual=f"0 in-window samples ({n_out_of_window} out of window)",
                source_refs=r08_refs,
            )
            pipeline_findings.append(r08_finding)
            evaluations.append(
                Evaluation(
                    test_id=test_id,
                    requirement_id=req_id,
                    outcome="INCONCLUSIVE",
                    aggregate=None,
                    n_in_window=0,
                    n_out_of_window=n_out_of_window,
                    blocked_by=[f"R08:{test_id}"],
                )
            )
            continue

        # ---------------------------------------------------------------------
        # S4: Unit check, else R11
        # ---------------------------------------------------------------------
        req_unit = req_row.get("unit", "").strip()
        test_unit = test_row.get("unit", "").strip()
        tel_units = [r.get("unit", "").strip() for r in in_window_rows]

        r11_variant = check_r11_unit(req_unit, test_unit, tel_units)
        if r11_variant is not None:
            r11_sev, r11_cls = _get_rule_meta(ruleset, "R11")
            r11_refs = [
                SourceRef(
                    file="test_results.csv",
                    row_number=test_row.row_number,
                    record_id=test_id,
                    fields=dict(test_row),
                )
            ]
            for r in in_window_rows[:20]:
                r11_refs.append(
                    SourceRef(
                        file="telemetry.csv",
                        row_number=r.row_number,
                        record_id=f"{run_id}:{r.get('signal_name', '')}",
                        fields=dict(r),
                    )
                )

            r11_finding = Finding(
                rule_id="R11",
                variant=r11_variant,
                severity=r11_sev,
                finding_class=r11_cls,
                entity_key=test_id,
                description=(
                    f"Invalid unit combination ({r11_variant}) for test {test_id}: "
                    f"req={req_unit}, test={test_unit}, telemetry={list(dict.fromkeys(tel_units))}"
                ),
                expected=f"All units in registry and exactly equal ({req_unit})",
                actual=f"req={req_unit}, test={test_unit}, telemetry={list(dict.fromkeys(tel_units))}",
                source_refs=r11_refs,
            )
            pipeline_findings.append(r11_finding)
            evaluations.append(
                Evaluation(
                    test_id=test_id,
                    requirement_id=req_id,
                    outcome="INCONCLUSIVE",
                    aggregate=None,
                    n_in_window=n_in_window,
                    n_out_of_window=n_out_of_window,
                    blocked_by=[f"R11:{test_id}"],
                )
            )
            continue

        # ---------------------------------------------------------------------
        # S5: Aggregate and compare -> SATISFIED or VIOLATED (R09 if violated)
        # ---------------------------------------------------------------------
        operator = req_row.get("operator", "").strip()
        threshold_val = Decimal(req_row.get("threshold_value", "").strip())
        aggregate_val, extremum_row = find_extremum(in_window_rows, operator)

        is_satisfied: bool = False
        if operator == "<":
            is_satisfied = aggregate_val < threshold_val
        elif operator == "<=":
            is_satisfied = aggregate_val <= threshold_val
        elif operator == ">":
            is_satisfied = aggregate_val > threshold_val
        elif operator == ">=":
            is_satisfied = aggregate_val >= threshold_val

        outcome = "SATISFIED" if is_satisfied else "VIOLATED"

        extremum_ref = SourceRef(
            file="telemetry.csv",
            row_number=extremum_row.row_number,
            record_id=f"{run_id}:{extremum_row.get('signal_name', '')}",
            fields=dict(extremum_row),
        )
        test_ref = SourceRef(
            file="test_results.csv",
            row_number=test_row.row_number,
            record_id=test_id,
            fields=dict(test_row),
        )

        if outcome == "VIOLATED":
            r09_sev, r09_cls = _get_rule_meta(ruleset, "R09")
            agg_name = "max" if operator in ("<", "<=") else "min"
            r09_finding = Finding(
                rule_id="R09",
                variant=None,
                severity=r09_sev,
                finding_class=r09_cls,
                entity_key=test_id,
                description=(
                    f"Threshold violation for test {test_id}: {agg_name} {aggregate_val} {req_unit} "
                    f"violates requirement {req_id} ({operator} {threshold_val} {req_unit})"
                ),
                expected=f"{operator} {threshold_val} {req_unit}",
                actual=f"{agg_name} = {aggregate_val} {req_unit} (n={n_in_window})",
                source_refs=[test_ref, extremum_ref],
            )
            pipeline_findings.append(r09_finding)

        # ---------------------------------------------------------------------
        # S6: Cross-checks R10 and R12
        # ---------------------------------------------------------------------
        # R10: Status vs measurement contradiction
        if (status == "Pass" and outcome == "VIOLATED") or (
            status == "Fail" and outcome == "SATISFIED"
        ):
            r10_sev, r10_cls = _get_rule_meta(ruleset, "R10")
            r10_finding = Finding(
                rule_id="R10",
                variant=None,
                severity=r10_sev,
                finding_class=r10_cls,
                entity_key=test_id,
                description=(
                    f"Test status {status} contradicts measurement outcome {outcome} "
                    f"(aggregate={aggregate_val})"
                ),
                expected=f"Test status consistent with measurement outcome {outcome}",
                actual=f"status={status}, outcome={outcome}, aggregate={aggregate_val}",
                source_refs=[test_ref, extremum_ref],
            )
            pipeline_findings.append(r10_finding)

        # R12: Reported value inconsistent with source
        actual_result_str = test_row.get("actual_result", "").strip()
        if _is_valid_decimal_number(actual_result_str):
            reported_val = Decimal(actual_result_str)
            tol_str = str(ruleset.get("R12", {}).get("tolerance", "0.05"))
            tolerance = Decimal(tol_str)
            diff = abs(reported_val - aggregate_val)
            if diff > tolerance:  # strictly greater
                r12_sev, r12_cls = _get_rule_meta(ruleset, "R12")
                r12_finding = Finding(
                    rule_id="R12",
                    variant=None,
                    severity=r12_sev,
                    finding_class=r12_cls,
                    entity_key=test_id,
                    description=(
                        f"Reported value {reported_val} differs from aggregate {aggregate_val} "
                        f"by {diff} (tolerance {tolerance})"
                    ),
                    expected=f"|actual_result - aggregate| <= {tolerance}",
                    actual=f"actual_result={reported_val}, aggregate={aggregate_val}, diff={diff}",
                    source_refs=[test_ref, extremum_ref],
                )
                pipeline_findings.append(r12_finding)

        evaluations.append(
            Evaluation(
                test_id=test_id,
                requirement_id=req_id,
                outcome=outcome,
                aggregate=str(aggregate_val),
                n_in_window=n_in_window,
                n_out_of_window=n_out_of_window,
                blocked_by=[],
            )
        )

    # Sort findings deterministically by (rule_id, entity_key)
    pipeline_findings.sort(key=lambda f: (f.rule_id, f.entity_key))

    return evaluations, pipeline_findings
