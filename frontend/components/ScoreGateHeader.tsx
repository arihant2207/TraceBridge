import React from 'react';

interface GateBadgeProps {
  gate: string;
}

export function GateBadge({ gate }: GateBadgeProps) {
  const isNotBlocked = gate === 'NOT_BLOCKED';
  const isCritical = gate.includes('CRITICAL');
  const isHigh = gate.includes('HIGH');

  let badgeClass = 'gate-badge gate-neutral';
  if (isCritical) {
    badgeClass = 'gate-badge gate-critical';
  } else if (isHigh) {
    badgeClass = 'gate-badge gate-high';
  } else if (isNotBlocked) {
    badgeClass = 'gate-badge gate-not-blocked';
  }

  return (
    <span className="gate-wrapper">
      <span className={badgeClass}>{gate}</span>
      {isNotBlocked && <span className="gate-note">Not an approval.</span>}
    </span>
  );
}

interface ScoreGateHeaderProps {
  score: string;
  gate: string;
}

export function ScoreGateHeader({ score, gate }: ScoreGateHeaderProps) {
  const isCritical = gate.includes('CRITICAL');
  const isHigh = gate.includes('HIGH');

  // Hard Rule: The score is NEVER green.
  let scoreClass = 'score-value score-neutral';
  if (isCritical) {
    scoreClass = 'score-value score-critical';
  } else if (isHigh) {
    scoreClass = 'score-value score-high';
  }

  return (
    <div className="score-gate-card">
      <div className="score-gate-metrics">
        <div className="score-block">
          <div className="metric-label">Quality Score</div>
          <div className="metric-value-row">
            <span className={scoreClass}>{score}</span>
            <span className="score-scale">/ 100.0</span>
          </div>
        </div>

        <div className="metric-divider" />

        <div className="gate-block">
          <div className="metric-label">Gate Status</div>
          <div style={{ marginTop: '0.2rem' }}>
            <GateBadge gate={gate} />
          </div>
        </div>
      </div>

      <div className="score-disclaimer">
        This score measures evidence quality only; it is not a safety or certification result.
      </div>
    </div>
  );
}
