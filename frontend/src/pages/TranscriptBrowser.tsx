import { useState, useEffect, useMemo, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { fetchJSON } from '../api/client'
import MediaPlayer from '../components/MediaPlayer'

interface Transcript {
  document_id: string
  source_path: string | null
  text: string
  language: string
  duration_seconds: number
}

function formatDuration(seconds: number): string {
  if (!seconds || seconds <= 0) return '--'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  if (h > 0) return `${h}h ${m}m ${s}s`
  if (m > 0) return `${m}m ${s}s`
  return `${s}s`
}

function getMediaFormat(sourcePath: string | null): string {
  if (!sourcePath) return 'Unknown'
  const ext = sourcePath.split('.').pop()?.toLowerCase()
  if (!ext) return 'Unknown'
  const formats: Record<string, string> = {
    mp4: 'MP4 Video',
    webm: 'WebM Video',
    mov: 'MOV Video',
    avi: 'AVI Video',
    mkv: 'MKV Video',
    mp3: 'MP3 Audio',
    wav: 'WAV Audio',
    ogg: 'OGG Audio',
    flac: 'FLAC Audio',
    aac: 'AAC Audio',
    m4a: 'M4A Audio',
    wma: 'WMA Audio',
  }
  return formats[ext] || ext.toUpperCase()
}

function getFileName(sourcePath: string | null): string {
  if (!sourcePath) return 'Unknown file'
  const parts = sourcePath.replace(/\\/g, '/').split('/')
  return parts[parts.length - 1] || 'Unknown file'
}

function highlightText(text: string, terms: string[]): string {
  if (!terms.length) return escapeHtml(text)
  const escaped = terms
    .filter(Boolean)
    .map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  if (!escaped.length) return escapeHtml(text)
  const pattern = new RegExp(`(${escaped.join('|')})`, 'gi')
  // Escape HTML first, then apply highlights
  const safe = escapeHtml(text)
  return safe.replace(pattern, '<mark>$1</mark>')
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

export default function TranscriptBrowser() {
  const { slug = '' } = useParams<{ slug: string }>()
  const [transcripts, setTranscripts] = useState<Transcript[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')

  useEffect(() => {
    if (!slug) return
    setLoading(true)
    fetchJSON<Transcript[]>(`/cases/${slug}/transcripts`)
      .then((data) => {
        setTranscripts(data)
      })
      .catch((err) => setError(err.message || 'Failed to load transcripts'))
      .finally(() => setLoading(false))
  }, [slug])

  const selected = useMemo(
    () => transcripts.find((t) => t.document_id === selectedId) ?? null,
    [transcripts, selectedId],
  )

  const searchTerms = useMemo(
    () =>
      searchQuery
        .trim()
        .split(/\s+/)
        .filter((t) => t.length > 1),
    [searchQuery],
  )

  // Filter transcripts in list view by search query matching document_id or text
  const filteredTranscripts = useMemo(() => {
    if (!searchQuery.trim()) return transcripts
    const lower = searchQuery.toLowerCase()
    return transcripts.filter(
      (t) =>
        t.document_id.toLowerCase().includes(lower) ||
        t.text.toLowerCase().includes(lower) ||
        (t.source_path && t.source_path.toLowerCase().includes(lower)),
    )
  }, [transcripts, searchQuery])

  const matchCount = useMemo(() => {
    if (!selected || !searchQuery.trim()) return 0
    const lower = searchQuery.toLowerCase()
    const text = selected.text.toLowerCase()
    let count = 0
    let pos = 0
    while ((pos = text.indexOf(lower, pos)) !== -1) {
      count++
      pos += lower.length
    }
    return count
  }, [selected, searchQuery])

  const handleBack = useCallback(() => {
    setSelectedId(null)
    setSearchQuery('')
  }, [])

  if (error) {
    return (
      <div style={styles.errorContainer}>
        <h2 style={styles.errorTitle}>Error loading transcripts</h2>
        <p style={styles.errorMessage}>{error}</p>
      </div>
    )
  }

  if (loading) {
    return <div style={styles.loading}>Loading transcripts...</div>
  }

  // -- Detail view --
  if (selected) {
    return (
      <div style={styles.page}>
        <button onClick={handleBack} style={styles.backButton}>
          &larr; Back to all transcripts
        </button>

        <div style={styles.detailHeader}>
          <h1 style={styles.detailTitle}>{getFileName(selected.source_path)}</h1>
          <div style={styles.detailMeta}>
            <span style={styles.metaBadge}>{getMediaFormat(selected.source_path)}</span>
            <span style={styles.metaBadge}>{formatDuration(selected.duration_seconds)}</span>
            <span style={styles.metaBadge}>{selected.language.toUpperCase()}</span>
            <span style={styles.metaId}>{selected.document_id}</span>
          </div>
        </div>

        {/* Media player */}
        <div style={styles.playerSection}>
          <MediaPlayer
            slug={slug}
            documentId={selected.document_id}
            sourcePath={selected.source_path ?? undefined}
          />
        </div>

        {/* Search within transcript */}
        <div style={styles.searchSection}>
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search within transcript..."
            style={styles.searchInput}
            onFocus={(e) => (e.currentTarget.style.borderColor = 'var(--accent)')}
            onBlur={(e) => (e.currentTarget.style.borderColor = 'var(--border)')}
          />
          {searchQuery.trim() && (
            <span style={styles.matchCount}>
              {matchCount} match{matchCount !== 1 ? 'es' : ''}
            </span>
          )}
        </div>

        {/* Transcript text */}
        <div style={styles.textContainer}>
          {selected.text ? (
            <div
              style={styles.textContent}
              dangerouslySetInnerHTML={{
                __html: highlightText(selected.text, searchTerms),
              }}
            />
          ) : (
            <div style={styles.emptyText}>No transcript text available.</div>
          )}
        </div>
      </div>
    )
  }

  // -- List view --
  return (
    <div style={styles.page}>
      <div style={styles.listHeader}>
        <h1 style={styles.title}>Transcripts</h1>
        <span style={styles.count}>
          {transcripts.length} transcript{transcripts.length !== 1 ? 's' : ''}
        </span>
      </div>

      {transcripts.length === 0 ? (
        <div style={styles.emptyState}>
          <div style={styles.emptyIcon}>--</div>
          <div style={styles.emptyTitle}>No transcripts yet</div>
          <div style={styles.emptyMessage}>
            Run ingest with media files to generate transcripts.
          </div>
        </div>
      ) : (
        <>
          {/* Search / filter */}
          <div style={styles.searchBar}>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Filter transcripts..."
              style={styles.searchInput}
              onFocus={(e) => (e.currentTarget.style.borderColor = 'var(--accent)')}
              onBlur={(e) => (e.currentTarget.style.borderColor = 'var(--border)')}
            />
            {searchQuery.trim() && (
              <span style={styles.filterCount}>
                {filteredTranscripts.length} of {transcripts.length}
              </span>
            )}
          </div>

          {/* Transcript cards */}
          <div style={styles.cardGrid}>
            {filteredTranscripts.map((t) => (
              <button
                key={t.document_id}
                onClick={() => {
                  setSelectedId(t.document_id)
                  setSearchQuery('')
                }}
                style={styles.card}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = 'var(--accent)'
                  e.currentTarget.style.boxShadow = '0 2px 8px rgba(37,99,235,0.08)'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = 'var(--border)'
                  e.currentTarget.style.boxShadow = 'none'
                }}
              >
                <div style={styles.cardTop}>
                  <div style={styles.cardTitle}>{getFileName(t.source_path)}</div>
                  <div style={styles.cardFormat}>{getMediaFormat(t.source_path)}</div>
                </div>
                <div style={styles.cardMeta}>
                  <span style={styles.cardId}>{t.document_id}</span>
                  <span style={styles.cardDuration}>
                    {formatDuration(t.duration_seconds)}
                  </span>
                </div>
                <div style={styles.cardSnippet}>
                  {t.text
                    ? t.text.slice(0, 200) + (t.text.length > 200 ? '...' : '')
                    : 'No text available'}
                </div>
              </button>
            ))}
          </div>

          {searchQuery.trim() && filteredTranscripts.length === 0 && (
            <div style={styles.noResults}>
              No transcripts match your filter.
            </div>
          )}
        </>
      )}
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  page: {
    maxWidth: 900,
    margin: '0 auto',
    padding: '32px 24px',
  },
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

  // List view
  listHeader: {
    display: 'flex',
    alignItems: 'baseline',
    gap: 12,
    marginBottom: 24,
  },
  title: {
    fontSize: 24,
    fontWeight: 700,
    color: 'var(--text)',
  },
  count: {
    fontSize: 14,
    color: 'var(--text-muted)',
    fontWeight: 500,
  },
  searchBar: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    marginBottom: 20,
  },
  searchInput: {
    flex: 1,
    padding: '10px 16px',
    fontSize: 14,
    fontFamily: 'inherit',
    border: '1.5px solid var(--border)',
    borderRadius: 'var(--radius-md)',
    outline: 'none',
    background: 'var(--surface)',
    color: 'var(--text)',
    transition: 'border-color 0.15s ease',
  },
  filterCount: {
    fontSize: 13,
    color: 'var(--text-muted)',
    whiteSpace: 'nowrap' as const,
  },
  cardGrid: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 12,
  },
  card: {
    display: 'block',
    width: '100%',
    textAlign: 'left' as const,
    padding: 20,
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-md)',
    cursor: 'pointer',
    transition: 'border-color 0.15s ease, box-shadow 0.15s ease',
    fontFamily: 'inherit',
  },
  cardTop: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    gap: 12,
    marginBottom: 8,
  },
  cardTitle: {
    fontSize: 15,
    fontWeight: 600,
    color: 'var(--text)',
    lineHeight: 1.3,
    wordBreak: 'break-word' as const,
  },
  cardFormat: {
    fontSize: 11,
    fontWeight: 600,
    color: 'var(--accent)',
    background: 'var(--accent-light)',
    padding: '2px 8px',
    borderRadius: 12,
    whiteSpace: 'nowrap' as const,
    flexShrink: 0,
  },
  cardMeta: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    marginBottom: 10,
  },
  cardId: {
    fontSize: 12,
    color: 'var(--text-muted)',
    fontFamily: 'monospace',
  },
  cardDuration: {
    fontSize: 12,
    color: 'var(--text-muted)',
  },
  cardSnippet: {
    fontSize: 13,
    color: 'var(--text-muted)',
    lineHeight: 1.5,
    overflow: 'hidden',
    display: '-webkit-box',
    WebkitLineClamp: 3,
    WebkitBoxOrient: 'vertical' as const,
  },

  // Detail view
  backButton: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 4,
    padding: '6px 0',
    fontSize: 14,
    fontWeight: 500,
    fontFamily: 'inherit',
    color: 'var(--accent)',
    background: 'none',
    border: 'none',
    cursor: 'pointer',
    marginBottom: 20,
  },
  detailHeader: {
    marginBottom: 20,
  },
  detailTitle: {
    fontSize: 22,
    fontWeight: 700,
    color: 'var(--text)',
    marginBottom: 10,
    wordBreak: 'break-word' as const,
  },
  detailMeta: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    flexWrap: 'wrap' as const,
  },
  metaBadge: {
    display: 'inline-block',
    padding: '3px 10px',
    fontSize: 12,
    fontWeight: 600,
    borderRadius: 12,
    background: '#f3f4f6',
    color: 'var(--text-muted)',
  },
  metaId: {
    fontSize: 12,
    color: 'var(--text-muted)',
    fontFamily: 'monospace',
  },
  playerSection: {
    marginBottom: 20,
    padding: '16px 20px',
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-md)',
  },
  searchSection: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    marginBottom: 16,
  },
  matchCount: {
    fontSize: 13,
    color: 'var(--text-muted)',
    whiteSpace: 'nowrap' as const,
  },
  textContainer: {
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-md)',
    overflow: 'hidden',
  },
  textContent: {
    padding: '24px',
    fontSize: 14,
    lineHeight: 1.8,
    color: 'var(--text)',
    whiteSpace: 'pre-wrap' as const,
    maxHeight: 600,
    overflowY: 'auto' as const,
  },
  emptyText: {
    padding: '40px 24px',
    textAlign: 'center' as const,
    fontSize: 14,
    color: 'var(--text-muted)',
  },

  // Empty state
  emptyState: {
    textAlign: 'center' as const,
    padding: '80px 20px',
    color: 'var(--text-muted)',
  },
  emptyIcon: {
    fontSize: 36,
    marginBottom: 12,
    opacity: 0.5,
  },
  emptyTitle: {
    fontSize: 20,
    fontWeight: 600,
    marginBottom: 8,
    color: 'var(--text)',
  },
  emptyMessage: {
    fontSize: 14,
    color: 'var(--text-muted)',
  },
  noResults: {
    textAlign: 'center' as const,
    padding: '40px 20px',
    fontSize: 14,
    color: 'var(--text-muted)',
  },
}
