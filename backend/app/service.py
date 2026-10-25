"""Service orchestrator tying together loader, engine, and database repository.

Note: This file is a small architectural deviation from the SPEC file list,
created to encapsulate business orchestration between API, engine, and database.
"""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any
import uuid

from app.db.database import get_db_connection, init_db
from app.db.repo import get_analysis, insert_analysis_bundle
from app.engine.evaluate import evaluate_pipeline
from app.engine.models import SchemaError, SchemaValidationError
from app.engine.rules import run_rules_m2
from app.engine.scoring import (
    assign_finding_ids,
    compute_coverage,
    compute_findings_digest,
    compute_gate,
    compute_score,
)
from app.ingestion.loader import (
    build_storage_path,
    load_dataset,
    save_uploaded_file,
)

RULESET_PATH = Path(__file__).resolve().parent / "engine" / "ruleset.json"
SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"

APP_VERSION = "1.0.0"
ENGINE_VERSION = "1.0.0"


def _get_ruleset() -> tuple[dict[str, Any], str]:
    """Load ruleset configuration and compute its SHA-256 hash."""
    content = RULESET_PATH.read_bytes()
    ruleset = json.loads(content.decode("utf-8"))
    sha256 = hashlib.sha256(content).hexdigest()
    return ruleset, sha256


def get_upload_base_dir() -> Path:
    """Return upload directory from environment or default."""
    return Path(os.environ.get("TRACEBRIDGE_UPLOAD_DIR", "data/uploads"))


def create_analysis(
    files: dict[str, tuple[str, bytes]] | None = None,
    sample: str | None = None,
    analysis_id: str | None = None,
    db_path: Path | str | None = None,
    upload_base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Orchestrate end-to-end analysis creation in a single transaction.

    Args:
        files: Optional dict mapping kind ('requirements', 'test_results', 'telemetry')
               to tuple (original_filename, file_bytes).
        sample: Optional sample name ('clean' or 'fault').
        analysis_id: Optional custom analysis_id (generated if omitted).
        db_path: Optional custom SQLite database path.
        upload_base_dir: Optional base directory for file uploads.

    Returns:
        The created analysis record dict.

    Raises:
        SchemaValidationError: If any file fails schema checks SCH-001..SCH-007.
        ValueError: If input arguments are invalid.
    """
    # 1. Resolve inputs
    raw_files: dict[str, tuple[str, bytes]] = {}

    if sample in ("clean", "fault"):
        sample_dir = SAMPLES_DIR / sample
        for kind in ("requirements", "test_results", "telemetry"):
            path = sample_dir / f"{kind}.csv"
            if not path.exists():
                raise FileNotFoundError(f"Sample file not found: {path}")
            raw_files[kind] = (f"{kind}.csv", path.read_bytes())
    elif files:
        raw_files = files
    else:
        raise ValueError("Either 'files' or a valid 'sample' (clean|fault) must be provided.")

    # Check that all 3 kinds are present
    missing_kinds = [k for k in ("requirements", "test_results", "telemetry") if k not in raw_files]
    if missing_kinds:
        errors = [
            SchemaError(
                code="SCH-004",
                message=f"Missing mandatory dataset: {k}",
                details=[f"Dataset kind {k!r} was not uploaded."],
            )
            for k in missing_kinds
        ]
        raise SchemaValidationError(errors)

    # 2. Schema validation on all datasets
    # Collect all errors across files before proceeding
    loaded_datasets: dict[str, Any] = {}
    schema_errors: list[SchemaError] = []

    for kind in ("requirements", "test_results", "telemetry"):
        orig_name, content = raw_files[kind]
        try:
            ds = load_dataset(content, orig_name, kind)
            loaded_datasets[kind] = ds
        except SchemaValidationError as exc:
            schema_errors.extend(exc.errors)

    if schema_errors:
        # Schema rejection: creates NO analysis row and NO stored files
        raise SchemaValidationError(schema_errors)

    req_ds = loaded_datasets["requirements"]
    test_ds = loaded_datasets["test_results"]
    tel_ds = loaded_datasets["telemetry"]

    # 3. Load ruleset and run validation engine
    ruleset, ruleset_sha256 = _get_ruleset()

    m2_findings = run_rules_m2(req_ds, test_ds, tel_ds, ruleset)
    evals, m3_findings = evaluate_pipeline(req_ds, test_ds, tel_ds, m2_findings, ruleset)
    all_findings = m2_findings + m3_findings

    if not analysis_id:
        analysis_id = f"ANL-{uuid.uuid4().hex[:8].upper()}"

    numbered_findings, resolved_evals = assign_finding_ids(all_findings, evals, analysis_id)
    score_res = compute_score(req_ds, test_ds, tel_ds, numbered_findings, resolved_evals)
    gate = compute_gate(numbered_findings, resolved_evals)
    coverage = compute_coverage(req_ds, test_ds, numbered_findings, resolved_evals)
    findings_digest = compute_findings_digest(numbered_findings)

    # Input fingerprint: hash of sorted dataset kind:sha256
    fingerprint_raw = "|".join(
        f"{kind}:{loaded_datasets[kind].sha256}"
        for kind in ("requirements", "test_results", "telemetry")
    )
    input_fingerprint = hashlib.sha256(fingerprint_raw.encode("utf-8")).hexdigest()

    records_processed = req_ds.row_count + test_ds.row_count + tel_ds.row_count
    created_at = datetime.now(timezone.utc).isoformat()

    # 4. Safe file storage
    base_upload = Path(upload_base_dir) if upload_base_dir is not None else get_upload_base_dir()
    stored_paths: dict[str, Path] = {}
    dest_dir = base_upload / analysis_id
    try:
        for kind in ("requirements", "test_results", "telemetry"):
            _, content = raw_files[kind]
            dest = save_uploaded_file(content, analysis_id, kind, base_dir=base_upload)
            stored_paths[kind] = dest

        # 5. Database persistence in one transaction
        init_db(db_path)
        conn = get_db_connection(db_path)

        analysis_bundle = {
            "id": analysis_id,
            "created_at": created_at,
            "versions": {
                "app": APP_VERSION,
                "engine": ENGINE_VERSION,
                "python": "3.13",
            },
            "ruleset_sha256": ruleset_sha256,
            "input_fingerprint": input_fingerprint,
            "findings_digest": findings_digest,
            "records_processed": records_processed,
            "finding_count": len(numbered_findings),
            "gate": gate,
            "quality_score": str(score_res.score),
            "score_breakdown": score_res.model_dump(mode="json"),
            "coverage": coverage,
            "evaluations": [e.model_dump(mode="json") for e in resolved_evals],
        }

        dataset_records = [
            {
                "kind": kind,
                "original_filename": raw_files[kind][0],
                "stored_path": str(stored_paths[kind]),
                "size_bytes": len(raw_files[kind][1]),
                "sha256": loaded_datasets[kind].sha256,
                "row_count": loaded_datasets[kind].row_count,
                "ignored_columns": loaded_datasets[kind].ignored_columns,
                "trim_count": loaded_datasets[kind].trim_count,
            }
            for kind in ("requirements", "test_results", "telemetry")
        ]

        finding_records = [f.model_dump(mode="json") for f in numbered_findings]

        insert_analysis_bundle(conn, analysis_bundle, dataset_records, finding_records)
        created_record = get_analysis(conn, analysis_id)
        conn.close()

        if created_record is None:
            raise RuntimeError(f"Failed to retrieve created analysis {analysis_id}")
        return created_record

    except Exception:
        # Clean up files on error
        if dest_dir.exists():
            shutil.rmtree(dest_dir, ignore_errors=True)
        raise
