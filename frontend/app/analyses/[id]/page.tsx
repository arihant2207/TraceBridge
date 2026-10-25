'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import {
  getAnalysis,
  getFindings,
  getCoverage,
  updateFindingReview,
  AnalysisDetail,
  FindingResponse,
  FindingFilters,
  ApiError,
} from '../../../lib/api';
import { ScoreGateHeader } from '../../../components/ScoreGateHeader';

interface CheckScoreItem {
  rule_id?: string;
  applicable: number;
  failing: number;
  pass_rate?: string | null;
}

interface SourceRefItem {
  file?: string;
  row_number?: number | string;
  record_id?: string;
  fields?: Record<string, unknown>;
}

export default function AnalysisDetailPage() {
  const params = useParams();
  const analysisId = params?.id as string;

  const [analysis, setAnalysis] = useState<AnalysisDetail | null>(null);
  const [findings, setFindings] = useState<FindingResponse[]>([]);
  const [selectedFinding, setSelectedFinding] = useState<FindingResponse | null>(null);

  const [loadingAnalysis, setLoadingAnalysis] = useState(true);
  const [loadingFindings, setLoadingFindings] = useState(false);
  const [analysisError, setAnalysisError] = useState<{ code: string; message: string; details: string[] } | null>(null);

  // Coverage state
  const [coverage, setCoverage] = useState<Record<string, string> | null>(null);
  const [loadingCoverage, setLoadingCoverage] = useState(true);
  const [coverageError, setCoverageError] = useState<{ code: string; message: string; details: string[] } | null>(null);

  // Filters
  const [severityFilter, setSeverityFilter] = useState('all');
  const [ruleFilter, setRuleFilter] = useState('all');
  const [classFilter, setClassFilter] = useState('all');
  const [reviewFilter, setReviewFilter] = useState('all');

  // Review editing state
  const [reviewStatusInput, setReviewStatusInput] = useState<'unreviewed' | 'reviewed'>('unreviewed');
  const [reviewerNoteInput, setReviewerNoteInput] = useState('');
  const [savingReview, setSavingReview] = useState(false);
  const [reviewSuccessMsg, setReviewSuccessMsg] = useState<string | null>(null);
  const [reviewErrorMsg, setReviewErrorMsg] = useState<string | null>(null);

  // Load Analysis Detail
  useEffect(() => {
    if (!analysisId) return;
    setLoadingAnalysis(true);
    setAnalysisError(null);

    getAnalysis(analysisId)
      .then((data) => {
        setAnalysis(data);
        setLoadingAnalysis(false);
      })
      .catch((err) => {
        if (err instanceof ApiError) {
          setAnalysisError({ code: err.code, message: err.message, details: err.details });
        } else {
          setAnalysisError({ code: 'ERROR', message: (err as Error).message, details: [] });
        }
        setLoadingAnalysis(false);
      });
  }, [analysisId]);

  // Load Coverage Data
  useEffect(() => {
    if (!analysisId) return;
    setLoadingCoverage(true);
    setCoverageError(null);

    getCoverage(analysisId)
      .then((data) => {
        setCoverage(data);
        setLoadingCoverage(false);
      })
      .catch((err) => {
        if (err instanceof ApiError) {
          setCoverageError({ code: err.code, message: err.message, details: err.details });
        } else {
          setCoverageError({ code: 'ERROR', message: (err as Error).message, details: [] });
        }
        setLoadingCoverage(false);
      });
  }, [analysisId]);

  // Load Findings with filters
  useEffect(() => {
    if (!analysisId) return;
    setLoadingFindings(true);

    const filters: FindingFilters = {
      severity: severityFilter,
      rule_id: ruleFilter,
      class: classFilter,
      review_status: reviewFilter,
    };

    getFindings(analysisId, filters)
      .then((data) => {
        setFindings(data);
        setLoadingFindings(false);

        // Keep selected finding up to date or select first
        setSelectedFinding((current) => {
          if (!current) return data[0] || null;
          const updated = data.find((f) => f.id === current.id);
          return updated || data[0] || null;
        });
      })
      .catch((err) => {
        console.error('Failed to load findings:', err);
        setLoadingFindings(false);
      });
  }, [analysisId, severityFilter, ruleFilter, classFilter, reviewFilter]);

  // Sync selected finding with review form inputs
  useEffect(() => {
    if (selectedFinding) {
      setReviewStatusInput(
        selectedFinding.review_status === 'reviewed' ? 'reviewed' : 'unreviewed'
      );
      setReviewerNoteInput(selectedFinding.reviewer_note || '');
      setReviewSuccessMsg(null);
      setReviewErrorMsg(null);
    }
  }, [selectedFinding]);

  const handleSaveReview = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedFinding) return;

    setSavingReview(true);
    setReviewSuccessMsg(null);
    setReviewErrorMsg(null);

    try {
      const updated = await updateFindingReview(selectedFinding.id, {
        review_status: reviewStatusInput,
        reviewer_note: reviewerNoteInput,
      });

      // Update in findings list
      setFindings((prev) =>
        prev.map((f) =>
          f.id === selectedFinding.id
            ? {
                ...f,
                review_status: updated.review_status,
                reviewer_note: updated.reviewer_note,
                review_updated_at: updated.updated_at,
              }
            : f
        )
      );

      // Update selected finding
      setSelectedFinding((prev) =>
        prev && prev.id === selectedFinding.id
          ? {
              ...prev,
              review_status: updated.review_status,
              reviewer_note: updated.reviewer_note,
              review_updated_at: updated.updated_at,
            }
          : prev
      );

      setReviewSuccessMsg('Review recorded successfully.');
    } catch (err) {
      if (err instanceof ApiError) {
        setReviewErrorMsg(`[${err.code}] ${err.message}`);
      } else {
        setReviewErrorMsg(`[ERROR] ${(err as Error).message}`);
      }
    } finally {
      setSavingReview(false);
    }
  };

  if (loadingAnalysis) {
    return (
      <div className="card" style={{ textAlign: 'center', padding: '3rem 1rem', color: 'var(--text-muted)' }}>
        Loading analysis {analysisId}...
      </div>
    );
  }

  if (analysisError || !analysis) {
    return (
      <div>
        <div style={{ marginBottom: '1rem' }}>
          <Link href="/" style={{ color: 'var(--text-muted)', fontSize: '0.8125rem' }}>
            ← Back to Dashboard
          </Link>
        </div>
        <div className="alert alert-error">
          <div className="alert-title">{analysisError ? `[${analysisError.code}] Analysis Error` : 'Analysis Not Found'}</div>
          <div>{analysisError ? analysisError.message : `Analysis ${analysisId} could not be loaded.`}</div>
          {analysisError && analysisError.details.length > 0 && (
            <ul className="alert-details-list">
              {analysisError.details.map((d, i) => (
                <li key={i}>{d}</li>
              ))}
            </ul>
          )}
        </div>
      </div>
    );
  }

  const scoreChecks = (
    analysis?.score_breakdown &&
    typeof analysis.score_breakdown === 'object' &&
    'checks' in analysis.score_breakdown &&
    analysis.score_breakdown.checks
      ? (analysis.score_breakdown.checks as Record<string, CheckScoreItem>)
      : {}
  );
  const unresolvedNote = (analysis as unknown as { unresolved?: string | string[] }).unresolved;

  const COVERAGE_STATUS_ORDER = [
    'NOT_COVERED',
    'NOT_EXECUTED',
    'CONTRADICTORY',
    'VIOLATED',
    'INCONCLUSIVE',
    'SATISFIED',
  ] as const;

  const coverageEntries = Object.entries(coverage || {}).sort(([a], [b]) => a.localeCompare(b));
  const totalRequirements = coverageEntries.length;

  const coverageCounts: Record<string, number> = {
    NOT_COVERED: 0,
    NOT_EXECUTED: 0,
    CONTRADICTORY: 0,
    VIOLATED: 0,
    INCONCLUSIVE: 0,
    SATISFIED: 0,
  };

  for (const [, status] of coverageEntries) {
    if (status in coverageCounts) {
      coverageCounts[status] = (coverageCounts[status] || 0) + 1;
    } else {
      coverageCounts[status] = 1;
    }
  }

  // Meaning-driven colors only (no green)
  const getCoverageColor = (status: string) => {
    switch (status) {
      case 'CONTRADICTORY':
        return '#dc2626'; // Muted red
      case 'VIOLATED':
        return '#d97706'; // Amber/orange
      case 'INCONCLUSIVE':
        return '#f59e0b'; // Amber
      case 'NOT_EXECUTED':
        return '#64748b'; // Slate gray
      case 'NOT_COVERED':
        return '#9ca3af'; // Neutral gray
      case 'SATISFIED':
        return '#2563eb'; // Muted blue - never green
      default:
        return '#94a3b8';
    }
  };

  return (
    <div>
      {/* Top Header */}
      <div style={{ marginBottom: '1.25rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '0.75rem' }}>
          <div>
            <Link href="/" style={{ color: 'var(--text-muted)', fontSize: '0.8125rem' }}>
              ← Back to Dashboard
            </Link>
            <h1 style={{ fontSize: '1.5rem', fontWeight: 600, color: 'var(--text-primary)', margin: '0.25rem 0 0 0' }}>
              Analysis <span className="mono">{analysis.id}</span>
            </h1>
            <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem', marginTop: '0.2rem' }}>
              Created: {analysis.created_at.replace('T', ' ').slice(0, 19)} UTC | Records Processed: {analysis.records_processed}
            </div>
          </div>
          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
            <Link href={`/analyses/${analysis.id}/report`} className="btn btn-secondary">
              View report (Markdown)
            </Link>
            <Link href="/analyses/new" className="btn btn-primary">
              New analysis
            </Link>
          </div>
        </div>
      </div>

      {/* Score and Gate */}
      <ScoreGateHeader score={analysis.quality_score} gate={analysis.gate} />

      {/* UNRESOLVED note if provided by API */}
      {unresolvedNote && (
        <div className="alert alert-warning">
          <div className="alert-title">UNRESOLVED Engineering Verification Questions</div>
          {Array.isArray(unresolvedNote) ? (
            <ul className="alert-details-list">
              {unresolvedNote.map((item, idx) => (
                <li key={idx}>{item}</li>
              ))}
            </ul>
          ) : (
            <div>{unresolvedNote}</div>
          )}
        </div>
      )}

      {/* Requirement Coverage Section */}
      <div className="card">
        <div className="card-title">
          <span>Requirement Coverage</span>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 'normal' }}>
            Status distribution and verification results
          </span>
        </div>

        {loadingCoverage ? (
          <div style={{ textAlign: 'center', padding: '1.5rem', color: 'var(--text-muted)' }}>
            Loading requirement coverage data...
          </div>
        ) : coverageError ? (
          <div className="alert alert-error" style={{ margin: '0.75rem 0' }}>
            <div className="alert-title">[{coverageError.code}] Failed to load coverage</div>
            <div>{coverageError.message}</div>
          </div>
        ) : totalRequirements === 0 ? (
          <div style={{ textAlign: 'center', padding: '1.5rem', color: 'var(--text-muted)' }}>
            No requirement coverage records recorded for this analysis.
          </div>
        ) : (
          <div>
            {/* Horizontal Distribution Bar */}
            <div className="coverage-bar-wrapper">
              <div className="coverage-bar">
                {COVERAGE_STATUS_ORDER.map((status) => {
                  const count = coverageCounts[status] || 0;
                  if (count === 0) return null;
                  const pct = (count / totalRequirements) * 100;
                  return (
                    <div
                      key={status}
                      className="coverage-segment"
                      style={{
                        width: `${pct}%`,
                        backgroundColor: getCoverageColor(status),
                      }}
                      title={`${status}: ${count} (${pct.toFixed(1)}%)`}
                    />
                  );
                })}
              </div>
            </div>

            {/* Legend with Counts */}
            <div className="coverage-legend">
              {COVERAGE_STATUS_ORDER.map((status) => {
                const count = coverageCounts[status] || 0;
                const color = getCoverageColor(status);
                const label = status === 'SATISFIED' ? 'satisfied by recorded evidence' : status;
                return (
                  <div key={status} className="coverage-legend-item">
                    <span className="coverage-legend-color" style={{ backgroundColor: color }} />
                    <span style={{ fontWeight: 500, color: 'var(--text-secondary)' }}>
                      {label}:
                    </span>
                    <span className="mono" style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
                      {count}
                    </span>
                  </div>
                );
              })}
            </div>

            {/* Requirements Table */}
            <div className="table-container" style={{ marginTop: '1rem' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Requirement ID</th>
                    <th>Status</th>
                    <th>Per-Test Outcomes</th>
                  </tr>
                </thead>
                <tbody>
                  {coverageEntries.map(([reqId, status]) => {
                    const color = getCoverageColor(status);
                    const label = status === 'SATISFIED' ? 'satisfied by recorded evidence' : status;
                    return (
                      <tr key={reqId}>
                        <td className="mono" style={{ fontWeight: 600 }}>
                          {reqId}
                        </td>
                        <td>
                          <span
                            style={{
                              display: 'inline-block',
                              padding: '0.15rem 0.45rem',
                              borderRadius: '4px',
                              fontSize: '0.75rem',
                              fontWeight: 500,
                              color: color,
                              border: `1px solid ${color}44`,
                              backgroundColor: `${color}11`,
                            }}
                          >
                            {label}
                          </span>
                        </td>
                        <td style={{ color: 'var(--text-muted)' }}>N/A</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* Quality Score Checks (11 Scored Rules) */}
      <div className="card">
        <div className="card-title">
          <span>Quality Score Checks (11 rules)</span>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 'normal' }}>
            Equal weights | R09 excluded
          </span>
        </div>
        <div className="checks-grid">
          {Object.keys(scoreChecks).sort().map((ruleId) => {
            const check = scoreChecks[ruleId];
            const isFailing = check.failing > 0;
            return (
              <div key={ruleId} className="check-card">
                <div className="check-header">
                  <span className="check-rule">{ruleId}</span>
                  {isFailing ? (
                    <span className="check-fail">{check.failing} failing</span>
                  ) : (
                    <span className="check-pass">Clean</span>
                  )}
                </div>
                <div className="check-counts">
                  Applicable: {check.applicable} | Failing: {check.failing}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Provenance & Datasets */}
      <div className="card">
        <div className="card-title">Provenance & Datasets</div>
        <div className="detail-grid" style={{ marginBottom: '0.75rem' }}>
          <div className="detail-item">
            <div className="detail-item-label">Versions</div>
            <div className="detail-item-value mono">
              app: {analysis.versions?.app || '1.0.0'} | engine: {analysis.versions?.engine || '1.0.0'} | python: {analysis.versions?.python || '3.13'}
            </div>
          </div>
          <div className="detail-item">
            <div className="detail-item-label">Ruleset SHA-256</div>
            <div className="detail-item-value mono" style={{ fontSize: '0.75rem' }}>
              {analysis.ruleset_sha256}
            </div>
          </div>
          <div className="detail-item">
            <div className="detail-item-label">Findings Digest</div>
            <div className="detail-item-value mono" style={{ fontSize: '0.75rem' }}>
              {analysis.findings_digest}
            </div>
          </div>
          <div className="detail-item">
            <div className="detail-item-label">Input Fingerprint</div>
            <div className="detail-item-value mono" style={{ fontSize: '0.75rem' }}>
              {analysis.input_fingerprint}
            </div>
          </div>
        </div>

        <div className="table-container">
          <table className="data-table">
            <thead>
              <tr>
                <th>Dataset Kind</th>
                <th>Original Filename</th>
                <th>Rows</th>
                <th>Size (bytes)</th>
                <th>SHA-256</th>
                <th>Ignored Columns</th>
                <th>Trim Count</th>
              </tr>
            </thead>
            <tbody>
              {(analysis.datasets || []).map((ds) => (
                <tr key={ds.kind}>
                  <td style={{ fontWeight: 600 }}>{ds.kind}</td>
                  <td className="mono">{ds.original_filename}</td>
                  <td className="mono">{ds.row_count}</td>
                  <td className="mono">{ds.size_bytes}</td>
                  <td className="mono" style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                    {ds.sha256}
                  </td>
                  <td style={{ color: 'var(--text-muted)' }}>
                    {ds.ignored_columns && ds.ignored_columns.length > 0
                      ? ds.ignored_columns.join(', ')
                      : 'none'}
                  </td>
                  <td className="mono">{ds.trim_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Findings Table with Filters */}
      <div className="card">
        <div className="card-title">
          <span>Findings (Total: {analysis.finding_count})</span>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 'normal' }}>
            Select a row to inspect source evidence and record review
          </span>
        </div>

        {/* Filters Bar */}
        <div className="filters-bar">
          <div className="filter-group">
            <label className="filter-label">Severity</label>
            <select
              className="filter-select"
              value={severityFilter}
              onChange={(e) => setSeverityFilter(e.target.value)}
            >
              <option value="all">All Severities</option>
              <option value="critical">Critical</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
          </div>

          <div className="filter-group">
            <label className="filter-label">Rule ID</label>
            <select
              className="filter-select"
              value={ruleFilter}
              onChange={(e) => setRuleFilter(e.target.value)}
            >
              <option value="all">All Rules</option>
              {['R01', 'R02', 'R03', 'R04', 'R05', 'R06', 'R07', 'R08', 'R09', 'R10', 'R11', 'R12'].map(
                (r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                )
              )}
            </select>
          </div>

          <div className="filter-group">
            <label className="filter-label">Finding Class</label>
            <select
              className="filter-select"
              value={classFilter}
              onChange={(e) => setClassFilter(e.target.value)}
            >
              <option value="all">All Classes</option>
              <option value="VALIDATION_FAILURE">VALIDATION_FAILURE</option>
              <option value="MISSING_EVIDENCE">MISSING_EVIDENCE</option>
              <option value="OBSERVATION">OBSERVATION</option>
            </select>
          </div>

          <div className="filter-group">
            <label className="filter-label">Review Status</label>
            <select
              className="filter-select"
              value={reviewFilter}
              onChange={(e) => setReviewFilter(e.target.value)}
            >
              <option value="all">All Statuses</option>
              <option value="unreviewed">Unreviewed</option>
              <option value="reviewed">Reviewed</option>
            </select>
          </div>

          <div style={{ flex: 1 }} />

          {(severityFilter !== 'all' || ruleFilter !== 'all' || classFilter !== 'all' || reviewFilter !== 'all') && (
            <button
              type="button"
              className="btn btn-secondary"
              style={{ fontSize: '0.75rem', padding: '0.25rem 0.6rem' }}
              onClick={() => {
                setSeverityFilter('all');
                setRuleFilter('all');
                setClassFilter('all');
                setReviewFilter('all');
              }}
            >
              Reset Filters
            </button>
          )}
        </div>

        {/* Findings Data Table */}
        {loadingFindings ? (
          <div style={{ textAlign: 'center', padding: '1.5rem', color: 'var(--text-muted)' }}>
            Loading findings...
          </div>
        ) : findings.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '2.5rem 1rem', color: 'var(--text-muted)' }}>
            <div style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: '0.25rem' }}>
              No findings match the selected filters.
            </div>
            <div style={{ fontSize: '0.75rem' }}>
              Adjust filter values above or click Reset Filters.
            </div>
          </div>
        ) : (
          <div className="table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Finding ID</th>
                  <th>Rule</th>
                  <th>Severity</th>
                  <th>Class</th>
                  <th>Entity Key</th>
                  <th>Description</th>
                  <th>Review</th>
                </tr>
              </thead>
              <tbody>
                {findings.map((f) => {
                  const isSelected = selectedFinding?.id === f.id;
                  const isObservation = f.finding_class === 'OBSERVATION';

                  let sevClass = 'severity-badge';
                  if (f.severity === 'critical') sevClass += ' severity-critical';
                  else if (f.severity === 'high') sevClass += ' severity-high';
                  else if (f.severity === 'medium') sevClass += ' severity-medium';
                  else sevClass += ' severity-low';

                  let clsClass = 'class-badge';
                  if (isObservation) clsClass += ' class-observation';
                  else if (f.finding_class === 'MISSING_EVIDENCE') clsClass += ' class-missing';
                  else clsClass += ' class-validation';

                  return (
                    <tr
                      key={f.id}
                      className={isSelected ? 'selected-row' : ''}
                      style={{ cursor: 'pointer' }}
                      onClick={() => setSelectedFinding(f)}
                    >
                      <td className="mono" style={{ fontWeight: 600 }}>
                        {f.id}
                      </td>
                      <td className="mono">
                        {f.rule_id}
                        {f.variant ? ` (${f.variant})` : ''}
                      </td>
                      <td>
                        <span className={sevClass}>{f.severity}</span>
                      </td>
                      <td>
                        <span className={clsClass}>
                          {isObservation ? 'Observation' : f.finding_class}
                        </span>
                      </td>
                      <td className="mono">{f.entity_key}</td>
                      <td style={{ maxWidth: '380px', wordBreak: 'break-word' }}>{f.description}</td>
                      <td>
                        <span
                          className={`review-badge ${
                            f.review_status === 'reviewed' ? 'review-reviewed' : 'review-unreviewed'
                          }`}
                        >
                          {f.review_status}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Finding Detail Panel */}
      {selectedFinding && (
        <div className="detail-panel" id="finding-detail-panel">
          <div className="detail-header">
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                <span className="mono" style={{ fontSize: '1.125rem', fontWeight: 700, color: 'var(--text-primary)' }}>
                  {selectedFinding.id}
                </span>
                <span className="mono" style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
                  Rule {selectedFinding.rule_id}
                  {selectedFinding.variant ? ` (${selectedFinding.variant})` : ''}
                </span>
                <span
                  className={`severity-badge ${
                    selectedFinding.severity === 'critical'
                      ? 'severity-critical'
                      : selectedFinding.severity === 'high'
                      ? 'severity-high'
                      : 'severity-medium'
                  }`}
                >
                  {selectedFinding.severity}
                </span>
                <span
                  className={`class-badge ${
                    selectedFinding.finding_class === 'OBSERVATION'
                      ? 'class-observation'
                      : selectedFinding.finding_class === 'MISSING_EVIDENCE'
                      ? 'class-missing'
                      : 'class-validation'
                  }`}
                >
                  {selectedFinding.finding_class === 'OBSERVATION'
                    ? 'Observation'
                    : selectedFinding.finding_class}
                </span>
              </div>
              <div style={{ color: 'var(--text-secondary)', marginTop: '0.4rem', fontSize: '0.875rem' }}>
                {selectedFinding.description}
              </div>
            </div>
            <span
              className={`review-badge ${
                selectedFinding.review_status === 'reviewed' ? 'review-reviewed' : 'review-unreviewed'
              }`}
            >
              {selectedFinding.review_status}
            </span>
          </div>

          <div className="detail-grid">
            <div className="detail-item">
              <div className="detail-item-label">Target Entity Key</div>
              <div className="detail-item-value mono">{selectedFinding.entity_key}</div>
            </div>
            <div className="detail-item">
              <div className="detail-item-label">Expected</div>
              <div className="detail-item-value mono">{selectedFinding.expected || 'N/A'}</div>
            </div>
            <div className="detail-item">
              <div className="detail-item-label">Actual</div>
              <div className="detail-item-value mono">{selectedFinding.actual || 'N/A'}</div>
            </div>
          </div>

          {/* Source References Inspector */}
          {(() => {
            const sourceRefs = (selectedFinding.source_refs as SourceRefItem[] | undefined) || [];
            return (
              <div style={{ marginTop: '1rem' }}>
                <div style={{ fontSize: '0.8125rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '0.5rem' }}>
                  Source References ({sourceRefs.length}
                  {selectedFinding.truncated ? ', truncated at 20' : ''})
                </div>

                {sourceRefs.length === 0 ? (
                  <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>No source row references recorded.</div>
                ) : (
                  sourceRefs.map((ref, idx) => {
                    const fileName = String(ref.file || '');
                    const rowNum = String(ref.row_number ?? '');
                    const recId = String(ref.record_id || '—');
                    const fields = ref.fields || {};

                    return (
                      <div key={idx} className="source-ref-card">
                        <div className="source-ref-header">
                          <span>
                            File: <strong>{fileName}</strong> | Row:{' '}
                            <strong className="mono">{rowNum}</strong>
                          </span>
                          <span className="mono">Record ID: {recId}</span>
                        </div>

                        {Object.keys(fields).length > 0 && (
                          <table className="source-fields-table">
                            <tbody>
                              {Object.entries(fields).map(([fieldName, val]) => (
                                <tr key={fieldName}>
                                  <td className="source-field-name">{fieldName}</td>
                                  <td className="source-field-val">{String(val)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        )}
                      </div>
                    );
                  })
                )}
              </div>
            );
          })()}

          {/* Engineering Review Form */}
          <div
            style={{
              marginTop: '1.25rem',
              paddingTop: '1rem',
              borderTop: '1px solid var(--border-light)',
            }}
          >
            <div style={{ fontSize: '0.8125rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '0.6rem' }}>
              Engineering Review (Isolated Audit Record)
            </div>

            {reviewSuccessMsg && (
              <div className="alert alert-success" style={{ padding: '0.5rem 0.75rem', marginBottom: '0.75rem' }}>
                {reviewSuccessMsg}
              </div>
            )}
            {reviewErrorMsg && (
              <div className="alert alert-error" style={{ padding: '0.5rem 0.75rem', marginBottom: '0.75rem' }}>
                {reviewErrorMsg}
              </div>
            )}

            <form onSubmit={handleSaveReview}>
              <div style={{ display: 'flex', gap: '1.25rem', alignItems: 'center', marginBottom: '0.75rem' }}>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Review Status:</span>
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.8125rem', cursor: 'pointer' }}>
                  <input
                    type="radio"
                    name="review_status"
                    value="unreviewed"
                    checked={reviewStatusInput === 'unreviewed'}
                    onChange={() => setReviewStatusInput('unreviewed')}
                  />
                  Unreviewed
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.8125rem', cursor: 'pointer' }}>
                  <input
                    type="radio"
                    name="review_status"
                    value="reviewed"
                    checked={reviewStatusInput === 'reviewed'}
                    onChange={() => setReviewStatusInput('reviewed')}
                  />
                  Reviewed
                </label>
              </div>

              <div style={{ marginBottom: '0.75rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.2rem' }}>
                  <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Reviewer Note (max 2000 chars):</label>
                  <span style={{ fontSize: '0.75rem', color: reviewerNoteInput.length > 2000 ? 'var(--critical-text)' : 'var(--text-muted)' }}>
                    {reviewerNoteInput.length} / 2000
                  </span>
                </div>
                <textarea
                  className="filter-select"
                  rows={3}
                  maxLength={2000}
                  style={{ width: '100%', resize: 'vertical', padding: '0.5rem' }}
                  value={reviewerNoteInput}
                  onChange={(e) => setReviewerNoteInput(e.target.value)}
                  placeholder="Enter engineer justification or resolution notes..."
                />
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem' }}>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={savingReview || reviewerNoteInput.length > 2000}
                >
                  {savingReview ? 'Saving Review...' : 'Save Review'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
