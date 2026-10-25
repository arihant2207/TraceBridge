# TraceBridge Manual QA Checklist

This manual checklist verifies system compliance against the acceptance criteria defined in `docs/SPEC.md` section 11. All verification steps must be manually validated by a test engineer before sign-off. Every box must start unticked.

---

## Criterion 1: Automated Unit & Rule Tests
- [ ] Execute `pytest -v` from `backend/` directory.
- [ ] Confirm all tests for rules R01 through R12 (positive, negative, and edge test cases) execute and pass without errors.
- [ ] Verify that zero tests are skipped or disabled.

## Criterion 2: Clean Dataset Verification
- [ ] Submit `POST /api/v1/analyses?sample=clean` or execute via web UI **Run Clean Sample**.
- [ ] Confirm `quality_score` equals `100.0`.
- [ ] Confirm `gate` equals `NOT_BLOCKED`.
- [ ] Confirm `finding_count` equals `1`.
- [ ] Confirm the single finding is rule `R09` on entity `TST-002` with class `OBSERVATION`.

## Criterion 3: Fault Dataset Finding Exactness
- [ ] Submit `POST /api/v1/analyses?sample=fault` or execute via web UI **Run Fault Sample**.
- [ ] Confirm total `finding_count` equals `14` (0 missing, 0 extra).
- [ ] Confirm severity breakdown matches: 2 Critical, 9 High, 3 Medium.
- [ ] Confirm listed non-findings are strictly absent:
  - [ ] No R08–R12 findings for `TST-002`, `TST-003`, `TST-006`, `TST-010` (both duplicate rows).
  - [ ] No R09 finding for `TST-007` or `TST-009`.
  - [ ] No R12 finding for `TST-005`.
  - [ ] No R01 finding for `TST-008`.

## Criterion 4: Fault Dataset Quality Score and Gate
- [ ] On the fault sample analysis result, confirm `quality_score` equals `73.3`.
- [ ] Confirm `gate` equals `BLOCKED_CRITICAL`.
- [ ] Verify that the score is not styled in green anywhere in the UI while blocked.

## Criterion 5: Findings Digest Determinism
- [ ] Execute two separate analysis runs using the identical clean dataset inputs.
- [ ] Confirm both runs yield the identical SHA-256 `findings_digest`.
- [ ] Execute two separate analysis runs using the identical fault dataset inputs.
- [ ] Confirm both runs yield the identical SHA-256 `findings_digest`.

## Criterion 6: Record Processing & Provenance Accounting
- [ ] For clean sample, verify `records_processed` equals `15` (3 requirements + 3 tests + 9 telemetry).
- [ ] For fault sample, verify `records_processed` equals `35` (5 requirements + 11 tests + 19 telemetry).
- [ ] Confirm every parsed CSV row failing a row-level rule is cited in at least one finding source reference.

## Criterion 7: Schema-Level Rejection Integrity (SCH-001..SCH-007)
- [ ] Submit a non-CSV file or file with NUL bytes (SCH-001) -> verify HTTP 422 error.
- [ ] Submit a file larger than 5 MB (SCH-002) -> verify HTTP 422 error.
- [ ] Submit a non-UTF-8 or empty file (SCH-003) -> verify HTTP 422 error.
- [ ] Submit a file missing mandatory header columns (SCH-004) -> verify HTTP 422 error.
- [ ] Submit a file with duplicate column headers (SCH-005) -> verify HTTP 422 error.
- [ ] Submit a file with a header but 0 data rows (SCH-006) -> verify HTTP 422 error.
- [ ] Submit a file with ragged rows (field count mismatch) (SCH-007) -> verify HTTP 422 error.
- [ ] Confirm that on HTTP 422, zero analysis database rows are created and zero files are written to disk.

## Criterion 8: Path Traversal Protection
- [ ] Upload files with path traversal names (e.g. `../../payload.csv`).
- [ ] Confirm the file is stored under `data/uploads/<analysis_id>/<kind>.csv` and the client-supplied filename never influences storage location.

## Criterion 9: Review Audit Trail Isolation
- [ ] Select any finding and execute `PATCH /api/v1/findings/{id}/review` with status `reviewed` and a justification note.
- [ ] Confirm the review record is updated in table `finding_reviews`.
- [ ] Verify that `findings`, `findings_digest`, and `gate` remain completely unchanged.

## Criterion 10: Multi-Format Export Parity
- [ ] Request `GET /api/v1/analyses/{id}/export?format=md` -> verify all finding IDs are present in Markdown.
- [ ] Request `GET /api/v1/analyses/{id}/export?format=json` -> verify JSON structure matches API output.
- [ ] Request `GET /api/v1/analyses/{id}/export?format=csv` -> verify CSV data row count equals the API `finding_count`.

## Criterion 11: Web UI Integrity
- [ ] Open web dashboard at `http://localhost:3000`.
- [ ] On the fault analysis detail page, verify the finding count header displays `14`.
- [ ] Filter findings by severity `Critical` -> verify exactly 2 rows are displayed.
- [ ] Select finding for rule `R10` on `TST-001` -> inspect source telemetry and confirm recorded extremum value is `91.0`.
- [ ] Verify that UI displays only API-provided values without computing or recalculating counts in the browser.
