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
