"""SQLite database connection and schema initialization for TraceBridge."""

import os
from pathlib import Path
import sqlite3
from typing import Generator

DEFAULT_DB_PATH = Path("data/tracebridge.db")


def get_db_path() -> Path:
    """Return active database path from environment or default."""
    env_path = os.environ.get("TRACEBRIDGE_DB_PATH")
    if env_path:
        return Path(env_path)
    return DEFAULT_DB_PATH


def get_db_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Create a new SQLite connection with foreign keys enabled and row factory set."""
    path = Path(db_path) if db_path is not None else get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path | str | None = None) -> None:
    """Initialize SQLite tables per SPEC section 9."""
    conn = get_db_connection(db_path)
    with conn:
        conn.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS analyses (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                versions_json TEXT NOT NULL,
                ruleset_sha256 TEXT NOT NULL,
                input_fingerprint TEXT NOT NULL,
                findings_digest TEXT NOT NULL,
                records_processed INTEGER NOT NULL,
                finding_count INTEGER NOT NULL,
                gate TEXT NOT NULL,
                quality_score TEXT NOT NULL,
                score_json TEXT NOT NULL,
                coverage_json TEXT NOT NULL,
                evaluations_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS datasets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_id TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
                kind TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                sha256 TEXT NOT NULL,
                row_count INTEGER NOT NULL,
                ignored_columns_json TEXT NOT NULL,
                trim_count INTEGER NOT NULL
            );

            -- Findings are immutable after insert
            CREATE TABLE IF NOT EXISTS findings (
                id TEXT PRIMARY KEY,
                analysis_id TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
                rule_id TEXT NOT NULL,
                variant TEXT,
                severity TEXT NOT NULL,
                finding_class TEXT NOT NULL,
                entity_key TEXT NOT NULL,
                description TEXT NOT NULL,
                expected TEXT,
                actual TEXT,
                source_refs_json TEXT NOT NULL,
                truncated INTEGER NOT NULL DEFAULT 0
            );

            -- Reviews stored in separate table
            CREATE TABLE IF NOT EXISTS finding_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                finding_id TEXT NOT NULL UNIQUE REFERENCES findings(id) ON DELETE CASCADE,
                review_status TEXT NOT NULL DEFAULT 'unreviewed',
                reviewer_note TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS exports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_id TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
                format TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                byte_size INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_datasets_analysis ON datasets(analysis_id);
            CREATE INDEX IF NOT EXISTS idx_findings_analysis ON findings(analysis_id);
            CREATE INDEX IF NOT EXISTS idx_findings_rule ON findings(rule_id);
            CREATE INDEX IF NOT EXISTS idx_findings_severity ON findings(severity);
            CREATE INDEX IF NOT EXISTS idx_reviews_finding ON finding_reviews(finding_id);
            CREATE INDEX IF NOT EXISTS idx_exports_analysis ON exports(analysis_id);
            """
        )
    conn.close()
