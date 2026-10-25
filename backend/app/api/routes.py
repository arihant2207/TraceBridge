"""FastAPI router implementing the 9 SPEC section 9 endpoints under /api/v1."""

import csv
import hashlib
import io
from pathlib import Path
from typing import Any
import zipfile

from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import JSONResponse

from app.api.schemas import (
    AnalysisDetail,
    AnalysisSummary,
    DatasetInfo,
    DatasetPreviewResponse,
    FindingResponse,
    RequirementCoverageItem,
    ReviewResponse,
    ReviewUpdateRequest,
    TestOutcomeItem,
)
from app.db.database import get_db_connection
from app.db.repo import (
    get_analysis,
    get_dataset_by_kind,
    get_datasets,
    get_findings,
    insert_export,
    list_analyses,
    update_finding_review,
)
from app.reporting.exports import export_csv, export_json, export_markdown
from app.service import SAMPLES_DIR, create_analysis

router = APIRouter(prefix="/api/v1")


# =============================================================================
# 1. POST /analyses (multipart or sample=clean|fault)
# =============================================================================
@router.post(
    "/analyses",
    response_model=AnalysisDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create and execute a new engineering validation analysis",
)
async def post_analysis(
    sample: str | None = Form(None),
    sample_query: str | None = Query(None, alias="sample"),
    requirements: UploadFile | None = File(None),
    test_results: UploadFile | None = File(None),
    telemetry: UploadFile | None = File(None),
) -> Any:
    # Resolve sample param from either query or form
    chosen_sample = sample or sample_query

    if chosen_sample:
        if chosen_sample not in ("clean", "fault"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown sample {chosen_sample!r}; must be 'clean' or 'fault'.",
            )
        analysis_record = create_analysis(sample=chosen_sample)
    else:
        if not requirements or not test_results or not telemetry:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="All three dataset files (requirements, test_results, telemetry) or 'sample' parameter are required.",
            )

        files = {
            "requirements": (requirements.filename or "requirements.csv", await requirements.read()),
            "test_results": (test_results.filename or "test_results.csv", await test_results.read()),
            "telemetry": (telemetry.filename or "telemetry.csv", await telemetry.read()),
        }
        analysis_record = create_analysis(files=files)

    conn = get_db_connection()
    datasets = get_datasets(conn, analysis_record["id"])
    conn.close()

    analysis_record["datasets"] = datasets
    return analysis_record


# =============================================================================
# 2. GET /analyses
# =============================================================================
@router.get(
    "/analyses",
    response_model=list[AnalysisSummary],
    summary="List all analyses",
)
def get_analyses() -> Any:
    conn = get_db_connection()
    analyses = list_analyses(conn)
    conn.close()
    return analyses


# =============================================================================
# 3. GET /analyses/{id}
# =============================================================================
@router.get(
    "/analyses/{id}",
    response_model=AnalysisDetail,
    summary="Get analysis details by ID",
)
def get_analysis_by_id(id: str) -> Any:
    conn = get_db_connection()
    analysis = get_analysis(conn, id)
    if not analysis:
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Analysis with ID {id!r} not found.",
        )
    datasets = get_datasets(conn, id)
    conn.close()
    analysis["datasets"] = datasets
    return analysis


# =============================================================================
# 4. GET /analyses/{id}/findings (filters: severity, rule_id, class, review_status)
# =============================================================================
@router.get(
    "/analyses/{id}/findings",
    response_model=list[FindingResponse],
    summary="Get findings for an analysis with optional filters",
)
def get_analysis_findings(
    id: str,
    severity: str | None = Query(None),
    rule_id: str | None = Query(None),
    finding_class: str | None = Query(None, alias="class"),
    review_status: str | None = Query(None),
) -> Any:
    conn = get_db_connection()
    analysis = get_analysis(conn, id)
    if not analysis:
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Analysis with ID {id!r} not found.",
        )

    findings = get_findings(
        conn=conn,
        analysis_id=id,
        severity=severity,
        rule_id=rule_id,
        finding_class=finding_class,
        review_status=review_status,
    )
    conn.close()
    return findings


# =============================================================================
# 5. GET /analyses/{id}/coverage
# =============================================================================
@router.get(
    "/analyses/{id}/coverage",
    response_model=dict[str, RequirementCoverageItem],
    summary="Get requirement coverage statuses and per-test outcomes for an analysis",
)
def get_analysis_coverage(id: str) -> dict[str, RequirementCoverageItem]:
    conn = get_db_connection()
    analysis = get_analysis(conn, id)
    conn.close()
    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Analysis with ID {id!r} not found.",
        )

    coverage_map = analysis.get("coverage", {})
    evaluations = analysis.get("evaluations", [])

    # If any evaluation lacks requirement_id, fallback to mapping from stored test_results.csv
    missing_req = any(not ev.get("requirement_id") for ev in evaluations)
    test_to_req: dict[str, str] = {}
    if missing_req:
        try:
            from app.service import get_upload_base_dir
            base_dir = get_upload_base_dir()
            test_csv_path = base_dir / id / "test_results.csv"
            if test_csv_path.exists():
                with open(test_csv_path, mode="r", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    for r in reader:
                        tid = (r.get("test_id") or "").strip()
                        rid = (r.get("requirement_id") or "").strip()
                        if tid and rid:
                            test_to_req[tid] = rid
        except Exception:
            pass

    evals_by_req: dict[str, list[TestOutcomeItem]] = {}
    for ev in evaluations:
        req_id = ev.get("requirement_id") or test_to_req.get(ev.get("test_id", ""))
        if req_id:
            evals_by_req.setdefault(req_id, []).append(
                TestOutcomeItem(
                    test_id=ev["test_id"],
                    outcome=ev["outcome"],
                    blocked_by=ev.get("blocked_by", []),
                )
            )

    result: dict[str, RequirementCoverageItem] = {}
    for req_id, req_status in coverage_map.items():
        result[req_id] = RequirementCoverageItem(
            status=req_status,
            test_outcomes=evals_by_req.get(req_id, []),
        )
    return result


# =============================================================================
# 6. GET /analyses/{id}/datasets/{kind}/preview?limit=20
# =============================================================================
@router.get(
    "/analyses/{id}/datasets/{kind}/preview",
    response_model=DatasetPreviewResponse,
    summary="Preview raw parsed rows from a stored dataset",
)
def get_dataset_preview(
    id: str,
    kind: str,
    limit: int = Query(20, ge=1, le=1000),
) -> Any:
    if kind not in ("requirements", "test_results", "telemetry"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invalid dataset kind {kind!r}; must be requirements, test_results, or telemetry.",
        )

    conn = get_db_connection()
    ds_record = get_dataset_by_kind(conn, id, kind)
    conn.close()

    if not ds_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset {kind!r} for analysis {id!r} not found.",
        )

    stored_path = Path(ds_record["stored_path"])
    if not stored_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Stored dataset file not found at {stored_path}.",
        )

    content = stored_path.read_text(encoding="utf-8")
    reader = csv.DictReader(io.StringIO(content))
    columns = reader.fieldnames or []
    rows: list[dict[str, Any]] = []
    total_count = 0

    for i, row in enumerate(reader):
        total_count += 1
        if i < limit:
            rows.append(dict(row))

    return DatasetPreviewResponse(
        kind=kind,
        columns=list(columns),
        rows=rows,
        total_rows=ds_record["row_count"],
    )


# =============================================================================
# 7. GET /analyses/{id}/export?format=md|json|csv
# =============================================================================
@router.get(
    "/analyses/{id}/export",
    summary="Export analysis report in Markdown, JSON, or CSV format",
)
def get_analysis_export(
    id: str,
    format: str = Query("md", pattern="^(md|markdown|json|csv)$"),
) -> Response:
    format_normalized = format.lower()
    if format_normalized == "markdown":
        format_normalized = "md"

    conn = get_db_connection()
    analysis = get_analysis(conn, id)
    if not analysis:
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Analysis with ID {id!r} not found.",
        )

    datasets = get_datasets(conn, id)
    findings = get_findings(conn, id)

    if format_normalized == "md":
        content = export_markdown(analysis, findings, datasets)
        media_type = "text/markdown; charset=utf-8"
        filename = f"tracebridge_report_{id}.md"
    elif format_normalized == "json":
        content = export_json(analysis, findings, datasets)
        media_type = "application/json"
        filename = f"tracebridge_report_{id}.json"
    elif format_normalized == "csv":
        content = export_csv(findings)
        media_type = "text/csv; charset=utf-8"
        filename = f"tracebridge_findings_{id}.csv"
    else:
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported format: {format!r}",
        )

    content_bytes = content.encode("utf-8")
    sha256 = hashlib.sha256(content_bytes).hexdigest()
    byte_size = len(content_bytes)

    # Record export in database
    insert_export(conn, id, format_normalized, sha256, byte_size)
    conn.close()

    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Export-SHA256": sha256,
    }
    return Response(content=content, media_type=media_type, headers=headers)


# =============================================================================
# 8. PATCH /findings/{id}/review (review_status unreviewed|reviewed)
# =============================================================================
@router.patch(
    "/findings/{id}/review",
    response_model=ReviewResponse,
    summary="Update finding review status and reviewer note",
)
def patch_finding_review(
    id: str,
    body: ReviewUpdateRequest,
) -> Any:
    conn = get_db_connection()
    review = update_finding_review(
        conn=conn,
        finding_id=id,
        review_status=body.review_status,
        reviewer_note=body.reviewer_note,
    )
    conn.close()

    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Finding with ID {id!r} not found.",
        )

    return ReviewResponse(
        finding_id=review["finding_id"],
        review_status=review["review_status"],
        reviewer_note=review["reviewer_note"],
        updated_at=review["updated_at"],
    )


# =============================================================================
# 9. GET /samples/{clean|fault}.zip
# =============================================================================
@router.get(
    "/samples/{sample}.zip",
    summary="Download sample dataset files as a zip archive",
)
def get_sample_zip(sample: str) -> Response:
    if sample not in ("clean", "fault"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown sample {sample!r}; must be 'clean' or 'fault'.",
        )

    sample_dir = SAMPLES_DIR / sample
    if not sample_dir.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sample directory not found: {sample_dir}",
        )

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for fname in ("requirements.csv", "test_results.csv", "telemetry.csv"):
            fpath = sample_dir / fname
            if fpath.exists():
                zf.writestr(fname, fpath.read_bytes())

    zip_bytes = zip_buffer.getvalue()
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{sample}.zip"'},
    )
