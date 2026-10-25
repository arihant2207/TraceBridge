import type { Metadata } from 'next';
import Link from 'next/link';
import './globals.css';

export const metadata: Metadata = {
  title: 'TraceBridge | Evidence Validation Engine',
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
              <Link href="/" className="brand-title">TraceBridge</Link>
              <span className="brand-subtitle">Deterministic Evidence Validation</span>
            </div>
            <nav className="nav-links">
              <Link href="/" className="nav-link">
                Dashboard
              </Link>
            </nav>
          </header>
          <main>{children}</main>
        </div>
      </body>
    </html>
  );
}
