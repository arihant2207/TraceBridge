"""Deterministic validation rules R01 through R06 for TraceBridge.

All rule logic is pure Python functions with no FastAPI, database, or filesystem imports.
Uses decimal.Decimal for numeric values, never float.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Iterable

from app.engine.models import Finding, LoadedDataset, RowData, SourceRef

# Precompiled regular expressions per SPEC section 3
NUMBER_REGEX = re.compile(r"^[+-]?\d+(\.\d+)?$")
TIMESTAMP_REGEX = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$"
)

ALLOWED_OPERATORS = {"<", "<=", ">", ">="}
ALLOWED_STATUSES = {"Pass", "Fail", "Not Run"}


def _extract_rows(dataset_or_rows: Any) -> list[RowData]:
    """Extract RowData list from LoadedDataset or raw row list."""
    if hasattr(dataset_or_rows, "rows"):
        return dataset_or_rows.rows
    if isinstance(dataset_or_rows, list):
        return dataset_or_rows
    return []


def _get_rule_meta(ruleset: dict[str, Any], rule_id: str) -> tuple[str, str]:
    """Retrieve severity and finding_class for a rule from ruleset dictionary."""
    cfg = ruleset.get(rule_id, {})
    severity = cfg.get("severity", "medium")
    finding_class = cfg.get("finding_class", "VALIDATION_FAILURE")
    return severity, finding_class


def _is_valid_iso_timestamp(ts: str) -> bool:
    """Validate ISO 8601 timestamp with offset and valid calendar date."""
    if not TIMESTAMP_REGEX.match(ts):
        return False
    try:
        # datetime.fromisoformat parses ISO 8601 with Z or +/-HH:MM
        datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _parse_iso_timestamp(ts: str) -> datetime | None:
    """Parse ISO 8601 timestamp string into datetime."""
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_valid_decimal_number(val: str) -> bool:
    r"""Validate number format per SPEC: ^[+-]?\d+(\.\d+)?$ and Decimal-safe."""
    if not NUMBER_REGEX.match(val):
        return False
    try:
        Decimal(val)
        return True
    except InvalidOperation:
        return False


# =============================================================================
# R01: Missing/unusable required field
# =============================================================================
def check_r01(
    req_rows: Any,
    test_rows: Any,
    tel_rows: Any,
    ruleset: dict[str, Any],
) -> list[Finding]:
    """R01 Missing/unusable required field | High | MISSING_EVIDENCE.

    Any row of any file: a required value is empty after trim (reason MISSING)
    or status/operator is outside the allowed set (INVALID_ENUM).
    One finding per record (telemetry grouped per series).
    """
    severity, finding_class = _get_rule_meta(ruleset, "R01")
    findings: list[Finding] = []

    # 1. requirements.csv
    for r in _extract_rows(req_rows):
        req_id = r.get("requirement_id", "").strip()
        signal_name = r.get("signal_name", "").strip()
        operator = r.get("operator", "").strip()
        threshold_value = r.get("threshold_value", "").strip()
        unit = r.get("unit", "").strip()

        rec_id = req_id if req_id else f"requirements.csv#{r.row_number}"
        defects: list[str] = []

        if not req_id:
            defects.append("Missing requirement_id (MISSING)")
        if not signal_name:
            defects.append("Missing signal_name (MISSING)")
        if not operator:
            defects.append("Missing operator (MISSING)")
        elif operator not in ALLOWED_OPERATORS:
            defects.append(f"Invalid operator {operator!r} (INVALID_ENUM)")
        if not threshold_value:
            defects.append("Missing threshold_value (MISSING)")
        if not unit:
            defects.append("Missing unit (MISSING)")

        if defects:
            findings.append(
                Finding(
                    rule_id="R01",
                    variant=None,
                    severity=severity,
                    finding_class=finding_class,
                    entity_key=rec_id,
                    description=f"Requirement row {r.row_number} has defects: {'; '.join(defects)}",
                    expected="All required fields present and valid enum",
                    actual="; ".join(defects),
                    source_refs=[
                        SourceRef(
                            file="requirements.csv",
                            row_number=r.row_number,
                            record_id=rec_id,
                            fields=dict(r),
                        )
                    ],
                )
            )

    # 2. test_results.csv
    for r in _extract_rows(test_rows):
        test_id = r.get("test_id", "").strip()
        req_id = r.get("requirement_id", "").strip()
        status = r.get("status", "").strip()
        run_id = r.get("run_id", "").strip()
        started_at = r.get("started_at", "").strip()
        completed_at = r.get("completed_at", "").strip()
        actual_result = r.get("actual_result", "").strip()
        unit = r.get("unit", "").strip()

        rec_id = test_id if test_id else f"test_results.csv#{r.row_number}"
        defects = []

        if not test_id:
            defects.append("Missing test_id (MISSING)")
        if not req_id:
            defects.append("Missing requirement_id (MISSING)")
        if not status:
            defects.append("Missing status (MISSING)")
        elif status not in ALLOWED_STATUSES:
            defects.append(f"Invalid status {status!r} (INVALID_ENUM)")
        elif status in ("Pass", "Fail"):
            # Required when status is Pass or Fail
            if not run_id:
                defects.append("Missing run_id for executed test (MISSING)")
            if not started_at:
                defects.append("Missing started_at for executed test (MISSING)")
            if not completed_at:
                defects.append("Missing completed_at for executed test (MISSING)")
            if not actual_result:
                defects.append("Missing actual_result for executed test (MISSING)")
            if not unit:
                defects.append("Missing unit for executed test (MISSING)")
        # When status == "Not Run", run_id/timestamps/actual_result/unit may be blank

        if defects:
            findings.append(
                Finding(
                    rule_id="R01",
                    variant=None,
                    severity=severity,
                    finding_class=finding_class,
                    entity_key=rec_id,
                    description=f"Test record {rec_id} has defects: {'; '.join(defects)}",
                    expected="All required fields present and valid enum",
                    actual="; ".join(defects),
                    source_refs=[
                        SourceRef(
                            file="test_results.csv",
                            row_number=r.row_number,
                            record_id=rec_id,
                            fields=dict(r),
                        )
                    ],
                )
            )

    # 3. telemetry.csv (grouped per series run_id:signal_name)
    tel_series_defects: dict[str, list[tuple[RowData, str]]] = {}
    for r in _extract_rows(tel_rows):
        run_id = r.get("run_id", "").strip()
        timestamp = r.get("timestamp", "").strip()
        signal_name = r.get("signal_name", "").strip()
        value = r.get("value", "").strip()
        unit = r.get("unit", "").strip()

        series_key = (
            f"{run_id}:{signal_name}"
            if (run_id or signal_name)
            else f"telemetry.csv#{r.row_number}"
        )
        row_defects: list[str] = []

        if not run_id:
            row_defects.append("Missing run_id (MISSING)")
        if not timestamp:
            row_defects.append("Missing timestamp (MISSING)")
        if not signal_name:
            row_defects.append("Missing signal_name (MISSING)")
        if not value:
            row_defects.append("Missing value (MISSING)")
        if not unit:
            row_defects.append("Missing unit (MISSING)")

        if row_defects:
            if series_key not in tel_series_defects:
                tel_series_defects[series_key] = []
            tel_series_defects[series_key].append((r, "; ".join(row_defects)))

    for series_key, defective_items in tel_series_defects.items():
        refs = [
            SourceRef(
                file="telemetry.csv",
                row_number=r.row_number,
                record_id=series_key,
                fields=dict(r),
            )
            for r, _ in defective_items
        ]
        summary = "; ".join(f"Row {r.row_number}: {msg}" for r, msg in defective_items)
        findings.append(
            Finding(
                rule_id="R01",
                variant=None,
                severity=severity,
                finding_class=finding_class,
                entity_key=series_key,
                description=f"Telemetry series {series_key} has missing/unusable required fields: {summary}",
                expected="All telemetry fields required non-empty",
                actual=summary,
                source_refs=refs,
            )
        )

    return findings


# =============================================================================
# R02: Duplicate identifiers
# =============================================================================
def check_r02(
    req_rows: Any,
    test_rows: Any,
    tel_rows: Any,
    ruleset: dict[str, Any],
) -> list[Finding]:
    """R02 Duplicate identifiers | High | VALIDATION_FAILURE.

    Keys: requirement_id; test_id; non-blank run_id (tests);
    (run_id, timestamp, signal_name) in telemetry.
    A key value in more than one row; blanks excluded.
    One finding per duplicated key listing all rows.
    """
    severity, finding_class = _get_rule_meta(ruleset, "R02")
    findings: list[Finding] = []

    # 1. requirement_id in requirements.csv
    req_by_id: dict[str, list[RowData]] = {}
    for r in _extract_rows(req_rows):
        k = r.get("requirement_id", "").strip()
        if k:
            req_by_id.setdefault(k, []).append(r)
    for k, rows in req_by_id.items():
        if len(rows) > 1:
            findings.append(
                Finding(
                    rule_id="R02",
                    variant=None,
                    severity=severity,
                    finding_class=finding_class,
                    entity_key=k,
                    description=f"Duplicate requirement_id {k!r} found in {len(rows)} rows",
                    expected="Unique requirement_id across requirements",
                    actual=f"Found {len(rows)} instances",
                    source_refs=[
                        SourceRef(
                            file="requirements.csv",
                            row_number=r.row_number,
                            record_id=k,
                            fields=dict(r),
                        )
                        for r in rows
                    ],
                )
            )

    # 2. test_id in test_results.csv
    test_by_id: dict[str, list[RowData]] = {}
    for r in _extract_rows(test_rows):
        k = r.get("test_id", "").strip()
        if k:
            test_by_id.setdefault(k, []).append(r)
    for k, rows in test_by_id.items():
        if len(rows) > 1:
            findings.append(
                Finding(
                    rule_id="R02",
                    variant=None,
                    severity=severity,
                    finding_class=finding_class,
                    entity_key=k,
                    description=f"Duplicate test_id {k!r} found in {len(rows)} rows",
                    expected="Unique test_id across test results",
                    actual=f"Found {len(rows)} instances",
                    source_refs=[
                        SourceRef(
                            file="test_results.csv",
                            row_number=r.row_number,
                            record_id=k,
                            fields=dict(r),
                        )
                        for r in rows
                    ],
                )
            )

    # 3. non-blank run_id in test_results.csv
    test_by_run: dict[str, list[RowData]] = {}
    for r in _extract_rows(test_rows):
        k = r.get("run_id", "").strip()
        if k:
            test_by_run.setdefault(k, []).append(r)
    for k, rows in test_by_run.items():
        if len(rows) > 1:
            findings.append(
                Finding(
                    rule_id="R02",
                    variant=None,
                    severity=severity,
                    finding_class=finding_class,
                    entity_key=k,
                    description=f"Duplicate run_id {k!r} in test results found in {len(rows)} rows",
                    expected="Unique non-blank run_id across test results",
                    actual=f"Found {len(rows)} instances",
                    source_refs=[
                        SourceRef(
                            file="test_results.csv",
                            row_number=r.row_number,
                            record_id=r.get("test_id", k),
                            fields=dict(r),
                        )
                        for r in rows
                    ],
                )
            )

    # 4. (run_id, timestamp, signal_name) in telemetry.csv
    tel_by_tuple: dict[tuple[str, str, str], list[RowData]] = {}
    for r in _extract_rows(tel_rows):
        run_id = r.get("run_id", "").strip()
        timestamp = r.get("timestamp", "").strip()
        signal_name = r.get("signal_name", "").strip()
        if run_id and timestamp and signal_name:
            t_key = (run_id, timestamp, signal_name)
            tel_by_tuple.setdefault(t_key, []).append(r)

    for (run_id, timestamp, signal_name), rows in tel_by_tuple.items():
        if len(rows) > 1:
            series_key = f"{run_id}:{signal_name}"
            findings.append(
                Finding(
                    rule_id="R02",
                    variant=None,
                    severity=severity,
                    finding_class=finding_class,
                    entity_key=series_key,
                    description=(
                        f"Duplicate telemetry record for (run_id={run_id!r}, "
                        f"timestamp={timestamp!r}, signal_name={signal_name!r}) in {len(rows)} rows"
                    ),
                    expected="Unique (run_id, timestamp, signal_name) in telemetry",
                    actual=f"Found {len(rows)} instances",
                    source_refs=[
                        SourceRef(
                            file="telemetry.csv",
                            row_number=r.row_number,
                            record_id=series_key,
                            fields=dict(r),
                        )
                        for r in rows
                    ],
                )
            )

    return findings


# =============================================================================
# R03: Invalid numeric value
# =============================================================================
def check_r03(
    req_rows: Any,
    test_rows: Any,
    tel_rows: Any,
    ruleset: dict[str, Any],
) -> list[Finding]:
    r"""R03 Invalid numeric value | Medium | VALIDATION_FAILURE.

    Fields threshold_value, actual_result, value (non-empty only) must match
    the number regex ^[+-]?\d+(\.\d+)?$ and be parseable by decimal.Decimal.
    One finding per record (telemetry grouped per series).
    """
    severity, finding_class = _get_rule_meta(ruleset, "R03")
    findings: list[Finding] = []

    # 1. requirements.csv (threshold_value)
    for r in _extract_rows(req_rows):
        val = r.get("threshold_value", "").strip()
        if val and not _is_valid_decimal_number(val):
            rec_id = r.get("requirement_id", "").strip() or f"requirements.csv#{r.row_number}"
            findings.append(
                Finding(
                    rule_id="R03",
                    variant=None,
                    severity=severity,
                    finding_class=finding_class,
                    entity_key=rec_id,
                    description=f"Invalid numeric threshold_value {val!r} in requirement row {r.row_number}",
                    expected="Number matching ^[+-]?\\d+(\\.\\d+)?$",
                    actual=val,
                    source_refs=[
                        SourceRef(
                            file="requirements.csv",
                            row_number=r.row_number,
                            record_id=rec_id,
                            fields=dict(r),
                        )
                    ],
                )
            )

    # 2. test_results.csv (actual_result)
    for r in _extract_rows(test_rows):
        val = r.get("actual_result", "").strip()
        if val and not _is_valid_decimal_number(val):
            rec_id = r.get("test_id", "").strip() or f"test_results.csv#{r.row_number}"
            findings.append(
                Finding(
                    rule_id="R03",
                    variant=None,
                    severity=severity,
                    finding_class=finding_class,
                    entity_key=rec_id,
                    description=f"Invalid numeric actual_result {val!r} in test row {r.row_number}",
                    expected="Number matching ^[+-]?\\d+(\\.\\d+)?$",
                    actual=val,
                    source_refs=[
                        SourceRef(
                            file="test_results.csv",
                            row_number=r.row_number,
                            record_id=rec_id,
                            fields=dict(r),
                        )
                    ],
                )
            )

    # 3. telemetry.csv (value, grouped per series)
    tel_series_invalids: dict[str, list[tuple[RowData, str]]] = {}
    for r in _extract_rows(tel_rows):
        val = r.get("value", "").strip()
        if val and not _is_valid_decimal_number(val):
            run_id = r.get("run_id", "").strip()
            signal_name = r.get("signal_name", "").strip()
            series_key = (
                f"{run_id}:{signal_name}"
                if (run_id or signal_name)
                else f"telemetry.csv#{r.row_number}"
            )
            tel_series_invalids.setdefault(series_key, []).append((r, val))

    for series_key, items in tel_series_invalids.items():
        refs = [
            SourceRef(
                file="telemetry.csv",
                row_number=r.row_number,
                record_id=series_key,
                fields=dict(r),
            )
            for r, _ in items
        ]
        values_summary = ", ".join(f"{val!r} (row {r.row_number})" for r, val in items)
        findings.append(
            Finding(
                rule_id="R03",
                variant=None,
                severity=severity,
                finding_class=finding_class,
                entity_key=series_key,
                description=f"Invalid numeric value in telemetry series {series_key}: {values_summary}",
                expected="Number matching ^[+-]?\\d+(\\.\\d+)?$",
                actual=values_summary,
                source_refs=refs,
            )
        )

    return findings


# =============================================================================
# R04: Invalid timestamp
# =============================================================================
def check_r04(
    req_rows: Any,
    test_rows: Any,
    tel_rows: Any,
    ruleset: dict[str, Any],
) -> list[Finding]:
    """R04 Invalid timestamp | Medium | VALIDATION_FAILURE.

    started_at, completed_at, telemetry timestamp must be valid ISO 8601 with offset
    and real calendar date; additionally completed_at >= started_at (reason ORDER).
    One finding per record (telemetry grouped per series).
    """
    severity, finding_class = _get_rule_meta(ruleset, "R04")
    findings: list[Finding] = []

    # 1. test_results.csv (started_at, completed_at, and completed_at >= started_at)
    for r in _extract_rows(test_rows):
        test_id = r.get("test_id", "").strip()
        rec_id = test_id if test_id else f"test_results.csv#{r.row_number}"
        started_at = r.get("started_at", "").strip()
        completed_at = r.get("completed_at", "").strip()

        defects: list[str] = []
        dt_start: datetime | None = None
        dt_complete: datetime | None = None

        if started_at:
            if not _is_valid_iso_timestamp(started_at):
                defects.append(f"Invalid started_at format/date {started_at!r}")
            else:
                dt_start = _parse_iso_timestamp(started_at)

        if completed_at:
            if not _is_valid_iso_timestamp(completed_at):
                defects.append(f"Invalid completed_at format/date {completed_at!r}")
            else:
                dt_complete = _parse_iso_timestamp(completed_at)

        # Check completed_at >= started_at (reason ORDER)
        if dt_start is not None and dt_complete is not None:
            if dt_complete < dt_start:
                defects.append(
                    f"completed_at ({completed_at}) precedes started_at ({started_at}) (reason ORDER)"
                )

        if defects:
            findings.append(
                Finding(
                    rule_id="R04",
                    variant=None,
                    severity=severity,
                    finding_class=finding_class,
                    entity_key=rec_id,
                    description=f"Invalid timestamp in test record {rec_id}: {'; '.join(defects)}",
                    expected="Valid ISO 8601 timestamps with offset and completed_at >= started_at",
                    actual="; ".join(defects),
                    source_refs=[
                        SourceRef(
                            file="test_results.csv",
                            row_number=r.row_number,
                            record_id=rec_id,
                            fields=dict(r),
                        )
                    ],
                )
            )

    # 2. telemetry.csv (timestamp, grouped per series)
    tel_series_ts_invalids: dict[str, list[tuple[RowData, str]]] = {}
    for r in _extract_rows(tel_rows):
        ts = r.get("timestamp", "").strip()
        if ts and not _is_valid_iso_timestamp(ts):
            run_id = r.get("run_id", "").strip()
            signal_name = r.get("signal_name", "").strip()
            series_key = (
                f"{run_id}:{signal_name}"
                if (run_id or signal_name)
                else f"telemetry.csv#{r.row_number}"
            )
            tel_series_ts_invalids.setdefault(series_key, []).append((r, ts))

    for series_key, items in tel_series_ts_invalids.items():
        refs = [
            SourceRef(
                file="telemetry.csv",
                row_number=r.row_number,
                record_id=series_key,
                fields=dict(r),
            )
            for r, _ in items
        ]
        summary = ", ".join(f"{ts!r} (row {r.row_number})" for r, ts in items)
        findings.append(
            Finding(
                rule_id="R04",
                variant=None,
                severity=severity,
                finding_class=finding_class,
                entity_key=series_key,
                description=f"Invalid timestamp in telemetry series {series_key}: {summary}",
                expected="ISO 8601 YYYY-MM-DDTHH:MM:SS[.f+](Z|+HH:MM|-HH:MM)",
                actual=summary,
                source_refs=refs,
            )
        )

    return findings


# =============================================================================
# R05: Unknown requirement reference
# =============================================================================
def check_r05(
    req_rows: Any,
    test_rows: Any,
    tel_rows: Any,
    ruleset: dict[str, Any],
) -> list[Finding]:
    """R05 Unknown requirement reference | High | VALIDATION_FAILURE.

    Test row with non-blank requirement_id not present in requirements
    (rows with other defects still count as present).
    One finding per test row. Case-sensitive. Blanks are R01, not R05.
    """
    severity, finding_class = _get_rule_meta(ruleset, "R05")
    findings: list[Finding] = []

    # Known requirements: set of all non-blank requirement_id
    known_reqs = {
        r.get("requirement_id", "").strip()
        for r in _extract_rows(req_rows)
        if r.get("requirement_id", "").strip()
    }

    for r in _extract_rows(test_rows):
        req_ref = r.get("requirement_id", "").strip()
        # Blank is R01, not R05
        if not req_ref:
            continue

        if req_ref not in known_reqs:
            test_id = r.get("test_id", "").strip()
            rec_id = test_id if test_id else f"test_results.csv#{r.row_number}"
            findings.append(
                Finding(
                    rule_id="R05",
                    variant=None,
                    severity=severity,
                    finding_class=finding_class,
                    entity_key=rec_id,
                    description=(
                        f"Test {rec_id} references unknown requirement_id {req_ref!r} "
                        f"not found in requirements.csv"
                    ),
                    expected="requirement_id matching a known requirement",
                    actual=req_ref,
                    source_refs=[
                        SourceRef(
                            file="test_results.csv",
                            row_number=r.row_number,
                            record_id=rec_id,
                            fields=dict(r),
                        )
                    ],
                )
            )

    return findings


# =============================================================================
# R06: Unknown run reference
# =============================================================================
def check_r06(
    req_rows: Any,
    test_rows: Any,
    tel_rows: Any,
    ruleset: dict[str, Any],
) -> list[Finding]:
    """R06 Unknown run reference | Medium | VALIDATION_FAILURE.

    Distinct non-blank telemetry run_id not among non-blank run_id in test_results
    (any status or quality). One finding per run_id, rows grouped.
    """
    severity, finding_class = _get_rule_meta(ruleset, "R06")
    findings: list[Finding] = []

    # Known runs: distinct non-blank run_id from test_results.csv
    known_runs = {
        r.get("run_id", "").strip()
        for r in _extract_rows(test_rows)
        if r.get("run_id", "").strip()
    }

    # Group telemetry rows with unknown non-blank run_id
    unknown_run_rows: dict[str, list[RowData]] = {}
    for r in _extract_rows(tel_rows):
        run_id = r.get("run_id", "").strip()
        if run_id and run_id not in known_runs:
            unknown_run_rows.setdefault(run_id, []).append(r)

    for run_id, rows in unknown_run_rows.items():
        refs = [
            SourceRef(
                file="telemetry.csv",
                row_number=r.row_number,
                record_id=(
                    f"{run_id}:{r.get('signal_name', '').strip()}"
                    if r.get("signal_name", "").strip()
                    else f"telemetry.csv#{r.row_number}"
                ),
                fields=dict(r),
            )
            for r in rows
        ]
        findings.append(
            Finding(
                rule_id="R06",
                variant=None,
                severity=severity,
                finding_class=finding_class,
                entity_key=run_id,
                description=(
                    f"Telemetry references unknown run_id {run_id!r} "
                    f"not present in test_results.csv across {len(rows)} rows"
                ),
                expected="run_id present in test_results.csv",
                actual=f"Unknown run_id {run_id!r} with {len(rows)} rows",
                source_refs=refs,
            )
        )

    return findings


# =============================================================================
# Combined runner for M2
# =============================================================================
def run_rules_m2(
    requirements: Any,
    test_results: Any,
    telemetry: Any,
    ruleset: dict[str, Any],
) -> list[Finding]:
    """Execute validation rules R01 through R06 and return canonically sorted findings.

    Findings are sorted by (rule_id, entity_key) per SPEC section 3.
    """
    findings: list[Finding] = []
    findings.extend(check_r01(requirements, test_results, telemetry, ruleset))
    findings.extend(check_r02(requirements, test_results, telemetry, ruleset))
    findings.extend(check_r03(requirements, test_results, telemetry, ruleset))
    findings.extend(check_r04(requirements, test_results, telemetry, ruleset))
    findings.extend(check_r05(requirements, test_results, telemetry, ruleset))
    findings.extend(check_r06(requirements, test_results, telemetry, ruleset))

    # Sort canonically by (rule_id, entity_key)
    findings.sort(key=lambda f: (f.rule_id, f.entity_key))
    return findings
