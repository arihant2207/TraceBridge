# TraceBridge MVP: Frozen Spec v1.0 (source of truth)

If anything in a prompt conflicts with this file, STOP and ask. Do not choose silently.

## 0. Standing rules for any agent working in this repo
1. Work ONLY inside this workspace. Never read the clipboard, shell history, other folders or drives, OneDrive, Downloads, or any file not named in the task. Never run `git clone` or change git remotes. No web search unless asked. If a needed file is missing, stop and report the missing path.
2. Stack: Python 3.12, FastAPI, Pandas, Pydantic, SQLite, pytest (backend); Next.js + TypeScript (frontend, later). No LLM, no vector DB, no auth, no external services, no runtime network access. Minimum dependencies, pinned versions.
3. The backend engine is the only authority for validation results. Rule logic = pure Python functions with no FastAPI, DB or filesystem imports. The frontend never computes validation results.
4. Use `decimal.Decimal` for all numeric comparison, never float. Read all CSV cells as strings (`dtype=str`, `keep_default_na=False`).
5. Never discard input rows silently. Every parsed row keeps a 1-based data-row number (header excluded).
6. Never edit anything under `backend/samples/`. Never weaken, skip or delete a test to make it pass. If a test fails, report it with a diagnosis.
7. Do not invent results. Report only outputs you actually observed; paste real command output.
8. No destructive commands, no secrets in git, ask before installing anything not in this spec.
9. Do only the milestone named in the task. Do not start the next one.

## 1. Scope
In: upload of 3 CSVs (requirements, test_results, telemetry); 12 deterministic rules; evidence quality score; separate blocking gate; requirement coverage; findings table with filters and source rows; review status + note; exports in Markdown, JSON, CSV; SHA-256 provenance; automated tests; clean and fault sample datasets.
Out: LLMs, vector DB, auth, external integrations, Docker, async jobs, evidence manifest, condition (ambient) checks, unit conversion, PDF/docx export, Playwright, PostgreSQL.

## 2. Locked decisions (U1 to U15)
- U1 Ambient/other condition checks are dropped. The report must list "recorded under the required ambient conditions?" as UNRESOLVED.
- U2 Aggregation derives from the operator: max for `<` and `<=`; min for `>` and `>=`.
- U3 `actual_result` is the aggregate the test report claims.
- U4 Window is `[started_at, completed_at]`, inclusive, UTC. Timestamps without offset are invalid.
- U5 No unit conversion. Any unit difference (even mA vs A) is R11 and the evaluation is INCONCLUSIVE.
- U6 Invalid enum values (`status`, `operator`) fold into R01. IDs are opaque non-empty strings, no regex.
- U7 Evidence manifest is out of the MVP.
- U8 `test_id` and non-blank `run_id` are unique. Retests use new IDs.
- U9 INCONCLUSIVE evaluations block the gate. OBSERVATION never blocks. Review status never affects the gate.
- U10 R12 tolerance is absolute 0.05 for all signals (configurable in `ruleset.json`).
- U11 Minimum samples in window = 1.
- U12 Score uses equal weights over the 11 scored checks (a policy choice, not derived).
- U13 Requirement status precedence: NOT_COVERED, NOT_EXECUTED, then CONTRADICTORY > VIOLATED > INCONCLUSIVE > SATISFIED.
- U14 Out-of-window telemetry is excluded and counted in the evaluation record; no separate finding.
- U15 No preview before analysis. Schema errors return 422 on submit; previews are served after analysis.

## 3. Data contracts
Files: UTF-8 (BOM tolerated), comma delimiter, header required, `.csv`, max 5 MB each. Column names exact and case-sensitive. Extra columns are allowed and listed in `ignored_columns`, never dropped silently. Whitespace trim only (leading/trailing); the number of changed cells is recorded as `trim_count`.

Mandatory columns:
- requirements.csv: requirement_id, signal_name, operator, threshold_value, unit (extra: description, subsystem, owner, etc. are ignored columns)
- test_results.csv: test_id, requirement_id, run_id, status, started_at, completed_at, actual_result, unit (extra such as expected_result ignored). Required VALUES: test_id, requirement_id, status always; run_id, started_at, completed_at, actual_result, unit when status is Pass or Fail. `status` is exactly `Pass`, `Fail` or `Not Run`.
- telemetry.csv: run_id, timestamp, signal_name, value, unit. All values required.
- `operator` is exactly one of `<`, `<=`, `>`, `>=`.

Schema-level errors REJECT the file (HTTP 422, no analysis created); collect all errors per file:
- SCH-001 extension not `.csv`, or content contains NUL bytes
- SCH-002 file larger than 5 MB
- SCH-003 not decodable as UTF-8 or not parseable as CSV
- SCH-004 mandatory column(s) missing
- SCH-005 duplicate column names
- SCH-006 header present but zero data rows
- SCH-007 ragged rows (field count differs from header)

Row-level problems never reject; they become findings.

Unit registry: `°C`,`K` (temperature); `A`,`mA` (current); `V`,`mV` (voltage). Case-sensitive.
Numbers: regex `^[+-]?\d+(\.\d+)?$` (no exponent, no thousands separators, no NaN/inf). "NA", "n/a" are plain strings, not special.
Timestamps: ISO 8601 `YYYY-MM-DDTHH:MM:SS[.f+](Z|+HH:MM|-HH:MM)`, real calendar date, normalized to UTC.
Entity key: record ID; `file#row` if the ID is missing; `run_id:signal_name` for telemetry (telemetry findings are grouped per series).
Source ref: `{file, row_number, record_id, fields}`; snapshots capped at 20 per finding with a `truncated` flag.
Finding order: sort by `(rule_id, entity_key)`; IDs `<analysis_id>-F0001...`. `findings_digest` = SHA-256 of canonical findings JSON excluding IDs, timestamps and reviews.

## 4. Rules
Severity and class come from `ruleset.json`, not from code branches. Classes: OBSERVATION, VALIDATION_FAILURE, MISSING_EVIDENCE, INCONCLUSIVE (evaluation outcome, recorded in evaluations, not as a separate finding).

**R01 Missing/unusable required field** | High | MISSING_EVIDENCE. Any row of any file: a required value is empty after trim (reason MISSING) or `status`/`operator` is outside the allowed set (INVALID_ENUM). One finding per record (telemetry grouped per series). Pos: Pass test with blank actual_result. Neg: Not Run test with blank run/timestamps/result. Edge: whitespace-only is empty; `pass` lowercase is INVALID_ENUM; literal `NA` is a value, not missing.

**R02 Duplicate identifiers** | High | VALIDATION_FAILURE. Keys: requirement_id; test_id; non-blank run_id (tests); (run_id, timestamp, signal_name) in telemetry. A key value in more than one row; blanks excluded. One finding per duplicated key listing all rows. Pos: TST-010 twice. Neg: same run_id across many telemetry rows. Edge: identical duplicate rows still flagged; case-sensitive; several Not Run rows with blank run_id are not duplicates.

**R03 Invalid numeric value** | Medium | VALIDATION_FAILURE. Fields threshold_value, actual_result, value (non-empty only) must match the number regex. Pos: telemetry value `n/a`. Neg: `-5.0`. Edge: NaN, inf, `1e3`, `12,5` rejected.

**R04 Invalid timestamp** | Medium | VALIDATION_FAILURE. started_at, completed_at, telemetry timestamp must be valid per section 3; additionally completed_at >= started_at (reason ORDER). Pos: `2026-10-01 12:00:00`. Neg: `2026-10-01T12:00:00+05:30`. Edge: equal start/complete allowed; date-only, Feb 30, `24:00:00` invalid; fractional seconds allowed.

**R05 Unknown requirement reference** | High | VALIDATION_FAILURE. Test row with non-blank requirement_id not present in requirements (rows with other defects still count as present). One finding per test row. Pos: TST-009 -> REQ-THM-099. Neg: Not Run test pointing to an existing requirement. Edge: blank is R01 not R05; case-sensitive.

**R06 Unknown run reference** | Medium | VALIDATION_FAILURE. Distinct non-blank telemetry run_id not among non-blank run_id in test_results (any status or quality). One finding per run_id, rows grouped. Pos: RUN-0099. Neg: telemetry for a run whose test row has other defects is still known.

**R07 Missing requirement-to-test link** | High | MISSING_EVIDENCE. Per requirement_id: links = test rows with that requirement_id. Covered if any link has valid status Pass or Fail (even if the row has other defects). Variant NO_TEST: zero links. Variant NOT_EXECUTED: links exist but all are Not Run or have an invalid status. Pos: REQ-PWR-009 (NO_TEST), REQ-THM-015 (NOT_EXECUTED). Neg: requirement with one Pass test. Edge: a test pointing to a nonexistent requirement links nothing; requirement evaluated once per ID.

**R08 Missing required telemetry evidence** | High | MISSING_EVIDENCE. Executed test that passed S1 and S2: zero telemetry rows with matching run_id, matching signal_name and started_at <= timestamp <= completed_at. One finding per test; refs include test row, requirement row, up to 20 rows of the same run with other signals; out-of-window count shown. Pos: TST-007. Neg: TST-001. Edge: samples exactly at start/end count; rows only outside the window still trigger R08.

**R09 Threshold violation** | High (configurable) | OBSERVATION; EXCLUDED from gate and score. Evaluation that reaches S5: aggregate (max for `<`/`<=`, min for `>`/`>=`, Decimal) violates `aggregate op threshold`. Expected like `<= 85 °C`, actual like `max = 91.0 °C (n=3)`. Refs: test row, extremum telemetry row. Pos: fault TST-001; clean TST-002. Neg: clean TST-001. Edge: `85.0 <= 85` satisfied; `85.0 < 85` violated; negatives; ties list the earliest timestamp.

**R10 Status vs measurement contradiction** | Critical | VALIDATION_FAILURE. Outcome SATISFIED/VIOLATED and (status Pass with VIOLATED) or (status Fail with SATISFIED). Pos: fault TST-001, TST-005. Neg: clean TST-002 (Fail + violated). Edge: INCONCLUSIVE never triggers; Not Run excluded.

**R11 Invalid unit combination** | High | VALIDATION_FAILURE. Tests that passed S1 to S3: requirement.unit, test.unit and every selected telemetry unit must be in the registry and EXACTLY equal. Variants UNKNOWN_UNIT, DIMENSION_MISMATCH, UNIT_MISMATCH. Pos: TST-004 (mA vs A, variant UNIT_MISMATCH). Neg: all `A`. Edge: `℃`, `a`, `volts` unknown; `°C` vs `K` is UNIT_MISMATCH. Limitation: unknown units in rows not used by any test are not flagged.

**R12 Reported value inconsistent with source** | High | VALIDATION_FAILURE. Conclusive evaluation with valid actual_result: `|actual_result - aggregate| > 0.05` (strictly greater). Pos: fault TST-001 (78.4 vs 91.0). Neg: TST-005 (21.6 vs 21.6). Edge: difference of exactly 0.05 passes; `21.60` equals `21.6`.

## 5. Evaluation (per test with status Pass or Fail, in order; the first failing step ends it as INCONCLUSIVE with `blocked_by` finding IDs)
- S1 test row has no R01/R02/R03/R04 finding; requirement exists (no R05); requirement row has no R01/R02/R03 finding.
- S2 no selected telemetry row (matching run_id and signal_name) has an R01/R03/R04 finding.
- S3 at least one in-window row, else R08.
- S4 unit check, else R11.
- S5 aggregate and compare -> SATISFIED or VIOLATED (R09 if violated).
- S6 cross-checks R10 and R12.
Not Run tests have no evaluation. Duplicated test rows are not evaluated (S1 fails).

## 6. Score and gate
Score = 100 x mean(pass_rate) over applicable checks, equal weights, R09 excluded; pass_rate = (applicable - failing) / applicable in distinct entities; round half-up to 1 decimal with Decimal; N/A checks excluded from the mean. Telemetry volume must not affect the score (a telemetry series is one entity).
- R01-R04: applicable = requirement rows + test rows + telemetry series; failing = distinct entities with that rule's finding.
- R05: test rows with non-blank requirement_id. R06: distinct telemetry run_ids. R07: requirements.
- R08: executed tests passing S1 and S2. R10: conclusive evaluations. R11: tests passing S1 to S3. R12: conclusive evaluations with a valid actual_result.
The score measures evidence quality only, not safety, correctness or certification readiness.
Known weakness: INCONCLUSIVE evaluations leave the R10/R12 denominators, which can inflate the score; the gate compensates.

Gate (always shown beside the score, independent of it):
- BLOCKED_CRITICAL if any non-OBSERVATION Critical finding exists.
- Else BLOCKED_HIGH if any non-OBSERVATION High finding exists or any evaluation is INCONCLUSIVE.
- Else NOT_BLOCKED (this does NOT mean approved).
Review status never changes the gate. A high score is never styled green while the gate is blocked.

## 7. Sample datasets and fixtures
`backend/samples/clean/` (15 records: 3+3+9) and `backend/samples/fault/` (35 records: 5+11+19). `expected_clean.json` and `expected_fault.json` are human-owned. Comparison: rule_id, variant, entity_key, severity, finding_class match exactly; expected `source_refs` must be a SUBSET of actual refs (extra context refs allowed). Clean: exactly 1 finding (R09 on TST-002), score 100.0, gate NOT_BLOCKED. Fault: exactly 14 findings (2 critical, 9 high, 3 medium), gate BLOCKED_CRITICAL, score 73.3 (hand-computed; if code differs, investigate both sides, do not silently edit).
Fault dataset must NOT produce: R08-R12 for TST-002, TST-003, TST-006, TST-010 (both rows); R09 for TST-007 or TST-009; R12 for TST-005; R01 for TST-008.

## 8. Minimum project structure
```
tracebridge/
  README.md  .gitignore  .env.example
  docs/SPEC.md
  backend/
    requirements.txt
    app/
      main.py
      api/routes.py  api/schemas.py
      ingestion/loader.py
      engine/models.py rules.py evaluate.py scoring.py ruleset.json
      db/database.py repo.py
      reporting/exports.py
    samples/ (clean/, fault/, expected_*.json)
    tests/ test_ingestion.py test_rules.py test_samples.py test_api.py test_exports.py
  frontend/ (Next.js + TypeScript: app/, components/, lib/api.ts, types/api.ts generated from OpenAPI)
```
Uploaded files are stored at `data/uploads/<analysis_id>/<kind>.csv`; the user filename is metadata only and never part of a path.

## 9. API and database
Endpoints (`/api/v1`): POST /analyses (multipart or `sample=clean|fault`); GET /analyses; GET /analyses/{id}; GET /analyses/{id}/findings (filters: severity, rule_id, class, review_status); GET /analyses/{id}/coverage; GET /analyses/{id}/datasets/{kind}/preview?limit=20; GET /analyses/{id}/export?format=md|json|csv; PATCH /findings/{id}/review (review_status unreviewed|reviewed, reviewer_note <= 2000 chars); GET /samples/{clean|fault}.zip.
Error envelope: `{"error": {"code", "message", "details": []}}`; never expose raw server errors.
DB tables: analyses (versions, ruleset_sha256, input_fingerprint, findings_digest, records_processed, finding_count, gate, quality_score, score_json, coverage_json, evaluations_json), datasets (kind, original_filename, stored_path, size_bytes, sha256, row_count, ignored_columns, trim_count), findings (immutable after insert; rule_id, variant, severity, finding_class, entity_key, source_refs_json), finding_reviews (separate table), exports (format, sha256, byte_size). Telemetry rows are NOT stored in the DB.

## 10. Implementation sequence (one milestone per prompt)
M1 backend skeleton + loader (SCH-001..007, sha256, trim, row numbers, path safety). M2 rules R01-R06 + tests. M3 evaluation S1-S6 + rules R07-R12 + tests. M4 score, gate, coverage, findings_digest + golden tests vs expected JSON (backend authoritative before any UI). M5 SQLite + API + exports + API tests. M6 frontend: new analysis, results (score and gate, findings table, filters, detail with source rows, review). M7 export/report view, coverage bars, empty/error states. M8 README, docs/rules.md, limitations, manual QA checklist.

## 11. Acceptance criteria (all must hold)
1. Every rule R01-R12 has its positive, negative and edge tests, all passing.
2. Clean: exactly 1 expected finding, score 100.0, gate NOT_BLOCKED.
3. Fault: exactly the 14 expected findings (0 missing, 0 extra); listed non-findings absent.
4. Fault score equals 73.3 or the discrepancy is investigated and resolved; gate BLOCKED_CRITICAL.
5. Two runs on the same inputs give the same findings_digest.
6. records_processed equals the sum of file row counts (15 clean, 35 fault); every row failing a row-level rule is referenced by a finding.
7. Schema-reject cases return 422 with no analysis created.
8. A filename like `../../x.csv` never influences the storage path.
9. PATCH review changes only finding_reviews; findings, findings_digest and gate stay identical.
10. MD, JSON and CSV exports agree with the API (every finding ID present; CSV row count = finding count).
11. The UI shows only API-provided values; on the fault sample it shows 14 findings, the Critical filter shows 2, and the R10/TST-001 detail shows telemetry value 91.0.
The fixtures are regression checks only. No precision, recall or performance claims are made.

## 12. Known limitations
No conditions (ambient) check; no unit conversion; exponent notation rejected; unknown units in unused rows not flagged; INCONCLUSIVE can inflate score denominators; single global tolerance; a test's relevance to a requirement (does the test actually verify it?) cannot be established from this schema and is reported as unresolved.