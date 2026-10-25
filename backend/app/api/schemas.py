"""Pydantic schemas for TraceBridge API endpoints."""

from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ErrorDetail(BaseModel):
    """Detailed error object in error envelope."""

    code: str
    message: str
    details: list[str] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    """Unified error envelope per SPEC section 9."""

    error: ErrorDetail


class DatasetInfo(BaseModel):
    """Dataset metadata record."""

    id: int | None = None
    kind: str
    original_filename: str
    stored_path: str
    size_bytes: int
    sha256: str
    row_count: int
    ignored_columns: list[str] = Field(default_factory=list)
    trim_count: int = 0


class AnalysisSummary(BaseModel):
    """Summary of an analysis for listing."""

    id: str
    created_at: str
    records_processed: int
    finding_count: int
    gate: str
    quality_score: str
    findings_digest: str


class AnalysisDetail(AnalysisSummary):
    """Comprehensive analysis report record."""

    versions: dict[str, str]
    ruleset_sha256: str
    input_fingerprint: str
    score_breakdown: dict[str, Any]
    coverage: dict[str, str]
    evaluations: list[dict[str, Any]] = Field(default_factory=list)
    datasets: list[DatasetInfo] = Field(default_factory=list)


class TestOutcomeItem(BaseModel):
    """Outcome of an evaluated test against a requirement."""

    test_id: str
    outcome: str
    blocked_by: list[str] = Field(default_factory=list)


class RequirementCoverageItem(BaseModel):
    """Coverage status and per-test outcomes for a requirement."""

    status: str
    test_outcomes: list[TestOutcomeItem] = Field(default_factory=list)


class FindingResponse(BaseModel):
    """Finding item returned by GET findings."""

    id: str
    analysis_id: str
    rule_id: str
    variant: str | None = None
    severity: str
    finding_class: str
    entity_key: str
    description: str
    expected: str | None = None
    actual: str | None = None
    source_refs: list[dict[str, Any]] = Field(default_factory=list)
    truncated: bool = False
    review_status: str = "unreviewed"
    reviewer_note: str = ""
    review_updated_at: str | None = None


class ReviewUpdateRequest(BaseModel):
    """Request body for PATCH /findings/{id}/review."""

    review_status: str
    reviewer_note: str = ""

    @field_validator("review_status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in ("unreviewed", "reviewed"):
            raise ValueError("review_status must be either 'unreviewed' or 'reviewed'")
        return v

    @field_validator("reviewer_note")
    @classmethod
    def validate_note(cls, v: str) -> str:
        if len(v) > 2000:
            raise ValueError("reviewer_note must be <= 2000 characters")
        return v


class ReviewResponse(BaseModel):
    """Response returned by PATCH /findings/{id}/review."""

    finding_id: str
    review_status: str
    reviewer_note: str
    updated_at: str


class DatasetPreviewResponse(BaseModel):
    """Preview of parsed rows from a stored dataset."""

    kind: str
    columns: list[str]
    rows: list[dict[str, Any]]
    total_rows: int
