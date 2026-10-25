"""Data ingestion and validation loader for TraceBridge."""

import csv
import hashlib
import io
import os
from pathlib import Path
from typing import Any

import pandas as pd

from app.engine.models import (
    LoadedDataset,
    RowData,
    SchemaError,
    SchemaValidationError,
)

# Maximum file size allowed: 5 MB (5 * 1024 * 1024 bytes)
MAX_FILE_SIZE = 5 * 1024 * 1024

# Mandatory columns per dataset kind (case-sensitive)
MANDATORY_COLUMNS: dict[str, list[str]] = {
    "requirements": [
        "requirement_id",
        "signal_name",
        "operator",
        "threshold_value",
        "unit",
    ],
    "test_results": [
        "test_id",
        "requirement_id",
        "run_id",
        "status",
        "started_at",
        "completed_at",
        "actual_result",
        "unit",
    ],
    "telemetry": [
        "run_id",
        "timestamp",
        "signal_name",
        "value",
        "unit",
    ],
}


def load_dataset(content: bytes, original_filename: str, kind: str) -> LoadedDataset:
    """Validate and load a CSV dataset from raw bytes.

    Performs schema-level checks (SCH-001 through SCH-007) and collects ALL errors.
    If any schema error is found, raises SchemaValidationError(errors).
    On success, returns a LoadedDataset with parsed, trimmed string rows and metadata.

    Args:
        content: Raw bytes of the uploaded file.
        original_filename: Original name of the uploaded file.
        kind: One of "requirements", "test_results", "telemetry".

    Returns:
        LoadedDataset containing parsed rows and ingestion metadata.

    Raises:
        ValueError: If dataset kind is unknown.
        SchemaValidationError: If schema-level validation fails.
    """
    if kind not in MANDATORY_COLUMNS:
        raise ValueError(
            f"Unknown dataset kind: {kind!r}. Expected one of {list(MANDATORY_COLUMNS.keys())}"
        )

    errors: list[SchemaError] = []

    # SCH-001: Extension is not .csv, or content contains NUL bytes
    if not original_filename.lower().endswith(".csv"):
        errors.append(
            SchemaError(
                code="SCH-001",
                message="File extension is not .csv",
                details=[f"Filename {original_filename!r} does not have a .csv extension"],
            )
        )
    if b"\x00" in content:
        errors.append(
            SchemaError(
                code="SCH-001",
                message="File content contains NUL bytes",
                details=["NUL byte (0x00) detected in content"],
            )
        )

    # SCH-002: File larger than 5 MB
    if len(content) > MAX_FILE_SIZE:
        errors.append(
            SchemaError(
                code="SCH-002",
                message="File larger than 5 MB limit",
                details=[
                    f"File size {len(content)} bytes exceeds maximum allowed size of {MAX_FILE_SIZE} bytes"
                ],
            )
        )

    # SCH-003: Not decodable as UTF-8 (accept a BOM) or not parseable as CSV
    text: str | None = None
    try:
        # utf-8-sig transparently handles and strips UTF-8 BOM if present
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        errors.append(
            SchemaError(
                code="SCH-003",
                message="File is not decodable as UTF-8",
                details=[f"UTF-8 decode failed: {exc}"],
            )
        )

    # If decoding failed, we cannot inspect CSV structure
    if text is None:
        raise SchemaValidationError(errors)

    # Check for empty content
    if not text.strip():
        errors.append(
            SchemaError(
                code="SCH-003",
                message="File is empty or not parseable as CSV",
                details=["File contains no readable text"],
            )
        )
        raise SchemaValidationError(errors)

    # Parse lines using standard csv.reader to check structure
    try:
        reader = csv.reader(io.StringIO(text))
        all_rows = list(reader)
    except csv.Error as exc:
        errors.append(
            SchemaError(
                code="SCH-003",
                message="File is not parseable as CSV",
                details=[f"CSV parse error: {exc}"],
            )
        )
        raise SchemaValidationError(errors)

    # Strip empty rows at the end of the file caused by trailing newlines
    while all_rows and len(all_rows[-1]) == 0:
        all_rows.pop()

    if not all_rows:
        errors.append(
            SchemaError(
                code="SCH-003",
                message="CSV header missing",
                details=["File contains no header row"],
            )
        )
        raise SchemaValidationError(errors)

    header_cols = all_rows[0]
    data_rows = all_rows[1:]

    # SCH-004: Mandatory column(s) missing
    mandatory = MANDATORY_COLUMNS[kind]
    missing_cols = [col for col in mandatory if col not in header_cols]
    if missing_cols:
        errors.append(
            SchemaError(
                code="SCH-004",
                message=f"Mandatory column(s) missing for {kind}",
                details=[f"Missing column: {col}" for col in missing_cols],
            )
        )

    # SCH-005: Duplicate column names
    seen_cols: set[str] = set()
    dup_cols: list[str] = []
    for col in header_cols:
        if col in seen_cols:
            if col not in dup_cols:
                dup_cols.append(col)
        else:
            seen_cols.add(col)
    if dup_cols:
        errors.append(
            SchemaError(
                code="SCH-005",
                message="Duplicate column names in header",
                details=[f"Duplicate column: {col}" for col in dup_cols],
            )
        )

    # SCH-006: Header present but zero data rows
    if len(data_rows) == 0:
        errors.append(
            SchemaError(
                code="SCH-006",
                message="Header present but zero data rows",
                details=["File contains a header row but 0 data rows"],
            )
        )

    # SCH-007: Ragged rows (field count differs from header)
    expected_count = len(header_cols)
    ragged_rows: list[str] = []
    for idx, row in enumerate(data_rows, start=1):
        if len(row) != expected_count:
            ragged_rows.append(
                f"Row {idx}: expected {expected_count} fields, got {len(row)}"
            )
    if ragged_rows:
        errors.append(
            SchemaError(
                code="SCH-007",
                message="Ragged rows: field count differs from header",
                details=ragged_rows,
            )
        )

    # If any schema errors were found, reject the file
    if errors:
        raise SchemaValidationError(errors)

    # Parse with pandas using dtype=str and keep_default_na=False
    df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)

    columns = list(df.columns)
    ignored_columns = [col for col in columns if col not in mandatory]

    # Trim whitespace and record trim_count
    trim_count = 0
    parsed_rows: list[RowData] = []
    for row_idx, df_row in enumerate(df.itertuples(index=False), start=1):
        row_dict = RowData()
        row_dict["row_number"] = row_idx
        for col_name, val in zip(df.columns, df_row):
            val_str = str(val)
            trimmed_val = val_str.strip()
            if trimmed_val != val_str:
                trim_count += 1
            row_dict[col_name] = trimmed_val
        parsed_rows.append(row_dict)

    sha256 = hashlib.sha256(content).hexdigest()

    return LoadedDataset(
        kind=kind,
        original_filename=original_filename,
        size_bytes=len(content),
        sha256=sha256,
        row_count=len(parsed_rows),
        columns=columns,
        ignored_columns=ignored_columns,
        trim_count=trim_count,
        rows=parsed_rows,
    )


def build_storage_path(
    analysis_id: str,
    kind: str,
    base_dir: Path | str = "data/uploads",
) -> Path:
    """Build a server-generated storage path from analysis_id and kind only.

    The user's original filename is never used in the storage path.
    Verifies that the generated path cannot escape the base directory.

    Args:
        analysis_id: Identifier for the analysis session.
        kind: Dataset kind ("requirements", "test_results", or "telemetry").
        base_dir: Base directory for uploads (defaults to 'data/uploads').

    Returns:
        Safe destination Path under base_dir / analysis_id / f"{kind}.csv".

    Raises:
        ValueError: If kind is invalid, analysis_id is invalid, or traversal is detected.
    """
    if kind not in MANDATORY_COLUMNS:
        raise ValueError(f"Invalid dataset kind: {kind!r}")

    # Reject traversal or separator characters in analysis_id
    if not analysis_id or "/" in analysis_id or "\\" in analysis_id or ".." in analysis_id:
        raise ValueError(
            f"Invalid analysis_id: path traversal or separators not allowed ({analysis_id!r})"
        )

    base = Path(base_dir).resolve()
    target = (base / analysis_id / f"{kind}.csv").resolve()

    # Verify that the target is strictly within base
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise ValueError(
            f"Path traversal detected: {target} escapes base {base}"
        ) from exc

    return target


def save_uploaded_file(
    content: bytes,
    analysis_id: str,
    kind: str,
    base_dir: Path | str = "data/uploads",
) -> Path:
    """Save raw file bytes to the safe server-generated path."""
    dest = build_storage_path(analysis_id, kind, base_dir=base_dir)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    return dest
