import { useEffect, useState, useRef, useCallback } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { fetchJSON } from '../api/client'

interface CaseData {
  slug: string
  name: string
  description: string
  document_count: number
  page_count: number
  image_count: number
  transcript_count: number
}

interface Conversation {
  id: string
  title: string | null
  updated_at: string
}

interface StepInfo {
  id: string
  label: string
  status: 'running' | 'completed' | 'skipped'
  startedAt: number
  completedAt?: number
  current?: number
  total?: number
}

interface IngestStatus {
  status: 'running' | 'completed' | 'failed' | 'never_run'
  error_message?: string
  current_step?: string
  error?: string
  steps?: StepInfo[]
  globalStartedAt?: number
  globalCompletedAt?: number
  lastProgressAt?: number
}

interface CaseStats {
  date_min: string | null
  date_max: string | null
  docs_by_year: { year: string; count: number }[]
  top_entities: { name: string; type: string; count: number }[]
}

// Pipeline step labels from manifest
const STEP_LABELS: Record<string, string> = {}

function formatElapsed(ms: number): string {
  const totalSec = Math.floor(ms / 1000)
  const h = Math.floor(totalSec / 3600)
  const min = Math.floor((totalSec % 3600) / 60)
  const sec = totalSec % 60
  if (h > 0) return `${h}h ${min.toString().padStart(2, '0')}m`
  if (min > 0) return `${min}m ${sec.toString().padStart(2, '0')}s`
  return `${sec}s`
}

function stepLabel(id: string): string {
  if (STEP_LABELS[id]) return STEP_LABELS[id]
  return id.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

function formatDateRange(min: string | null, max: string | null): string {
  if (!min && !max) return ''
  const fmt = (d: string) => {
    const [y, m] = d.split('-')
    const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    return `${months[parseInt(m) - 1]} ${y}`
  }
  if (min && max) return `${fmt(min)} – ${fmt(max)}`
  if (min) return `From ${fmt(min)}`
  return `Until ${fmt(max!)}`
}

const ENTITY_TYPE_COLORS: Record<string, string> = {
  PERSON: '#3b82f6',
  ORG: '#22c55e',
  GPE: '#ef4444',
}

function TimelineChart({ data }: { data: { year: string; count: number }[] }) {
  if (!data.length) return null
  const maxCount = Math.max(...data.map(d => d.count))
  const chartHeight = 110
  const barGap = 5
  const barWidth = 22
  const totalWidth = (barWidth + barGap) * data.length - barGap

  // Use sqrt scale so small bars are visible but large bars still dominate
  const scale = (count: number) => Math.max(4, Math.round(Math.sqrt(count / maxCount) * chartHeight))

  return (
    <div style={{ overflowX: 'auto' }}>
      <svg width={totalWidth} height={chartHeight + 28} style={{ display: 'block' }}>
        {data.map((d, i) => {
          const barH = scale(d.count)
          const x = i * (barWidth + barGap)
          const y = chartHeight - barH
          const isPeak = d.count === maxCount
          return (
            <g key={d.year}>
              <rect
                x={x}
                y={y}
                width={barWidth}
                height={barH}
                rx={2}
                fill="var(--accent)"
                opacity={isPeak ? 1 : 0.65}
              />
              {/* Count label on bars with enough height */}
              {barH >= 18 && (
                <text
                  x={x + barWidth / 2}
                  y={y + 12}
                  textAnchor="middle"
                  fontSize={9}
                  fill="#fff"
                  fontFamily="inherit"
                  fontWeight={600}
                >
                  {d.count}
                </text>
              )}
              {/* Count label above short bars */}
              {barH < 18 && d.count > 1 && (
                <text
                  x={x + barWidth / 2}
                  y={y - 3}
                  textAnchor="middle"
                  fontSize={8}
                  fill="var(--accent)"
                  fontFamily="inherit"
                >
                  {d.count}
                </text>
              )}
              <text
                x={x + barWidth / 2}
                y={chartHeight + 18}
                textAnchor="middle"
                fontSize={9}
                fill="var(--text-muted)"
                fontFamily="inherit"
              >
                {d.year}
              </text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}

const ENTITY_ROW_STYLE = `
  .dash-entity-row:hover { background: var(--surface-hover, var(--border)) !important; }
`

export default function Dashboard() {
  const { slug } = useParams<{ slug: string }>()
  const navigate = useNavigate()
  const [caseData, setCaseData] = useState<CaseData | null>(null)
  const [caseStats, setCaseStats] = useState<CaseStats | null>(null)
  const [ingestStatus, setIngestStatus] = useState<IngestStatus | null>(null)
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [error, setError] = useState('')
  const [showProcessing, setShowProcessing] = useState(false)
  const [, setTick] = useState(0)
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const wsRef = useRef<WebSocket | null>(null)

  const startTicking = useCallback(() => {
    if (tickRef.current) return
    tickRef.current = setInterval(() => setTick(t => t + 1), 1000)
  }, [])

  const stopTicking = useCallback(() => {
    if (tickRef.current) {
      clearInterval(tickRef.current)
      tickRef.current = null
    }
  }, [])

  useEffect(() => () => { stopTicking(); wsRef.current?.close() }, [stopTicking])

  useEffect(() => {
    if (!slug) return

    // Load pipeline manifest for step labels
    fetchJSON<{ id: string; label: string }[]>('/pipeline/manifest')
      .then(m => { for (const s of m) STEP_LABELS[s.id] = s.label })
      .catch(() => {})

    fetchJSON<CaseData>(`/cases/${slug}`)
      .then(setCaseData)
      .catch(err => setError(err.message))

    fetchJSON<CaseStats>(`/cases/${slug}/stats`)
      .then(setCaseStats)
      .catch(() => {})

    fetchJSON<Conversation[]>(`/cases/${slug}/conversations`)
      .then(setConversations)
      .catch(() => {})

    fetchJSON<IngestStatus>(`/cases/${slug}/ingest/status`)
      .then(s => {
        if (s.status === 'running' && !s.globalStartedAt) {
          s = { ...s, globalStartedAt: Date.now() }
        }
        setIngestStatus(s)
        if (s.status === 'running') {
          setShowProcessing(true)
          startTicking()
          connectWs(slug)
        }
      })
      .catch(() => setIngestStatus({ status: 'never_run' }))

    function connectWs(caseSlug: string) {
      if (wsRef.current) { wsRef.current.close(); wsRef.current = null }
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const ws = new WebSocket(`${proto}//${window.location.host}/ws/cases/${caseSlug}/ingest`)
      wsRef.current = ws

      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data)
          setIngestStatus(prev => {
            const steps = prev?.steps || []
            const now = Date.now()
            switch (msg.type) {
              case 'step_start': {
                startTicking()
                const globalStart = prev?.globalStartedAt || now
                const updatedSteps = steps.map(s =>
                  s.status === 'running' ? { ...s, status: 'completed' as const, completedAt: now } : s
                )
                updatedSteps.push({ id: msg.step_id, label: stepLabel(msg.step_id), status: 'running', startedAt: now, total: msg.total > 0 ? msg.total : undefined })
                return { ...prev!, status: 'running', current_step: msg.step_id, steps: updatedSteps, globalStartedAt: globalStart, lastProgressAt: now }
              }
              case 'step_progress':
                return {
                  ...prev!,
                  lastProgressAt: now,
                  steps: steps.map(s =>
                    s.id === msg.step_id ? { ...s, current: msg.current, total: msg.total } : s
                  ),
                }
              case 'step_complete': {
                const updatedSteps = steps.map(s =>
                  s.id === msg.step_id ? { ...s, status: 'completed' as const, completedAt: now } : s
                )
                return { ...prev!, steps: updatedSteps }
              }
              case 'log':
                return prev
              case 'complete': {
                stopTicking()
                fetchJSON<CaseData>(`/cases/${caseSlug}`).then(setCaseData).catch(() => {})
                fetchJSON<CaseStats>(`/cases/${caseSlug}/stats`).then(setCaseStats).catch(() => {})
                const finalSteps = steps.map(s =>
                  s.status === 'running' ? { ...s, status: 'completed' as const, completedAt: now } : s
                )
                return { ...prev!, status: 'completed', current_step: undefined, steps: finalSteps, globalCompletedAt: now }
              }
              case 'error':
                stopTicking()
                return { ...prev!, status: 'failed', error: msg.message }
              default:
                return prev
            }
          })
        } catch {}
      }

      ws.onclose = () => {
        wsRef.current = null
        setTimeout(() => {
          fetchJSON<IngestStatus>(`/cases/${caseSlug}/ingest/status`)
            .then(s => {
              if (s.status === 'running') {
                setIngestStatus(prev => ({ ...prev!, status: 'running' }))
                startTicking()
                connectWs(caseSlug)
              } else if (s.status === 'completed' || s.status === 'failed') {
                stopTicking()
                setIngestStatus(prev => ({
                  ...prev!,
                  status: s.status as 'completed' | 'failed',
                  error: s.status === 'failed' ? (prev?.error || 'Ingest failed') : undefined,
                  globalCompletedAt: prev?.globalCompletedAt || Date.now(),
                }))
                if (s.status === 'completed') {
                  fetchJSON<CaseData>(`/cases/${caseSlug}`).then(setCaseData).catch(() => {})
                }
              }
            })
            .catch(() => {})
        }, 2000)
      }
    }
  }, [slug, startTicking, stopTicking])

  // Detect stuck ingest — poll every 30s if running
  useEffect(() => {
    if (!slug || ingestStatus?.status !== 'running') return
    const poll = setInterval(() => {
      fetchJSON<{ status: string; error_message?: string }>(`/cases/${slug}/ingest/status`)
        .then(s => {
          if (s.status === 'completed') {
            stopTicking()
            fetchJSON<CaseData>(`/cases/${slug}`).then(setCaseData).catch(() => {})
            setIngestStatus(prev => ({
              ...prev!,
              status: 'completed',
              globalCompletedAt: Date.now(),
              steps: prev?.steps?.map(st => st.status === 'running' ? { ...st, status: 'completed' as const, completedAt: Date.now() } : st),
            }))
          } else if (s.status === 'failed') {
            stopTicking()
            setIngestStatus(prev => ({
              ...prev!,
              status: 'failed',
              error: s.error_message || 'Ingest process stopped unexpectedly',
            }))
          }
        })
        .catch(() => {})
    }, 15000)
    return () => clearInterval(poll)
  }, [slug, ingestStatus?.status, stopTicking])

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

  const dateRange = caseStats ? formatDateRange(caseStats.date_min, caseStats.date_max) : null
  const isRunning = ingestStatus?.status === 'running'

  return (
    <div>
      <style>{ENTITY_ROW_STYLE}</style>
      {/* Header */}
      <div style={styles.header}>
        <h1 style={styles.title}>{caseData.name}</h1>
        {caseData.description && (
          <p style={styles.description}>{caseData.description}</p>
        )}
        {dateRange && (
          <div style={styles.dateRange}>{dateRange}</div>
        )}
      </div>

      {/* Stats row */}
      <div style={styles.statsGrid}>
        {[
          { label: 'Documents', value: caseData.document_count, color: 'var(--accent)' },
          { label: 'Pages', value: caseData.page_count, color: '#7c3aed' },
          { label: 'Images', value: caseData.image_count, color: '#0891b2' },
          { label: 'Transcripts', value: caseData.transcript_count, color: '#059669' },
        ].map(stat => (
          <div key={stat.label} style={styles.statCard}>
            <div style={{ ...styles.statValue, color: stat.color }}>
              {stat.value.toLocaleString()}
            </div>
            <div style={styles.statLabel}>{stat.label}</div>
          </div>
        ))}
      </div>

      {/* Timeline + Top Entities */}
      {caseStats && (caseStats.docs_by_year.length > 0 || caseStats.top_entities.length > 0) && (
        <div style={styles.insightRow}>
          {/* Timeline chart */}
          {caseStats.docs_by_year.length > 0 && (
            <div style={styles.insightCard}>
              <div style={styles.insightHeader}>
                <span style={styles.insightTitle}>Documents by Year</span>
                {dateRange && <span style={styles.insightSub}>{dateRange}</span>}
              </div>
              <TimelineChart data={caseStats.docs_by_year} />
            </div>
          )}

          {/* Top entities */}
          {caseStats.top_entities.length > 0 && (
            <div style={{ ...styles.insightCard, flex: '0 0 260px' }}>
              <div style={styles.insightHeader}>
                <span style={styles.insightTitle}>Key Entities</span>
                <Link
                  to={`/case/${slug}/entities`}
                  style={{ fontSize: 12, color: 'var(--accent)', textDecoration: 'none' }}
                >
                  View all →
                </Link>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {caseStats.top_entities.slice(0, 8).map((ent, i) => {
                  const color = ENTITY_TYPE_COLORS[ent.type] || '#94a3b8'
                  return (
                    <div
                      key={i}
                      className="dash-entity-row"
                      style={styles.entityRow}
                      onClick={() => navigate(`/case/${slug}/search?q=${encodeURIComponent(ent.name)}`)}
                      title={`Search for "${ent.name}"`}
                    >
                      <span
                        style={{
                          display: 'inline-block',
                          width: 6,
                          height: 6,
                          borderRadius: '50%',
                          background: color,
                          flexShrink: 0,
                          marginTop: 2,
                        }}
                      />
                      <span style={styles.entityName}>{ent.name}</span>
                      <span style={styles.entityCount}>{ent.count}</span>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Recent Conversations */}
      {conversations.length > 0 && (
        <div style={styles.section}>
          <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 16 }}>
            <h2 style={styles.sectionTitle}>Recent Conversations</h2>
            <Link to={`/case/${slug}/ask`} style={{ fontSize: 13, color: 'var(--accent)', textDecoration: 'none' }}>
              New conversation →
            </Link>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {conversations.slice(0, 8).map(conv => (
              <Link
                key={conv.id}
                to={`/case/${slug}/ask?conv=${conv.id}`}
                style={styles.convRow}
                onMouseEnter={e => (e.currentTarget.style.background = 'var(--surface-hover, var(--border))')}
                onMouseLeave={e => (e.currentTarget.style.background = 'var(--surface)')}
              >
                <span style={styles.convTitle}>{conv.title || 'Untitled conversation'}</span>
                <span style={styles.convDate}>{new Date(conv.updated_at).toLocaleDateString()}</span>
              </Link>
            ))}
          </div>
        </div>
      )}

      {/* Processing — collapsed by default when completed */}
      <div style={styles.section}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: showProcessing ? 16 : 0 }}>
          <h2 style={styles.sectionTitle}>
            Processing
            {ingestStatus && !isRunning && (
              <span style={{
                marginLeft: 10,
                fontSize: 12,
                fontWeight: 500,
                color: ingestStatus.status === 'completed' ? 'var(--success)' : ingestStatus.status === 'failed' ? 'var(--danger)' : 'var(--text-muted)',
              }}>
                {ingestStatus.status === 'completed' ? '✓ Completed' : ingestStatus.status === 'failed' ? '✗ Failed' : 'Not started'}
              </span>
            )}
          </h2>
          {!isRunning && (
            <button
              onClick={() => setShowProcessing(p => !p)}
              style={styles.toggleBtn}
            >
              {showProcessing ? 'Hide' : 'Show details'}
            </button>
          )}
        </div>
        {(showProcessing || isRunning) && (
          <IngestCard status={ingestStatus} />
        )}
      </div>
    </div>
  )
}

function IngestCard({ status }: { status: IngestStatus | null }) {
  if (!status) return <div style={styles.statusCard}>Loading...</div>

  const now = Date.now()

  switch (status.status) {
    case 'running': {
      const globalElapsed = status.globalStartedAt ? now - status.globalStartedAt : 0
      const steps = status.steps || []
      const currentStep = steps.find(s => s.status === 'running')
      const completedCount = steps.filter(s => s.status === 'completed').length
      const idleMs = status.lastProgressAt ? now - status.lastProgressAt : 0

      return (
        <div style={{ ...styles.statusCard, borderLeft: '4px solid var(--accent)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={styles.statusBadgeRunning}>Processing</span>
              {currentStep && (
                <span style={{ fontSize: 14, fontWeight: 500, color: 'var(--text)' }}>
                  {currentStep.label}
                </span>
              )}
            </div>
            <span style={{ fontFamily: 'monospace', fontSize: 14, fontWeight: 600, color: 'var(--accent)' }}>
              {formatElapsed(globalElapsed)}
            </span>
          </div>

          {currentStep && currentStep.total && (
            <div style={{ marginBottom: 16 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 4 }}>
                <span style={{ color: 'var(--text-muted)' }}>
                  {currentStep.current != null
                    ? `${currentStep.current} of ${currentStep.total} items`
                    : `Starting... 0 of ${currentStep.total} items`}
                </span>
                <span style={{ color: 'var(--text-muted)' }}>
                  {currentStep.current != null
                    ? `${Math.round((currentStep.current / currentStep.total) * 100)}%`
                    : '0%'}
                </span>
              </div>
              <div style={{ width: '100%', height: 6, background: 'var(--border)', borderRadius: 3, overflow: 'hidden' }}>
                <div style={{
                  height: '100%',
                  width: currentStep.current != null
                    ? `${(currentStep.current / currentStep.total) * 100}%`
                    : '20%',
                  background: 'var(--accent)',
                  borderRadius: 3,
                  transition: currentStep.current != null ? 'width 0.3s ease' : 'opacity 1s ease-in-out',
                  animation: currentStep.current == null ? 'pulse 1.2s ease-in-out infinite' : 'none',
                }} />
              </div>
            </div>
          )}

          {steps.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
              <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>
                {completedCount} step{completedCount !== 1 ? 's' : ''} completed
              </div>
              {idleMs > 90000 && (
                <div style={{ fontSize: 12, color: '#b45309', marginBottom: 6 }}>
                  No new item progress for {Math.floor(idleMs / 1000)}s. Still running, but may be slow or stalled.
                </div>
              )}
              {steps.map(step => (
                <StepRow key={step.id} step={step} now={now} />
              ))}
            </div>
          )}
        </div>
      )
    }

    case 'completed': {
      const steps = status.steps || []
      const totalTime = status.globalStartedAt && status.globalCompletedAt
        ? status.globalCompletedAt - status.globalStartedAt
        : null

      return (
        <div style={{ ...styles.statusCard, borderLeft: '4px solid var(--success)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: steps.length ? 12 : 0 }}>
            <span style={styles.statusBadgeCompleted}>Completed</span>
            {totalTime && (
              <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>
                Finished in {formatElapsed(totalTime)}
              </span>
            )}
          </div>
          {steps.length > 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
              {steps.map(step => (
                <StepRow key={step.id} step={step} now={Date.now()} />
              ))}
            </div>
          ) : (
            <p style={styles.statusMessage}>All documents have been processed.</p>
          )}
        </div>
      )
    }

    case 'failed':
      return (
        <div style={{ ...styles.statusCard, borderLeft: '4px solid var(--danger)' }}>
          <span style={styles.statusBadgeFailed}>Failed</span>
          {status.error && (
            <p style={{ ...styles.statusError, marginTop: 8 }}>{status.error}</p>
          )}
          {status.steps && status.steps.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 1, marginTop: 12 }}>
              {status.steps.map(step => (
                <StepRow key={step.id} step={step} now={Date.now()} />
              ))}
            </div>
          )}
        </div>
      )

    default:
      return (
        <div style={{ ...styles.statusCard, borderLeft: '4px solid var(--border)' }}>
          <span style={styles.statusBadgeNeverRun}>Not Started</span>
          <p style={{ ...styles.statusMessage, marginTop: 8 }}>
            No documents have been processed yet. Start ingestion to extract and index your documents.
          </p>
        </div>
      )
  }
}

function StepRow({ step, now }: { step: StepInfo; now: number }) {
  const isRunning = step.status === 'running'
  const elapsed = step.completedAt
    ? step.completedAt - step.startedAt
    : now - step.startedAt

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 10, padding: '5px 0',
      opacity: isRunning ? 1 : 0.65,
    }}>
      <span style={{
        width: 8, height: 8, borderRadius: '50%', flexShrink: 0,
        background: isRunning ? 'var(--accent)' : 'var(--success)',
        animation: isRunning ? 'pulse 1.5s infinite' : 'none',
      }} />
      <span style={{ flex: 1, fontSize: 13, fontWeight: isRunning ? 600 : 400, color: 'var(--text)' }}>
        {step.label}
      </span>
      <span style={{
        fontSize: 12, fontFamily: 'monospace', minWidth: 44, textAlign: 'right',
        color: isRunning ? 'var(--accent)' : 'var(--text-muted)',
        fontWeight: isRunning ? 600 : 400,
      }}>
        {formatElapsed(elapsed)}
      </span>
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  loading: { padding: 32, color: 'var(--text-muted)', fontSize: 14 },
  errorContainer: { padding: 32 },
  errorTitle: { fontSize: 20, fontWeight: 700, color: 'var(--danger)', marginBottom: 8 },
  errorMessage: { fontSize: 14, color: 'var(--text-muted)' },
  header: { marginBottom: 24 },
  title: { fontSize: 28, fontWeight: 700, color: 'var(--text)', marginBottom: 4 },
  description: { fontSize: 15, color: 'var(--text-muted)', marginTop: 4, marginBottom: 6 },
  dateRange: { fontSize: 13, color: 'var(--text-muted)', fontWeight: 500, marginTop: 2 },
  statsGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 12, marginBottom: 24 },
  statCard: { background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)', padding: '20px 24px', textAlign: 'center' as const },
  statValue: { fontSize: 32, fontWeight: 700, lineHeight: 1, marginBottom: 6 },
  statLabel: { fontSize: 12, fontWeight: 500, color: 'var(--text-muted)', textTransform: 'uppercase' as const, letterSpacing: '0.05em' },
  insightRow: { display: 'flex', gap: 16, marginBottom: 24, flexWrap: 'wrap' as const },
  insightCard: { flex: 1, minWidth: 280, background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)', padding: '20px 24px' },
  insightHeader: { display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 14, gap: 8 },
  insightTitle: { fontSize: 14, fontWeight: 600, color: 'var(--text)', textTransform: 'uppercase' as const, letterSpacing: '0.04em' },
  insightSub: { fontSize: 12, color: 'var(--text-muted)' },
  entityRow: {
    display: 'flex', alignItems: 'flex-start', gap: 8, cursor: 'pointer',
    padding: '4px 6px', borderRadius: 'var(--radius-sm)', margin: '0 -6px',
    transition: 'background 0.1s',
  },
  entityName: { flex: 1, fontSize: 13, color: 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const },
  entityCount: { fontSize: 12, color: 'var(--text-muted)', flexShrink: 0, fontVariantNumeric: 'tabular-nums' },
  section: { marginBottom: 28 },
  sectionTitle: { fontSize: 16, fontWeight: 600, color: 'var(--text)', margin: 0 },
  toggleBtn: {
    padding: '4px 12px', fontSize: 12, fontWeight: 500, fontFamily: 'inherit',
    border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
    background: 'var(--surface)', color: 'var(--text-muted)', cursor: 'pointer',
  },
  statusCard: { background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)', padding: 24 },
  statusBadgeRunning: { display: 'inline-block', padding: '4px 10px', fontSize: 12, fontWeight: 600, borderRadius: 'var(--radius-sm)', background: 'var(--accent-light)', color: 'var(--accent)' },
  statusBadgeCompleted: { display: 'inline-block', padding: '4px 10px', fontSize: 12, fontWeight: 600, borderRadius: 'var(--radius-sm)', background: '#dcfce7', color: 'var(--success)' },
  statusBadgeFailed: { display: 'inline-block', padding: '4px 10px', fontSize: 12, fontWeight: 600, borderRadius: 'var(--radius-sm)', background: '#fee2e2', color: 'var(--danger)' },
  statusBadgeNeverRun: { display: 'inline-block', padding: '4px 10px', fontSize: 12, fontWeight: 600, borderRadius: 'var(--radius-sm)', background: '#f3f4f6', color: 'var(--text-muted)' },
  statusMessage: { fontSize: 14, color: 'var(--text-muted)', lineHeight: 1.5 },
  statusError: { fontSize: 14, color: 'var(--danger)', lineHeight: 1.5 },
  convRow: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 14px', borderRadius: 'var(--radius-sm)', background: 'var(--surface)', border: '1px solid var(--border)', textDecoration: 'none', transition: 'background 0.1s' },
  convTitle: { fontSize: 14, color: 'var(--text)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const },
  convDate: { fontSize: 12, color: 'var(--text-muted)', flexShrink: 0, marginLeft: 12 },
}
