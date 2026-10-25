"""Core models for TraceBridge validation engine."""

from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class SchemaError(BaseModel):
    """Schema-level validation error."""

    code: str
    message: str
    details: list[str] = Field(default_factory=list)


class SchemaValidationError(Exception):
    """Exception raised when a file fails schema-level checks."""

    def __init__(self, errors: list[SchemaError]):
        super().__init__(
            f"Schema validation failed: {', '.join(e.code for e in errors)}"
        )
        self.errors = errors


class RowData(dict):
    """Dictionary representing a single parsed CSV row.

    Provides a 1-based data-row number (header excluded) via `.row_number`
    and key indexing `row['row_number']`. All other fields store string values.
    """

    @property
    def row_number(self) -> int:
        return self["row_number"]


class LoadedDataset(BaseModel):
    """Result of successfully ingesting and parsing a dataset CSV."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    kind: str
    original_filename: str
    size_bytes: int
    sha256: str
    row_count: int
    columns: list[str]
    ignored_columns: list[str]
    trim_count: int
    rows: list[RowData]


class SourceRef(BaseModel):
    """Reference to an input CSV row supporting a finding."""

    file: str
    row_number: int
    record_id: str
    fields: dict[str, Any] = Field(default_factory=dict)


class Finding(BaseModel):
    """A deterministic validation finding emitted by a rule."""

    rule_id: str
    variant: str | None = None
    severity: str
    finding_class: str
    entity_key: str
    description: str
    expected: str | None = None
    actual: str | None = None
    source_refs: list[SourceRef] = Field(default_factory=list)
    truncated: bool = False

    def model_post_init(self, __context: Any) -> None:
        if len(self.source_refs) > 20:
            object.__setattr__(self, "source_refs", self.source_refs[:20])
            object.__setattr__(self, "truncated", True)
