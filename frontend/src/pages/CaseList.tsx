import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchJSON } from '../api/client'

interface Case {
  slug: string
  name: string
  description: string
  document_count: number
  created_at?: string
  updated_at?: string
  ingest_status?: 'running' | 'completed' | 'failed' | 'never_run'
}

function formatDate(dateStr?: string): string {
  if (!dateStr) return ''
  try {
    const d = new Date(dateStr)
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
  } catch {
    return ''
  }
}

function StatusBadge({ status }: { status?: string }) {
  let label: string
  let style: React.CSSProperties

  switch (status) {
    case 'completed':
      label = 'Completed'
      style = { background: '#dcfce7', color: 'var(--success)' }
      break
    case 'running':
      label = 'Running'
      style = { background: 'var(--accent-light)', color: 'var(--accent)' }
      break
    case 'failed':
      label = 'Failed'
      style = { background: '#fee2e2', color: 'var(--danger)' }
      break
    default:
      label = 'Not Started'
      style = { background: '#f3f4f6', color: 'var(--text-muted)' }
      break
  }

  return (
    <span
      style={{
        display: 'inline-block',
        padding: '3px 10px',
        fontSize: 11,
        fontWeight: 600,
        borderRadius: 'var(--radius-sm)',
        letterSpacing: '0.02em',
        ...style,
      }}
    >
      {label}
    </span>
  )
}

function EmptyState() {
  return (
    <div style={styles.emptyState}>
      <div style={styles.emptyIcon}>
        <svg
          width="80"
          height="80"
          viewBox="0 0 80 80"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          <rect x="10" y="18" width="60" height="48" rx="6" stroke="#d1d5db" strokeWidth="2" fill="#f9fafb" />
          <rect x="18" y="28" width="28" height="4" rx="2" fill="#d1d5db" />
          <rect x="18" y="36" width="44" height="3" rx="1.5" fill="#e5e7eb" />
          <rect x="18" y="43" width="36" height="3" rx="1.5" fill="#e5e7eb" />
          <rect x="18" y="50" width="40" height="3" rx="1.5" fill="#e5e7eb" />
          <circle cx="60" cy="58" r="14" fill="#2563eb" fillOpacity="0.1" stroke="#2563eb" strokeWidth="2" />
          <line x1="56" y1="58" x2="64" y2="58" stroke="#2563eb" strokeWidth="2" strokeLinecap="round" />
          <line x1="60" y1="54" x2="60" y2="62" stroke="#2563eb" strokeWidth="2" strokeLinecap="round" />
        </svg>
      </div>
      <h2 style={styles.emptyTitle}>No cases yet</h2>
      <p style={styles.emptyDescription}>
        Create your first case to start ingesting and analyzing documents.
      </p>
      <Link to="/new" style={styles.emptyButton}>
        Create Your First Case
      </Link>
    </div>
  )
}

export default function CaseList() {
  const [cases, setCases] = useState<Case[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchJSON<Case[]>('/cases')
      .then(setCases)
      .catch(() => setCases([]))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div style={styles.page}>
      {/* Header */}
      <header style={styles.header}>
        <div style={styles.headerInner}>
          <div>
            <h1 style={styles.logo}>CaseStack</h1>
            <p style={styles.tagline}>Document Intelligence Platform</p>
          </div>
          <Link to="/new" style={styles.newCaseButton}>
            <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
              <path d="M8 2a.75.75 0 01.75.75v4.5h4.5a.75.75 0 010 1.5h-4.5v4.5a.75.75 0 01-1.5 0v-4.5h-4.5a.75.75 0 010-1.5h4.5v-4.5A.75.75 0 018 2z" />
            </svg>
            New Case
          </Link>
        </div>
      </header>

      {/* Content */}
      <main style={styles.content}>
        {loading ? (
          <div style={styles.loadingState}>
            <div style={styles.spinner} />
            <span>Loading cases...</span>
          </div>
        ) : cases.length === 0 ? (
          <EmptyState />
        ) : (
          <>
            <div style={styles.sectionHeader}>
              <h2 style={styles.sectionTitle}>
                Your Cases
                <span style={styles.caseCount}>{cases.length}</span>
              </h2>
            </div>
            <div style={styles.caseGrid}>
              {cases.map(c => (
                <Link
                  key={c.slug}
                  to={`/case/${c.slug}`}
                  style={styles.caseCard}
                  className="case-card"
                >
                  <div style={styles.cardTop}>
                    <h3 style={styles.caseName}>{c.name}</h3>
                    <StatusBadge status={c.ingest_status} />
                  </div>
                  {c.description && (
                    <p style={styles.caseDescription}>{c.description}</p>
                  )}
                  <div style={styles.cardMeta}>
                    <span style={styles.metaItem}>
                      <svg width="14" height="14" viewBox="0 0 16 16" fill="var(--text-muted)" style={{ flexShrink: 0 }}>
                        <path d="M3.5 2A1.5 1.5 0 002 3.5v9A1.5 1.5 0 003.5 14h9a1.5 1.5 0 001.5-1.5v-7a.5.5 0 00-.146-.354l-4.5-4.5A.5.5 0 009 2H3.5zm5 .5L13 7h-3.5A1.5 1.5 0 018 5.5V2.5z" />
                      </svg>
                      {c.document_count} {c.document_count === 1 ? 'document' : 'documents'}
                    </span>
                    {c.updated_at && (
                      <span style={styles.metaItem}>
                        Last opened {formatDate(c.updated_at)}
                      </span>
                    )}
                  </div>
                </Link>
              ))}
            </div>
          </>
        )}
      </main>
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  page: {
    minHeight: '100vh',
    background: 'var(--bg)',
  },
  header: {
    background: 'var(--surface)',
    borderBottom: '1px solid var(--border)',
    padding: '0 32px',
  },
  headerInner: {
    maxWidth: 960,
    margin: '0 auto',
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '24px 0',
  },
  logo: {
    fontSize: 24,
    fontWeight: 700,
    color: 'var(--text)',
    margin: 0,
    letterSpacing: '-0.02em',
  },
  tagline: {
    fontSize: 13,
    color: 'var(--text-muted)',
    margin: '2px 0 0',
  },
  newCaseButton: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 8,
    padding: '10px 24px',
    background: 'var(--accent)',
    color: '#fff',
    borderRadius: 'var(--radius-md)',
    fontSize: 14,
    fontWeight: 600,
    textDecoration: 'none',
    transition: 'all 0.15s ease',
    boxShadow: '0 1px 3px rgba(37, 99, 235, 0.3)',
  },
  content: {
    maxWidth: 960,
    margin: '0 auto',
    padding: '32px 32px 64px',
  },
  sectionHeader: {
    marginBottom: 20,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: 600,
    color: 'var(--text)',
    display: 'flex',
    alignItems: 'center',
    gap: 10,
  },
  caseCount: {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    minWidth: 24,
    height: 24,
    padding: '0 8px',
    fontSize: 12,
    fontWeight: 600,
    borderRadius: 12,
    background: '#f3f4f6',
    color: 'var(--text-muted)',
  },
  caseGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
    gap: 16,
  },
  caseCard: {
    display: 'block',
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-lg)',
    padding: 24,
    textDecoration: 'none',
    color: 'inherit',
    transition: 'all 0.2s ease',
    cursor: 'pointer',
  },
  cardTop: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    gap: 12,
    marginBottom: 8,
  },
  caseName: {
    fontSize: 16,
    fontWeight: 600,
    color: 'var(--text)',
    margin: 0,
    lineHeight: 1.3,
  },
  caseDescription: {
    fontSize: 13,
    color: 'var(--text-muted)',
    lineHeight: 1.5,
    margin: '0 0 16px',
    display: '-webkit-box',
    WebkitLineClamp: 2,
    WebkitBoxOrient: 'vertical' as const,
    overflow: 'hidden',
  },
  cardMeta: {
    display: 'flex',
    alignItems: 'center',
    gap: 16,
    paddingTop: 16,
    borderTop: '1px solid var(--border)',
    fontSize: 12,
    color: 'var(--text-muted)',
  },
  metaItem: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 5,
  },
  // Empty state
  emptyState: {
    display: 'flex',
    flexDirection: 'column' as const,
    alignItems: 'center',
    justifyContent: 'center',
    padding: '80px 32px',
    textAlign: 'center' as const,
  },
  emptyIcon: {
    marginBottom: 24,
    opacity: 0.8,
  },
  emptyTitle: {
    fontSize: 22,
    fontWeight: 600,
    color: 'var(--text)',
    marginBottom: 8,
  },
  emptyDescription: {
    fontSize: 15,
    color: 'var(--text-muted)',
    maxWidth: 360,
    lineHeight: 1.6,
    marginBottom: 28,
  },
  emptyButton: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 8,
    padding: '12px 32px',
    background: 'var(--accent)',
    color: '#fff',
    borderRadius: 'var(--radius-md)',
    fontSize: 15,
    fontWeight: 600,
    textDecoration: 'none',
    transition: 'all 0.15s ease',
    boxShadow: '0 1px 3px rgba(37, 99, 235, 0.3)',
  },
  // Loading
  loadingState: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 12,
    padding: 64,
    color: 'var(--text-muted)',
    fontSize: 14,
  },
  spinner: {
    width: 20,
    height: 20,
    border: '2px solid var(--border)',
    borderTopColor: 'var(--accent)',
    borderRadius: '50%',
    animation: 'spin 0.6s linear infinite',
  },
}
