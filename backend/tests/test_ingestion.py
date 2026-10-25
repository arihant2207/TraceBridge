"""Tests for data ingestion loader and schema checks (Milestone M1)."""

import hashlib
from pathlib import Path
import pytest

from app.engine.models import SchemaValidationError
from app.ingestion.loader import (
    MAX_FILE_SIZE,
    build_storage_path,
    load_dataset,
    save_uploaded_file,
)


# Path to sample directories
SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"
CLEAN_DIR = SAMPLES_DIR / "clean"
FAULT_DIR = SAMPLES_DIR / "fault"


# Valid minimal CSV templates
VALID_REQ_CSV = (
    "requirement_id,signal_name,operator,threshold_value,unit\n"
    "REQ-01,esc_temperature,<=,85,°C\n"
)
VALID_TEST_CSV = (
    "test_id,requirement_id,run_id,status,started_at,completed_at,actual_result,unit\n"
    "TST-01,REQ-01,RUN-01,Pass,2026-10-01T10:00:00Z,2026-10-01T10:02:00Z,78.4,°C\n"
)
VALID_TEL_CSV = (
    "run_id,timestamp,signal_name,value,unit\n"
    "RUN-01,2026-10-01T10:00:00Z,esc_temperature,61.2,°C\n"
)


def test_sch_001_non_csv_extension():
    """SCH-001: Extension is not .csv."""
    content = VALID_REQ_CSV.encode("utf-8")
    with pytest.raises(SchemaValidationError) as exc_info:
        load_dataset(content, "requirements.txt", "requirements")
    codes = [e.code for e in exc_info.value.errors]
    assert "SCH-001" in codes


def test_sch_001_nul_bytes():
    """SCH-001: Content contains NUL bytes."""
    content = b"requirement_id,signal_name,operator,threshold_value,unit\nREQ-01,\x00esc,<=,85,\xc2\xb0C\n"
    with pytest.raises(SchemaValidationError) as exc_info:
        load_dataset(content, "requirements.csv", "requirements")
    codes = [e.code for e in exc_info.value.errors]
    assert "SCH-001" in codes


def test_sch_002_file_larger_than_5mb():
    """SCH-002: File larger than 5 MB."""
    # 5 MB + 1 byte
    content = b"a" * (MAX_FILE_SIZE + 1)
    with pytest.raises(SchemaValidationError) as exc_info:
        load_dataset(content, "requirements.csv", "requirements")
    codes = [e.code for e in exc_info.value.errors]
    assert "SCH-002" in codes


def test_sch_003_not_decodable_utf8():
    """SCH-003: Not decodable as UTF-8."""
    # Invalid UTF-8 sequence
    content = b"\xff\xfe\x80\x81invalid"
    with pytest.raises(SchemaValidationError) as exc_info:
        load_dataset(content, "requirements.csv", "requirements")
    codes = [e.code for e in exc_info.value.errors]
    assert "SCH-003" in codes


def test_sch_003_empty_file():
    """SCH-003: File is empty (not parseable as CSV / no header)."""
    content = b""
    with pytest.raises(SchemaValidationError) as exc_info:
        load_dataset(content, "requirements.csv", "requirements")
    codes = [e.code for e in exc_info.value.errors]
    assert "SCH-003" in codes


def test_sch_004_mandatory_columns_missing():
    """SCH-004: Mandatory column(s) missing."""
    # Missing 'threshold_value' and 'unit'
    csv_text = "requirement_id,signal_name,operator\nREQ-01,temp,<=\n"
    with pytest.raises(SchemaValidationError) as exc_info:
        load_dataset(csv_text.encode("utf-8"), "requirements.csv", "requirements")
    errs = [e for e in exc_info.value.errors if e.code == "SCH-004"]
    assert len(errs) > 0
    missing_details = " ".join(errs[0].details)
    assert "threshold_value" in missing_details
    assert "unit" in missing_details


def test_sch_005_duplicate_column_names():
    """SCH-005: Duplicate column names in header."""
    csv_text = (
        "requirement_id,signal_name,operator,threshold_value,unit,signal_name\n"
        "REQ-01,temp,<=,85,°C,temp\n"
    )
    with pytest.raises(SchemaValidationError) as exc_info:
        load_dataset(csv_text.encode("utf-8"), "requirements.csv", "requirements")
    codes = [e.code for e in exc_info.value.errors]
    assert "SCH-005" in codes


def test_sch_006_header_present_zero_data_rows():
    """SCH-006: Header present but zero data rows."""
    csv_text = "requirement_id,signal_name,operator,threshold_value,unit\n"
    with pytest.raises(SchemaValidationError) as exc_info:
        load_dataset(csv_text.encode("utf-8"), "requirements.csv", "requirements")
    codes = [e.code for e in exc_info.value.errors]
    assert "SCH-006" in codes


def test_sch_007_ragged_rows():
    """SCH-007: Ragged rows (field count differs from header)."""
    # Row 1 has 5 fields, row 2 has 3 fields
    csv_text = (
        "requirement_id,signal_name,operator,threshold_value,unit\n"
        "REQ-01,temp,<=,85,°C\n"
        "REQ-02,voltage,>=\n"
    )
    with pytest.raises(SchemaValidationError) as exc_info:
        load_dataset(csv_text.encode("utf-8"), "requirements.csv", "requirements")
    codes = [e.code for e in exc_info.value.errors]
    assert "SCH-007" in codes


def test_collects_all_errors_together():
    """Loader collects all schema errors on a file, not just the first."""
    # Extension wrong (.txt -> SCH-001), duplicate columns (SCH-005), missing mandatory unit (SCH-004), ragged row (SCH-007)
    bad_csv = (
        "requirement_id,signal_name,operator,threshold_value,signal_name\n"
        "REQ-01,temp,<=,85\n"
    )
    with pytest.raises(SchemaValidationError) as exc_info:
        load_dataset(bad_csv.encode("utf-8"), "requirements.txt", "requirements")
    codes = [e.code for e in exc_info.value.errors]
    assert "SCH-001" in codes
    assert "SCH-004" in codes
    assert "SCH-005" in codes
    assert "SCH-007" in codes


def test_bom_accepted():
    """UTF-8 BOM is accepted transparently without corrupting header."""
    content = b"\xef\xbb\xbf" + VALID_REQ_CSV.encode("utf-8")
    dataset = load_dataset(content, "requirements.csv", "requirements")
    assert dataset.row_count == 1
    assert dataset.columns[0] == "requirement_id"
    assert dataset.rows[0]["requirement_id"] == "REQ-01"


def test_crlf_accepted():
    """CRLF line endings parse identically to LF."""
    crlf_text = (
        "run_id,timestamp,signal_name,value,unit\r\n"
        "RUN-01,2026-10-01T10:00:00Z,esc_temperature,61.2,°C\r\n"
        "RUN-01,2026-10-01T10:01:00Z,esc_temperature,78.4,°C\r\n"
    )
    dataset = load_dataset(crlf_text.encode("utf-8"), "telemetry.csv", "telemetry")
    assert dataset.row_count == 2
    assert dataset.rows[0]["run_id"] == "RUN-01"
    assert dataset.rows[1]["run_id"] == "RUN-01"


def test_extra_column_reported_in_ignored_columns():
    """Extra columns are listed in ignored_columns and retained in row data."""
    csv_text = (
        "requirement_id,description,subsystem,signal_name,operator,threshold_value,unit\n"
        "REQ-01,ESC temp limit,thermal,esc_temp,<=,85,°C\n"
    )
    dataset = load_dataset(csv_text.encode("utf-8"), "requirements.csv", "requirements")
    assert "description" in dataset.ignored_columns
    assert "subsystem" in dataset.ignored_columns
    assert dataset.rows[0]["description"] == "ESC temp limit"
    assert dataset.rows[0]["subsystem"] == "thermal"


def test_whitespace_trim_counted():
    """Leading and trailing whitespace is trimmed and recorded in trim_count."""
    csv_text = (
        "requirement_id,signal_name,operator,threshold_value,unit\n"
        "  REQ-01  , esc_temperature ,<=, 85 , °C \n"
        "REQ-02,motor_current,<=,30, A \n"
    )
    # 4 trimmed cells in row 1, 1 trimmed cell in row 2 = 5 trimmed cells
    dataset = load_dataset(csv_text.encode("utf-8"), "requirements.csv", "requirements")
    assert dataset.trim_count == 5
    assert dataset.rows[0]["requirement_id"] == "REQ-01"
    assert dataset.rows[0]["signal_name"] == "esc_temperature"
    assert dataset.rows[0]["threshold_value"] == "85"
    assert dataset.rows[1]["unit"] == "A"


def test_sha256_equals_hashlib_result():
    """Dataset sha256 matches hashlib.sha256 of raw bytes."""
    content = VALID_TEL_CSV.encode("utf-8")
    expected_sha256 = hashlib.sha256(content).hexdigest()
    dataset = load_dataset(content, "telemetry.csv", "telemetry")
    assert dataset.sha256 == expected_sha256


def test_row_numbers_start_at_1():
    """Data row numbers start at 1 and increment sequentially."""
    csv_text = (
        "run_id,timestamp,signal_name,value,unit\n"
        "RUN-01,2026-10-01T10:00:00Z,esc_temperature,61.2,°C\n"
        "RUN-01,2026-10-01T10:01:00Z,esc_temperature,78.4,°C\n"
        "RUN-01,2026-10-01T10:02:00Z,esc_temperature,77.1,°C\n"
    )
    dataset = load_dataset(csv_text.encode("utf-8"), "telemetry.csv", "telemetry")
    assert dataset.row_count == 3
    assert dataset.rows[0].row_number == 1
    assert dataset.rows[0]["row_number"] == 1
    assert dataset.rows[1].row_number == 2
    assert dataset.rows[1]["row_number"] == 2
    assert dataset.rows[2].row_number == 3
    assert dataset.rows[2]["row_number"] == 3


def test_na_nan_strings_preserved():
    """Values like 'NA', 'n/a', 'NaN' remain literal strings and are not converted to NaN."""
    csv_text = (
        "run_id,timestamp,signal_name,value,unit\n"
        "RUN-01,2026-10-01T10:00:00Z,esc_temperature,NA,°C\n"
        "RUN-01,2026-10-01T10:01:00Z,esc_temperature,n/a,°C\n"
        "RUN-01,2026-10-01T10:02:00Z,esc_temperature,NaN,°C\n"
    )
    dataset = load_dataset(csv_text.encode("utf-8"), "telemetry.csv", "telemetry")
    assert dataset.rows[0]["value"] == "NA"
    assert dataset.rows[1]["value"] == "n/a"
    assert dataset.rows[2]["value"] == "NaN"


def test_path_safety_user_filename_never_influences_path(tmp_path: Path):
    """User filename like '../../x.csv' never influences server storage path."""
    content = VALID_REQ_CSV.encode("utf-8")
    user_filename = "../../x.csv"
    analysis_id = "analysis-abc-123"

    # User filename is passed to load_dataset as metadata only
    dataset = load_dataset(content, user_filename, "requirements")
    assert dataset.original_filename == "../../x.csv"

    # Storage path is built strictly from analysis_id and kind
    storage_path = build_storage_path(analysis_id, "requirements", base_dir=tmp_path)
    expected_path = (tmp_path / analysis_id / "requirements.csv").resolve()
    assert storage_path == expected_path

    # Verify traversal attempts in analysis_id are rejected
    with pytest.raises(ValueError):
        build_storage_path("../../escaped", "requirements", base_dir=tmp_path)

    with pytest.raises(ValueError):
        build_storage_path("sub/folder", "requirements", base_dir=tmp_path)

    # Save and verify physical file placement
    saved_path = save_uploaded_file(content, analysis_id, "requirements", base_dir=tmp_path)
    assert saved_path == expected_path
    assert saved_path.exists()
    assert saved_path.read_bytes() == content


def test_load_sample_csvs_clean_dataset():
    """Clean sample CSVs load cleanly with row counts 3 / 3 / 9."""
    req_bytes = (CLEAN_DIR / "requirements.csv").read_bytes()
    test_bytes = (CLEAN_DIR / "test_results.csv").read_bytes()
    tel_bytes = (CLEAN_DIR / "telemetry.csv").read_bytes()

    req_ds = load_dataset(req_bytes, "requirements.csv", "requirements")
    test_ds = load_dataset(test_bytes, "test_results.csv", "test_results")
    tel_ds = load_dataset(tel_bytes, "telemetry.csv", "telemetry")

    assert req_ds.row_count == 3
    assert test_ds.row_count == 3
    assert tel_ds.row_count == 9

    # Verify ignored_columns on clean requirements (has description column)
    assert "description" in req_ds.ignored_columns


def test_load_sample_csvs_fault_dataset():
    """Fault sample CSVs load cleanly with row counts 5 / 11 / 19."""
    req_bytes = (FAULT_DIR / "requirements.csv").read_bytes()
    test_bytes = (FAULT_DIR / "test_results.csv").read_bytes()
    tel_bytes = (FAULT_DIR / "telemetry.csv").read_bytes()

    req_ds = load_dataset(req_bytes, "requirements.csv", "requirements")
    test_ds = load_dataset(test_bytes, "test_results.csv", "test_results")
    tel_ds = load_dataset(tel_bytes, "telemetry.csv", "telemetry")

    assert req_ds.row_count == 5
    assert test_ds.row_count == 11
    assert tel_ds.row_count == 19
