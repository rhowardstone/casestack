import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { fetchJSON } from '../api/client'
import ProgressBar from '../components/ProgressBar'

interface CaseData {
  slug: string
  name: string
  description: string
  document_count: number
  page_count: number
  image_count: number
  transcript_count: number
}

interface IngestStatus {
  status: 'running' | 'completed' | 'failed' | 'never_run'
  current_step?: string
  progress?: number
  steps_completed?: number
  steps_total?: number
  error?: string
}

export default function Dashboard() {
  const { slug } = useParams<{ slug: string }>()
  const [caseData, setCaseData] = useState<CaseData | null>(null)
  const [ingestStatus, setIngestStatus] = useState<IngestStatus | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!slug) return

    fetchJSON<CaseData>(`/cases/${slug}`)
      .then(setCaseData)
      .catch(err => setError(err.message))

    fetchJSON<IngestStatus>(`/cases/${slug}/ingest/status`)
      .then(setIngestStatus)
      .catch(() => setIngestStatus({ status: 'never_run' }))
  }, [slug])

  if (error) {
    return (
      <div style={styles.errorContainer}>
        <h2 style={styles.errorTitle}>Error loading case</h2>
        <p style={styles.errorMessage}>{error}</p>
      </div>
    )
  }

  if (!caseData) {
    return <div style={styles.loading}>Loading...</div>
  }

  const stats = [
    { label: 'Documents', value: caseData.document_count, color: 'var(--accent)' },
    { label: 'Pages', value: caseData.page_count, color: '#7c3aed' },
    { label: 'Images', value: caseData.image_count, color: '#0891b2' },
    { label: 'Transcripts', value: caseData.transcript_count, color: '#059669' },
  ]

  return (
    <div>
      <div style={styles.header}>
        <h1 style={styles.title}>{caseData.name}</h1>
        {caseData.description && (
          <p style={styles.description}>{caseData.description}</p>
        )}
      </div>

      {/* Stat cards */}
      <div style={styles.statsGrid}>
        {stats.map(stat => (
          <div key={stat.label} style={styles.statCard}>
            <div style={{ ...styles.statValue, color: stat.color }}>
              {stat.value.toLocaleString()}
            </div>
            <div style={styles.statLabel}>{stat.label}</div>
          </div>
        ))}
      </div>

      {/* Ingest status */}
      <div style={styles.ingestSection}>
        <h2 style={styles.sectionTitle}>Ingest Status</h2>
        {renderIngestStatus(ingestStatus)}
      </div>
    </div>
  )
}

function renderIngestStatus(status: IngestStatus | null) {
  if (!status) {
    return <div style={styles.statusCard}>Loading ingest status...</div>
  }

  switch (status.status) {
    case 'running':
      return (
        <div style={{ ...styles.statusCard, borderLeft: '4px solid var(--accent)' }}>
          <div style={styles.statusHeader}>
            <span style={styles.statusBadgeRunning}>In Progress</span>
            {status.current_step && (
              <span style={styles.currentStep}>{status.current_step}</span>
            )}
          </div>
          {status.progress != null && (
            <div style={{ marginTop: 16 }}>
              <ProgressBar
                label={
                  status.steps_completed != null && status.steps_total != null
                    ? `Step ${status.steps_completed} of ${status.steps_total}`
                    : 'Progress'
                }
                percent={status.progress}
              />
            </div>
          )}
        </div>
      )

    case 'completed':
      return (
        <div style={{ ...styles.statusCard, borderLeft: '4px solid var(--success)' }}>
          <div style={styles.statusHeader}>
            <span style={styles.statusBadgeCompleted}>Completed</span>
          </div>
          <p style={styles.statusMessage}>
            Ingest finished successfully. All documents have been processed.
          </p>
        </div>
      )

    case 'failed':
      return (
        <div style={{ ...styles.statusCard, borderLeft: '4px solid var(--danger)' }}>
          <div style={styles.statusHeader}>
            <span style={styles.statusBadgeFailed}>Failed</span>
          </div>
          {status.error && (
            <p style={styles.statusError}>{status.error}</p>
          )}
        </div>
      )

    case 'never_run':
    default:
      return (
        <div style={{ ...styles.statusCard, borderLeft: '4px solid var(--border)' }}>
          <div style={styles.statusHeader}>
            <span style={styles.statusBadgeNeverRun}>Not Started</span>
          </div>
          <p style={styles.statusMessage}>
            Run ingest to process your documents and extract content.
          </p>
          <p style={styles.statusHint}>
            Use <code style={styles.code}>casestack ingest --case your-case.yaml</code> to begin.
          </p>
        </div>
      )
  }
}

const styles: Record<string, React.CSSProperties> = {
  loading: {
    padding: 32,
    color: 'var(--text-muted)',
    fontSize: 14,
  },
  errorContainer: {
    padding: 32,
  },
  errorTitle: {
    fontSize: 20,
    fontWeight: 700,
    color: 'var(--danger)',
    marginBottom: 8,
  },
  errorMessage: {
    fontSize: 14,
    color: 'var(--text-muted)',
  },
  header: {
    marginBottom: 32,
  },
  title: {
    fontSize: 28,
    fontWeight: 700,
    color: 'var(--text)',
    marginBottom: 4,
  },
  description: {
    fontSize: 15,
    color: 'var(--text-muted)',
    marginTop: 4,
  },
  statsGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
    gap: 16,
    marginBottom: 40,
  },
  statCard: {
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-md)',
    padding: 24,
    textAlign: 'center' as const,
  },
  statValue: {
    fontSize: 36,
    fontWeight: 700,
    lineHeight: 1,
    marginBottom: 8,
  },
  statLabel: {
    fontSize: 13,
    fontWeight: 500,
    color: 'var(--text-muted)',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.05em',
  },
  ingestSection: {
    marginBottom: 32,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: 600,
    color: 'var(--text)',
    marginBottom: 16,
  },
  statusCard: {
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-md)',
    padding: 24,
  },
  statusHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    marginBottom: 8,
  },
  statusBadgeRunning: {
    display: 'inline-block',
    padding: '4px 10px',
    fontSize: 12,
    fontWeight: 600,
    borderRadius: 'var(--radius-sm)',
    background: 'var(--accent-light)',
    color: 'var(--accent)',
  },
  statusBadgeCompleted: {
    display: 'inline-block',
    padding: '4px 10px',
    fontSize: 12,
    fontWeight: 600,
    borderRadius: 'var(--radius-sm)',
    background: '#dcfce7',
    color: 'var(--success)',
  },
  statusBadgeFailed: {
    display: 'inline-block',
    padding: '4px 10px',
    fontSize: 12,
    fontWeight: 600,
    borderRadius: 'var(--radius-sm)',
    background: '#fee2e2',
    color: 'var(--danger)',
  },
  statusBadgeNeverRun: {
    display: 'inline-block',
    padding: '4px 10px',
    fontSize: 12,
    fontWeight: 600,
    borderRadius: 'var(--radius-sm)',
    background: '#f3f4f6',
    color: 'var(--text-muted)',
  },
  currentStep: {
    fontSize: 14,
    color: 'var(--text)',
    fontWeight: 500,
  },
  statusMessage: {
    fontSize: 14,
    color: 'var(--text-muted)',
    lineHeight: 1.5,
  },
  statusError: {
    fontSize: 14,
    color: 'var(--danger)',
    lineHeight: 1.5,
  },
  statusHint: {
    fontSize: 13,
    color: 'var(--text-muted)',
    marginTop: 8,
  },
  code: {
    background: '#f3f4f6',
    padding: '2px 6px',
    borderRadius: 4,
    fontSize: 12,
    fontFamily: 'monospace',
  },
}
