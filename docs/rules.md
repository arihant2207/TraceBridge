# TraceBridge Validation Rules and Evaluation Pipeline

This document defines the 12 deterministic validation rules (R01–R12), the sequential evaluation pipeline (S1–S6), the evidence quality scoring formula, and the gate classification logic.

Severity and finding class values are read directly from `backend/app/engine/ruleset.json`:
- **Classes**: `OBSERVATION`, `VALIDATION_FAILURE`, `MISSING_EVIDENCE`.
- **Severities**: `critical`, `high`, `medium`, `low`.

---

## 1. Validation Rules (R01 to R12)

### Rule Core Principles
- **R02 Failing Entity Count**: R02 counts each duplicated row as one failing entity. For example, if test ID `TST-010` appears across 2 rows, both rows are failing entities (count = 2).
- **Derived Aggregation**: Aggregation is strictly derived from the comparison operator in the requirement:
  - `<` and `<=`: Maximum (`max`) of in-window telemetry values.
  - `>` and `>=`: Minimum (`min`) of in-window telemetry values.
- **No Unit Conversion**: The engine performs zero unit conversion. Any difference in unit representation (e.g. `mA` vs `A`) triggers R11 and renders the test evaluation `INCONCLUSIVE`.
- **Absolute Tolerance**: R12 uses an absolute difference tolerance of `0.05` for all signals, read from `ruleset.json`.

---

### R01: Missing/unusable required field
- **Severity**: `high`
- **Finding Class**: `MISSING_EVIDENCE`
- **Inputs**: Parsed rows from `requirements.csv`, `test_results.csv`, and `telemetry.csv`.
- **Logic**: Any row of any file where a required value is empty after whitespace trim (reason `MISSING`), or where enum values (`status` in test results, `operator` in requirements) fall outside the allowed set (reason `INVALID_ENUM`). Grouped per record; telemetry rows are grouped per `run_id:signal_name` series.
- **Source References**: `{file, row_number, record_id, fields}` (capped at 20).
- **Positive Example**: Test row with status `Pass` and blank `actual_result`.
- **Negative Example**: Test row with status `Not Run` having blank `run_id`, `started_at`, `completed_at`, and `actual_result`.
- **Edge Cases**: Whitespace-only cells are considered empty (`MISSING`); lowercase `pass` is flagged as `INVALID_ENUM`; literal string `"NA"` or `"n/a"` is treated as a populated string, not missing.

---

### R02: Duplicate identifiers
- **Severity**: `high`
- **Finding Class**: `VALIDATION_FAILURE`
- **Inputs**: Primary identifier keys across datasets:
  - `requirements.csv`: `requirement_id`
  - `test_results.csv`: `test_id`
  - `test_results.csv`: non-blank `run_id`
  - `telemetry.csv`: `(run_id, timestamp, signal_name)` composite key
- **Logic**: A key value occurring in more than one row; blank values are excluded. Produces one finding per duplicated key listing all affected rows.
- **Entity Accounting**: Each duplicated row counts as one failing entity (e.g. `TST-010` in 2 rows counts as 2 failing entities in scoring).
- **Source References**: All rows sharing the duplicated key.
- **Positive Example**: `test_id` `TST-010` appearing in two distinct rows.
- **Negative Example**: The same `run_id` appearing across multiple telemetry rows with different timestamps or signals.
- **Edge Cases**: Fully identical duplicate rows are still flagged; comparison is case-sensitive; multiple `Not Run` tests with blank `run_id` are not treated as duplicate run IDs.

---

### R03: Invalid numeric value
- **Severity**: `medium`
- **Finding Class**: `VALIDATION_FAILURE`
- **Inputs**: Numeric fields `threshold_value` (requirements), `actual_result` (test results), and `value` (telemetry).
- **Logic**: Non-empty fields must match the standard numeric regex `^[+-]?\d+(\.\d+)?$`.
- **Source References**: Offending data row.
- **Positive Example**: Telemetry value `"n/a"`.
- **Negative Example**: `"-5.0"`.
- **Edge Cases**: `NaN`, `inf`, `-inf`, exponential notation like `1e3`, and comma decimals like `12,5` are rejected.

---

### R04: Invalid timestamp
- **Severity**: `medium`
- **Finding Class**: `VALIDATION_FAILURE`
- **Inputs**: `started_at` and `completed_at` (test results); `timestamp` (telemetry).
- **Logic**: Timestamps must strictly parse as ISO 8601 with timezone offset (`YYYY-MM-DDTHH:MM:SS[.f+](Z|+HH:MM|-HH:MM)`), represent real calendar dates, and normalize to UTC. In test results, `completed_at` must be greater than or equal to `started_at` (reason `ORDER`).
- **Source References**: Offending row.
- **Positive Example**: `"2026-10-01 12:00:00"` (missing `T` separator and offset).
- **Negative Example**: `"2026-10-01T12:00:00+05:30"`.
- **Edge Cases**: Equal start and completion timestamps (`started_at == completed_at`) are permitted; date-only strings, February 30 (`2026-02-30`), and `24:00:00` are invalid; fractional seconds are allowed.

---

### R05: Unknown requirement reference
- **Severity**: `high`
- **Finding Class**: `VALIDATION_FAILURE`
- **Inputs**: `test_results.csv` against `requirements.csv`.
- **Logic**: A test row with a non-blank `requirement_id` that is not present in `requirements.csv`. (Requirement rows with other defects still count as present). Emits one finding per offending test row.
- **Source References**: Test row.
- **Positive Example**: Test `TST-009` referencing unknown requirement `REQ-THM-099`.
- **Negative Example**: `Not Run` test referencing an existing requirement ID.
- **Edge Cases**: Blank `requirement_id` triggers R01, not R05; key matching is case-sensitive.

---

### R06: Unknown run reference
- **Severity**: `medium`
- **Finding Class**: `VALIDATION_FAILURE`
- **Inputs**: `telemetry.csv` against `test_results.csv`.
- **Logic**: Distinct non-blank telemetry `run_id` values not present among non-blank `run_id` values in `test_results.csv`. Grouped per `run_id`.
- **Source References**: Up to 20 telemetry rows referencing the unknown run.
- **Positive Example**: Telemetry row with `run_id` `"RUN-0099"`.
- **Negative Example**: Telemetry for a run whose corresponding test row has defects elsewhere in the file.

---

### R07: Missing requirement-to-test link
- **Severity**: `high`
- **Finding Class**: `MISSING_EVIDENCE`
- **Inputs**: Requirements mapped to test results.
- **Logic**: Evaluated per requirement:
  - Variant `NO_TEST`: Zero test rows reference the requirement.
  - Variant `NOT_EXECUTED`: Tests reference the requirement, but all tests are marked `Not Run` or have invalid statuses.
- **Source References**: Requirement row, plus any test rows if variant is `NOT_EXECUTED`.
- **Positive Example**: `REQ-PWR-009` with zero referencing tests (`NO_TEST`); `REQ-THM-015` with only `Not Run` tests (`NOT_EXECUTED`).
- **Negative Example**: Requirement referenced by at least one test with status `Pass` or `Fail`.
- **Edge Cases**: Tests pointing to nonexistent requirements do not establish valid links; each requirement is evaluated once.

---

### R08: Missing required telemetry evidence
- **Severity**: `high`
- **Finding Class**: `MISSING_EVIDENCE`
- **Inputs**: Executed tests passing pipeline steps S1 and S2.
- **Logic**: Zero telemetry rows exist matching `run_id`, matching `signal_name`, and satisfying `started_at <= timestamp <= completed_at`.
- **Source References**: Test row, requirement row, and up to 20 rows of the same run with different signals (including out-of-window count).
- **Positive Example**: Test `TST-007` with no telemetry for signal `temp_ambient`.
- **Negative Example**: Test `TST-001` with matching telemetry samples inside the execution window.
- **Edge Cases**: Samples falling exactly on `started_at` or `completed_at` are inclusive; runs with telemetry falling exclusively outside the window trigger R08.

---

### R09: Threshold violation
- **Severity**: `high`
- **Finding Class**: `OBSERVATION` *(Excluded from quality score and gate)*
- **Inputs**: Tests reaching pipeline step S5.
- **Logic**: The telemetry extremum aggregate (using Decimal comparison) violates `aggregate op threshold`.
- **Source References**: Test row, extremum telemetry row.
- **Positive Example**: Test `TST-001` requiring `<= 85 °C` where maximum recorded telemetry is `91.0 °C`.
- **Negative Example**: Test `TST-001` in clean fixture where recorded maximum is `<= 85.0 °C`.
- **Edge Cases**: `85.0 <= 85` is satisfied; `85.0 < 85` is violated; negative values supported; timestamp ties select the earliest sample.

---

### R10: Status vs measurement contradiction
- **Severity**: `critical`
- **Finding Class**: `VALIDATION_FAILURE`
- **Inputs**: Conclusive evaluation outcomes (`SATISFIED` or `VIOLATED`).
- **Logic**: Triggered when either:
  - Test status is `Pass` but physical evidence outcome is `VIOLATED`.
  - Test status is `Fail` but physical evidence outcome is `SATISFIED`.
- **Source References**: Test row, extremum telemetry row, requirement row.
- **Positive Example**: Test `TST-001` reported as `Pass` while telemetry aggregate `91.0 °C` violates requirement `<= 85 °C`.
- **Negative Example**: Test `TST-002` reported as `Fail` with telemetry aggregate violating requirement.
- **Edge Cases**: `INCONCLUSIVE` evaluations never trigger R10; `Not Run` tests are excluded.

---

### R11: Invalid unit combination
- **Severity**: `high`
- **Finding Class**: `VALIDATION_FAILURE`
- **Inputs**: Tests passing pipeline steps S1 to S3.
- **Logic**: Requirement unit, test result unit, and all in-window telemetry units must be present in the unit registry (`°C`, `K`, `A`, `mA`, `V`, `mV`) and must be strictly identical across all three datasets. Variants:
  - `UNKNOWN_UNIT`: Unit not in registry.
  - `DIMENSION_MISMATCH`: Different physical dimensions (e.g. `V` vs `A`).
  - `UNIT_MISMATCH`: Same dimension but differing scale (e.g. `mA` vs `A`).
- **Source References**: Test row, requirement row, and representative telemetry row.
- **Positive Example**: Test `TST-004` claiming unit `mA` against requirement unit `A`.
- **Negative Example**: All rows consistently reporting unit `A`.
- **Edge Cases**: Non-standard symbols such as `℃`, `a`, `volts` are flagged as `UNKNOWN_UNIT`; no conversion is attempted.

---

### R12: Reported value inconsistent with source
- **Severity**: `high`
- **Finding Class**: `VALIDATION_FAILURE`
- **Inputs**: Conclusive evaluations with a valid `actual_result`.
- **Logic**: Triggered when the absolute difference between claimed `actual_result` and computed telemetry aggregate exceeds `0.05` (`|actual_result - aggregate| > 0.05`).
- **Tolerance**: Absolute `0.05` (configurable in `ruleset.json`).
- **Source References**: Test row and extremum telemetry row.
- **Positive Example**: Test `TST-001` claiming `actual_result = 78.4` against telemetry aggregate `91.0`.
- **Negative Example**: Test `TST-005` claiming `21.6` against telemetry aggregate `21.6`.
- **Edge Cases**: Difference of exactly `0.05` passes; trailing zeroes (`21.60` vs `21.6`) are numerically equal under Decimal evaluation.

---

## 2. Evaluation Pipeline (S1 to S6)

Evaluations run for each test with status `Pass` or `Fail`. Execution halts at the first failing step with outcome `INCONCLUSIVE` and records the IDs of findings blocking progress (`blocked_by`):

1. **S1 (Integrity & Linkage)**: Test row must have zero R01, R02, R03, or R04 findings. The target requirement must exist (no R05) and have zero R01, R02, or R03 findings.
2. **S2 (Telemetry Cleanliness)**: No selected telemetry row matching `run_id` and `signal_name` may have an R01, R03, or R04 finding.
3. **S3 (Telemetry Presence)**: At least one in-window telemetry sample must exist, otherwise R08 is raised and execution stops.
4. **S4 (Unit Consistency)**: Units must match exactly across requirement, test, and telemetry without conversion, otherwise R11 is raised and execution stops.
5. **S5 (Threshold Evaluation)**: Derives aggregate from operator (`max` for `<`, `<=`; `min` for `>`, `>=`) and compares to requirement threshold. Yields conclusive outcome `SATISFIED` or `VIOLATED` (emitting R09 if violated).
6. **S6 (Cross-Checks)**: Evaluates R10 (status vs measurement contradiction) and R12 (reported value vs aggregate consistency).

`Not Run` tests produce no evaluation record. Tests with duplicate test IDs fail S1 and are not evaluated.

---

## 3. Evidence Quality Score Formula

The quality score is the unweighted arithmetic mean of entity pass rates across the 11 scored checks:
$$\text{Score} = 100 \times \frac{1}{N_{\text{applicable}}} \sum_{i=1}^{11} \text{pass\_rate}_i$$

Where:
$$\text{pass\_rate}_i = \frac{\text{applicable}_i - \text{failing}_i}{\text{applicable}_i}$$

### Rules and Denominators:
1. **R01 to R04**: Applicable entities = requirement rows + test rows + distinct telemetry series (`run_id:signal_name`). Failing = distinct entities with that rule's finding.
2. **R05**: Applicable entities = test rows with non-blank `requirement_id`.
3. **R06**: Applicable entities = distinct telemetry `run_id`s.
4. **R07**: Applicable entities = distinct requirement IDs.
5. **R08**: Applicable entities = executed tests passing S1 and S2.
6. **R10**: Applicable entities = conclusive evaluations (`SATISFIED` or `VIOLATED`).
7. **R11**: Applicable entities = executed tests passing S1 to S3.
8. **R12**: Applicable entities = conclusive evaluations with valid numeric `actual_result`.

- **Exclusions**: R09 is classified as an `OBSERVATION` and is excluded from both scoring and the gate.
- **Rounding**: Rounded half-up to 1 decimal place using `decimal.Decimal`.
- **N/A Handling**: Checks with 0 applicable entities are excluded from the denominator ($N_{\text{applicable}}$).

---

## 4. Gate Classification Rules

The gate status is determined independently from the score:

1. **`BLOCKED_CRITICAL`**: Raised if any non-OBSERVATION finding with severity `critical` exists (e.g. R10).
2. **`BLOCKED_HIGH`**: Raised if any non-OBSERVATION finding with severity `high` exists (e.g. R01, R02, R05, R07, R08, R11, R12) OR if any test evaluation ends as `INCONCLUSIVE`.
3. **`NOT_BLOCKED`**: Assigned only when zero blocking findings and zero inconclusive evaluations exist.

### Operational Gate Constraints:
- Engineering review status never alters the gate.
- A high score never overrides a blocked gate.
- `NOT_BLOCKED` does not imply safety, sign-off, or certification.
