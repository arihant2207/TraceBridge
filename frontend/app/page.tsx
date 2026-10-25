'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { listAnalyses, AnalysisSummary, ApiError } from '../lib/api';
import { GateBadge } from '../components/ScoreGateHeader';

export default function AnalysesListPage() {
  const [analyses, setAnalyses] = useState<AnalysisSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    listAnalyses()
      .then((data) => {
        if (mounted) {
          setAnalyses(data);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (mounted) {
          setError(err instanceof ApiError ? `${err.code}: ${err.message}` : err.message);
          setLoading(false);
        }
      });
    return () => {
      mounted = false;
    };
  }, []);

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
        <div>
          <h1 style={{ fontSize: '1.75rem', fontWeight: 700, color: '#ffffff' }}>Validation Analyses</h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginTop: '0.25rem' }}>
            Deterministic engineering evidence validation runs
          </p>
        </div>
        <Link href="/analyses/new" className="btn btn-primary">
          + New Analysis
        </Link>
      </div>

      {error && (
        <div className="alert alert-error">
          <div className="alert-title">Failed to load analyses</div>
          <div>{error}</div>
        </div>
      )}

      {loading ? (
        <div className="card" style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-muted)' }}>
          Loading analyses...
        </div>
      ) : analyses.length === 0 ? (
        <div className="card" style={{ textAlign: 'center', padding: '4rem 2rem' }}>
          <div style={{ fontSize: '2.5rem', marginBottom: '1rem' }}>📋</div>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 600, marginBottom: '0.5rem' }}>No Analyses Found</h2>
          <p style={{ color: 'var(--text-muted)', marginBottom: '1.5rem', maxWidth: '450px', margin: '0 auto 1.5rem' }}>
            Run an analysis using the preloaded clean or fault sample datasets, or upload your own engineering CSVs.
          </p>
          <div style={{ display: 'flex', gap: '1rem', justifyContent: 'center' }}>
            <Link href="/analyses/new" className="btn btn-primary">
              Run Sample or Upload Files
            </Link>
          </div>
        </div>
      ) : (
        <div className="card" style={{ padding: 0 }}>
          <div className="table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Analysis ID</th>
                  <th>Created At (UTC)</th>
                  <th>Records</th>
                  <th>Findings</th>
                  <th>Score & Gate</th>
                  <th>Findings Digest</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {analyses.map((anl) => {
                  const isClean = anl.gate === 'NOT_BLOCKED';
                  // Score coloring rule: NEVER styled green unless gate is NOT_BLOCKED
                  let scoreStyle: React.CSSProperties = { fontWeight: 700, fontFamily: 'var(--font-mono)' };
                  if (isClean) {
                    scoreStyle.color = '#34d399';
                  } else if (anl.gate.includes('CRITICAL')) {
                    scoreStyle.color = '#f87171';
                  } else {
                    scoreStyle.color = '#fbbf24';
                  }

                  return (
                    <tr key={anl.id}>
                      <td className="mono" style={{ fontWeight: 600 }}>
                        <Link href={`/analyses/${anl.id}`} style={{ color: 'var(--accent-cyan)' }}>
                          {anl.id}
                        </Link>
                      </td>
                      <td style={{ color: 'var(--text-secondary)' }}>
                        {anl.created_at.replace('T', ' ').slice(0, 19)}
                      </td>
                      <td className="mono">{anl.records_processed}</td>
                      <td>
                        <span
                          style={{
                            fontWeight: 600,
                            color: anl.finding_count > 0 ? '#fca5a5' : '#34d399',
                          }}
                        >
                          {anl.finding_count}
                        </span>
                      </td>
                      <td>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                          <span style={scoreStyle}>{anl.quality_score}</span>
                          <GateBadge gate={anl.gate} />
                        </div>
                      </td>
                      <td className="mono" style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>
                        {anl.findings_digest ? `${anl.findings_digest.slice(0, 12)}...` : '—'}
                      </td>
                      <td>
                        <Link href={`/analyses/${anl.id}`} className="btn btn-secondary" style={{ padding: '0.3rem 0.75rem', fontSize: '0.75rem' }}>
                          View Results →
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
