'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { listAnalyses, AnalysisSummary, ApiError } from '../lib/api';
import { GateBadge } from '../components/ScoreGateHeader';

export default function AnalysesListPage() {
  const [analyses, setAnalyses] = useState<AnalysisSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<{ code: string; message: string; details: string[] } | null>(null);

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
          if (err instanceof ApiError) {
            setError({ code: err.code, message: err.message, details: err.details });
          } else {
            setError({ code: 'ERROR', message: (err as Error).message, details: [] });
          }
          setLoading(false);
        }
      });
    return () => {
      mounted = false;
    };
  }, []);

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1.25rem', flexWrap: 'wrap', gap: '0.75rem' }}>
        <div>
          <h1 style={{ fontSize: '1.5rem', fontWeight: 600, color: 'var(--text-primary)', margin: 0 }}>
            Validation Analyses
          </h1>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.8125rem', margin: '0.25rem 0 0 0' }}>
            Deterministic engineering evidence validation runs
          </p>
        </div>
        <Link href="/analyses/new" className="btn btn-primary">
          New analysis
        </Link>
      </div>

      {error && (
        <div className="alert alert-error">
          <div className="alert-title">[{error.code}] Failed to load analyses</div>
          <div>{error.message}</div>
          {error.details.length > 0 && (
            <ul className="alert-details-list">
              {error.details.map((d, i) => (
                <li key={i}>{d}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {loading ? (
        <div className="card" style={{ textAlign: 'center', padding: '2.5rem 1rem', color: 'var(--text-muted)' }}>
          Loading analyses...
        </div>
      ) : analyses.length === 0 ? (
        <div className="card" style={{ textAlign: 'center', padding: '3rem 1.5rem' }}>
          <h2 style={{ fontSize: '1.125rem', fontWeight: 600, color: 'var(--text-primary)', margin: '0 0 0.5rem 0' }}>
            No analyses found
          </h2>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.8125rem', maxWidth: '420px', margin: '0 auto 1.25rem auto' }}>
            Run an analysis using the preloaded clean or fault sample datasets, or upload your own engineering CSV files.
          </p>
          <Link href="/analyses/new" className="btn btn-primary">
            New analysis
          </Link>
        </div>
      ) : (
        <div className="table-container">
          <table className="data-table">
            <thead>
              <tr>
                <th>Analysis ID</th>
                <th>Created (UTC)</th>
                <th>Records</th>
                <th>Findings</th>
                <th>Score & Gate</th>
                <th>Findings Digest</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {analyses.map((anl) => {
                let scoreColor = 'var(--text-primary)';
                if (anl.gate.includes('CRITICAL')) {
                  scoreColor = 'var(--critical-text)';
                } else if (anl.gate.includes('HIGH')) {
                  scoreColor = 'var(--amber-text)';
                }

                return (
                  <tr key={anl.id}>
                    <td className="mono" style={{ fontWeight: 600 }}>
                      <Link href={`/analyses/${anl.id}`}>
                        {anl.id}
                      </Link>
                    </td>
                    <td style={{ color: 'var(--text-muted)' }}>
                      {anl.created_at.replace('T', ' ').slice(0, 19)}
                    </td>
                    <td className="mono">{anl.records_processed}</td>
                    <td className="mono" style={{ fontWeight: 500, color: anl.finding_count > 0 ? 'var(--text-primary)' : 'var(--text-muted)' }}>
                      {anl.finding_count}
                    </td>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
                        <span className="mono" style={{ fontWeight: 600, color: scoreColor }}>
                          {anl.quality_score}
                        </span>
                        <GateBadge gate={anl.gate} />
                      </div>
                    </td>
                    <td className="mono" style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>
                      {anl.findings_digest ? `${anl.findings_digest.slice(0, 12)}...` : '—'}
                    </td>
                    <td>
                      <Link href={`/analyses/${anl.id}`} className="btn btn-secondary" style={{ padding: '0.25rem 0.6rem', fontSize: '0.75rem' }}>
                        View results
                      </Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
