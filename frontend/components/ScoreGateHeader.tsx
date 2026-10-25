import React from 'react';

interface GateBadgeProps {
  gate: string;
}

export function GateBadge({ gate }: GateBadgeProps) {
  const normalized = (gate || '').toLowerCase();
  let className = 'gate-badge';

  if (normalized.includes('critical')) {
    className += ' gate-blocked_critical';
  } else if (normalized.includes('high')) {
    className += ' gate-blocked_high';
  } else if (normalized.includes('not_blocked')) {
    className += ' gate-not_blocked';
  } else {
    className += ' gate-blocked_high';
  }

  return (
    <span className={className}>
      <span style={{ fontSize: '0.65rem' }}>●</span> {gate}
    </span>
  );
}

interface ScoreGateHeaderProps {
  score: string;
  gate: string;
}

export function ScoreGateHeader({ score, gate }: ScoreGateHeaderProps) {
  const isNotBlocked = gate === 'NOT_BLOCKED';

  // Hard Rule: The score is NEVER styled green unless the gate is NOT_BLOCKED
  let scoreClass = 'score-value';
  if (isNotBlocked) {
    scoreClass += ' score-clean';
  } else if (gate.includes('CRITICAL')) {
    scoreClass += ' score-blocked';
  } else if (gate.includes('HIGH')) {
    scoreClass += ' score-warning';
  } else {
    scoreClass += ' score-neutral';
  }

  return (
    <div className="score-gate-container">
      <div className="score-box">
        <span className="score-label">Quality Score</span>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '0.4rem' }}>
          <span className={scoreClass}>{score}</span>
          <span style={{ color: 'var(--text-muted)', fontSize: '1rem', fontFamily: 'var(--font-mono)' }}>
            / 100.0
          </span>
        </div>
      </div>

      <div style={{ height: '40px', width: '1px', backgroundColor: 'var(--border-subtle)' }} />

      <div className="score-box">
        <span className="score-label">Gate Status</span>
        <div style={{ marginTop: '0.25rem' }}>
          <GateBadge gate={gate} />
        </div>
      </div>

      <div style={{ flex: 1 }} />

      <div className="score-disclaimer">
        This score measures evidence quality only; it is not a safety or certification result.
      </div>
    </div>
  );
}
