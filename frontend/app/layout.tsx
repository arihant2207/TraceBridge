import type { Metadata } from 'next';
import Link from 'next/link';
import './globals.css';

export const metadata: Metadata = {
  title: 'TraceBridge | Deterministic Evidence Validation Engine',
  description: 'Deterministic engineering-evidence validation engine for safety and requirements compliance.',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <div className="app-container">
          <header className="app-header">
            <div className="brand">
              <span className="brand-badge">TB</span>
              <div>
                <Link href="/" className="brand-title">TraceBridge</Link>
                <div className="brand-subtitle">Deterministic Engineering-Evidence Validation Engine</div>
              </div>
            </div>
            <nav className="nav-links">
              <Link href="/" className="btn btn-secondary">
                Dashboard
              </Link>
              <Link href="/analyses/new" className="btn btn-primary">
                + New Analysis
              </Link>
            </nav>
          </header>
          <main>{children}</main>
        </div>
      </body>
    </html>
  );
}
