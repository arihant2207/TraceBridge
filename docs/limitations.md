# TraceBridge Limitations and Boundary Constraints

This document details the known limitations, structural assumptions, and boundary conditions of TraceBridge v1.0.

---

## 1. Known Architectural Limitations

1. **Ambient & Operating Condition Checks Dropped**:
   TraceBridge evaluates threshold values against sensor telemetry streams but cannot confirm environmental conditions (e.g., ambient chamber temperature, atmospheric pressure, or test bench calibration). The Markdown export explicitly records `"recorded under the required ambient conditions?"` as `UNRESOLVED`.

2. **Zero Unit Conversion**:
   The engine does not perform dimension or scale conversions. Comparing identical quantities with different scales (such as `mA` vs `A` or `mV` vs `V`) is treated as a validation failure (`R11` variant `UNIT_MISMATCH`), halting evaluation at step S4 with outcome `INCONCLUSIVE`.

3. **Numeric Format Restrictions**:
   Numeric parsing strictly enforces `^[+-]?\d+(\.\d+)?$`. Exponential notations (e.g. `1e3`), comma decimals (`12,5`), thousands separators, `NaN`, and `inf` are rejected under rule R03.

4. **Unused Telemetry Units**:
   Rule R11 checks unit combinations only for telemetry rows that fall within an executed test's time window for a referenced signal. Unused telemetry series or unreferenced signals containing invalid unit strings are not flagged by R11.

5. **Single Global Tolerance**:
   Rule R12 evaluates consistency between reported test results and telemetry aggregates using a single global absolute tolerance of `0.05` across all signals and units, configured in `ruleset.json`.

6. **Requirement Relevance Unverified**:
   The schema links test records to requirement IDs via foreign keys, but cannot verify semantic relevance (i.e. whether the test procedure actually measures the engineering phenomenon described by the requirement). The export reports this question as `UNRESOLVED`.

---

## 2. Scoring & Gate Boundaries

1. **INCONCLUSIVE Denominator Effect**:
   When an evaluation terminates early as `INCONCLUSIVE` (at S1, S2, S3, or S4), the test does not reach S5 or S6. Consequently, it is excluded from the denominators of rules R10 and R12. In isolation, this denominator reduction can artificially inflate the arithmetic quality score. The independent gate mechanism directly compensates: any `INCONCLUSIVE` evaluation unconditionally triggers `BLOCKED_HIGH`.

2. **Policy-Based Equal Weights**:
   The 11 scored checks are weighted equally (1/11 each) in the quality score calculation. This weighting is an engineering policy choice, not derived from empirical failure distributions or risk severities.

3. **No Recommended-Action Field**:
   Findings contain rule IDs, entity keys, descriptions, expected/actual comparisons, and source references. TraceBridge does not generate remediation recommendations or prescriptive fix steps.

4. **Fixtures as Regression Checks Only**:
   The preloaded clean and fault datasets are minimal regression checks designed to verify rule and pipeline execution. They make no claims regarding precision, recall, or general model performance across arbitrary aerospace or automotive telemetry sets.

---

## 3. Discrepancies Found

The following implementation differences exist between the frozen `docs/SPEC.md` text and the active codebase:

1. **Service Layer Architecture (`backend/app/service.py`)**:
   - *Specification*: SPEC section 8 lists module paths omitting a service layer (`loader.py`, `repo.py`, `routes.py`, `exports.py`).
   - *Implementation*: Added `backend/app/service.py` to orchestrate file persistence, dataset SHA-256 recording, validation engine invocation, and database transactions within an isolated boundary.

2. **Coverage API Representation (`GET /analyses/{id}/coverage`)**:
   - *Specification*: SPEC section 11 criterion 3 describes requirement coverage with per-test outcomes.
   - *Implementation*: The endpoint `GET /analyses/{id}/coverage` returns `dict[str, str]` mapping `requirement_id -> status` (precedence resolved per U13). Full per-test outcomes are preserved in `evaluations_json` in SQLite, while the UI displays `"N/A"` for per-test columns on the coverage distribution table.

3. **`R09` Severity vs Gate Non-Blocking**:
   - *Specification*: R09 has severity `high` in `ruleset.json`, but SPEC section 6 states "OBSERVATION never blocks."
   - *Implementation*: The gate classification logic in `app/engine/scoring.py` explicitly filters for `finding.finding_class != "OBSERVATION"`, ensuring `OBSERVATION` findings never trigger `BLOCKED_HIGH` regardless of their `high` severity tag in `ruleset.json`.
