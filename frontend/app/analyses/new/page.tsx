'use client';

import React, { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { createAnalysisFromSample, createAnalysisFromFiles, ApiError, getSampleZipUrl } from '../../../lib/api';

export default function NewAnalysisPage() {
  const router = useRouter();

  const [reqFile, setReqFile] = useState<File | null>(null);
  const [testFile, setTestFile] = useState<File | null>(null);
  const [telFile, setTelFile] = useState<File | null>(null);

  const [submitting, setSubmitting] = useState(false);
  const [errorHeader, setErrorHeader] = useState<string | null>(null);
  const [errorDetails, setErrorDetails] = useState<string[]>([]);

  const handleRunSample = async (sample: 'clean' | 'fault') => {
    setSubmitting(true);
    setErrorHeader(null);
    setErrorDetails([]);

    try {
      const result = await createAnalysisFromSample(sample);
      router.push(`/analyses/${result.id}`);
    } catch (err) {
      setSubmitting(false);
      if (err instanceof ApiError) {
        setErrorHeader(`${err.code}: ${err.message}`);
        setErrorDetails(err.details);
      } else {
        setErrorHeader((err as Error).message);
      }
    }
  };

  const handleFileUploadSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!reqFile || !testFile || !telFile) {
      setErrorHeader('Missing files');
      setErrorDetails(['Please select all 3 CSV files (requirements.csv, test_results.csv, telemetry.csv).']);
      return;
    }

    setSubmitting(true);
    setErrorHeader(null);
    setErrorDetails([]);

    try {
      const result = await createAnalysisFromFiles(reqFile, testFile, telFile);
      router.push(`/analyses/${result.id}`);
    } catch (err) {
      setSubmitting(false);
      if (err instanceof ApiError) {
        setErrorHeader(`${err.code}: ${err.message}`);
        setErrorDetails(err.details);
      } else {
        setErrorHeader((err as Error).message);
      }
    }
  };

  return (
    <div>
      <div style={{ marginBottom: '2rem' }}>
        <Link href="/" style={{ color: 'var(--text-muted)', fontSize: '0.875rem' }}>
          ← Back to Dashboard
        </Link>
        <h1 style={{ fontSize: '1.75rem', fontWeight: 700, color: '#ffffff', marginTop: '0.5rem' }}>
          Start New Validation Analysis
        </h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginTop: '0.25rem' }}>
          Upload your engineering datasets or run pre-packaged test fixtures.
        </p>
      </div>

      {errorHeader && (
        <div className="alert alert-error">
          <div className="alert-title">{errorHeader}</div>
          {errorDetails.length > 0 && (
            <ul className="alert-details-list">
              {errorDetails.map((d, i) => (
                <li key={i} style={{ marginTop: '0.25rem' }}>
                  {d}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Quick Run Section */}
      <div className="card">
        <div className="card-title">
          <span>⚡ One-Click Preloaded Samples</span>
          <div style={{ display: 'flex', gap: '0.75rem' }}>
            <a
              href={getSampleZipUrl('clean')}
              download
              className="btn btn-secondary"
              style={{ fontSize: '0.75rem', padding: '0.35rem 0.75rem' }}
            >
              📥 Download Clean ZIP
            </a>
            <a
              href={getSampleZipUrl('fault')}
              download
              className="btn btn-secondary"
              style={{ fontSize: '0.75rem', padding: '0.35rem 0.75rem' }}
            >
              📥 Download Fault ZIP
            </a>
          </div>
        </div>
        <p style={{ color: 'var(--text-muted)', fontSize: '0.875rem', marginBottom: '1.25rem' }}>
          Run official deterministic fixtures to inspect standard compliance or faulty conditions.
        </p>

        <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
          <button
            type="button"
            className="btn btn-sample-clean"
            disabled={submitting}
            onClick={() => handleRunSample('clean')}
            style={{ flex: 1, minWidth: '220px', padding: '1rem' }}
          >
            {submitting ? 'Running...' : 'Run Clean Sample (Score 100.0, Not Blocked)'}
          </button>

          <button
            type="button"
            className="btn btn-sample-fault"
            disabled={submitting}
            onClick={() => handleRunSample('fault')}
            style={{ flex: 1, minWidth: '220px', padding: '1rem' }}
          >
            {submitting ? 'Running...' : 'Run Fault Sample (Score 73.3, Blocked Critical)'}
          </button>
        </div>
      </div>

      {/* File Upload Section */}
      <div className="card">
        <div className="card-title">📁 Upload Engineering Datasets</div>
        <p style={{ color: 'var(--text-muted)', fontSize: '0.875rem', marginBottom: '1.5rem' }}>
          CSVs are parsed strictly as UTF-8 text with headers. All schema checks (SCH-001..SCH-007) are evaluated before saving.
        </p>

        <form onSubmit={handleFileUploadSubmit}>
          <div className="upload-grid">
            {/* 1. Requirements CSV */}
            <label className={`dropzone ${reqFile ? 'has-file' : ''}`}>
              <input
                type="file"
                accept=".csv"
                style={{ display: 'none' }}
                onChange={(e) => {
                  if (e.target.files?.[0]) setReqFile(e.target.files[0]);
                }}
              />
              <div className="dropzone-icon">📋</div>
              <div className="dropzone-label">requirements.csv</div>
              <div className="dropzone-hint">
                Columns: requirement_id, signal_name, operator, threshold_value, unit
              </div>
              {reqFile && <div className="file-selected-name">✓ {reqFile.name} ({(reqFile.size / 1024).toFixed(1)} KB)</div>}
            </label>

            {/* 2. Test Results CSV */}
            <label className={`dropzone ${testFile ? 'has-file' : ''}`}>
              <input
                type="file"
                accept=".csv"
                style={{ display: 'none' }}
                onChange={(e) => {
                  if (e.target.files?.[0]) setTestFile(e.target.files[0]);
                }}
              />
              <div className="dropzone-icon">🧪</div>
              <div className="dropzone-label">test_results.csv</div>
              <div className="dropzone-hint">
                Columns: test_id, requirement_id, run_id, status, started_at, completed_at, actual_result, unit
              </div>
              {testFile && <div className="file-selected-name">✓ {testFile.name} ({(testFile.size / 1024).toFixed(1)} KB)</div>}
            </label>

            {/* 3. Telemetry CSV */}
            <label className={`dropzone ${telFile ? 'has-file' : ''}`}>
              <input
                type="file"
                accept=".csv"
                style={{ display: 'none' }}
                onChange={(e) => {
                  if (e.target.files?.[0]) setTelFile(e.target.files[0]);
                }}
              />
              <div className="dropzone-icon">📈</div>
              <div className="dropzone-label">telemetry.csv</div>
              <div className="dropzone-hint">
                Columns: run_id, timestamp, signal_name, value, unit
              </div>
              {telFile && <div className="file-selected-name">✓ {telFile.name} ({(telFile.size / 1024).toFixed(1)} KB)</div>}
            </label>
          </div>

          <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '1.5rem' }}>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={submitting || !reqFile || !testFile || !telFile}
              style={{ minWidth: '200px' }}
            >
              {submitting ? 'Validating Datasets...' : 'Run Analysis →'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
