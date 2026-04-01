import React, { useState, useEffect, useMemo, useCallback } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { fetchJSON } from '../api/client'
import DocumentReader from '../components/DocumentReader'

interface Document {
  doc_id: string
  title: string
  date: string | null
  tags: string | null
  total_pages: number | null
  total_chars: number | null
  file_path: string | null
  category: string | null
}

const PAGE_SIZE = 50

type SortKey = 'date_desc' | 'date_asc' | 'title'

function getDocType(tags: string | null, filePath: string | null): { label: string; color: string } {
  const t = (tags ?? '').toLowerCase()
  const ext = filePath ? filePath.split('.').pop()?.toLowerCase() ?? '' : ''

  if (t.includes('pdf') || ext === 'pdf') return { label: 'PDF', color: '#ef4444' }
  if (t.includes('eml') || t.includes('email') || t.includes('msg') || ext === 'eml' || ext === 'msg')
    return { label: 'Email', color: '#3b82f6' }
  if (t.includes('transcript') || t.includes('whisper') || ext === 'vtt' || ext === 'srt')
    return { label: 'Transcript', color: '#f97316' }
  if (t.includes('xlsx') || t.includes('xls') || t.includes('csv') || ext === 'xlsx' || ext === 'csv')
    return { label: 'Spreadsheet', color: '#22c55e' }
  if (t.includes('docx') || t.includes('doc') || ext === 'docx' || ext === 'doc')
    return { label: 'Word', color: '#8b5cf6' }
  if (t.includes('pptx') || t.includes('ppt') || ext === 'pptx')
    return { label: 'Slides', color: '#ec4899' }
  if (t.includes('html') || t.includes('htm') || ext === 'html' || ext === 'htm')
    return { label: 'HTML', color: '#a855f7' }
  if (t.includes('image') || t.includes('png') || t.includes('jpg') || t.includes('jpeg'))
    return { label: 'Image', color: '#eab308' }
  if (t.includes('mp4') || t.includes('mov') || t.includes('webm') || t.includes('video'))
    return { label: 'Video', color: '#14b8a6' }
  if (t.includes('txt') || t.includes('md') || ext === 'txt' || ext === 'md')
    return { label: 'Text', color: '#6b7280' }
  return { label: 'Doc', color: '#6b7280' }
}

function TypeBadge({ tags, filePath }: { tags: string | null; filePath: string | null }) {
  const { label, color } = getDocType(tags, filePath)
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '2px 8px',
        fontSize: 11,
        fontWeight: 600,
        letterSpacing: '0.04em',
        borderRadius: 4,
        background: color + '1a',
        color,
        border: `1px solid ${color}33`,
        whiteSpace: 'nowrap',
      }}
    >
      {label}
    </span>
  )
}

const TYPE_FILTERS = [
  { value: 'all', label: 'All' },
  { value: 'pdf', label: 'PDF' },
  { value: 'email', label: 'Email' },
  { value: 'transcript', label: 'Transcripts' },
  { value: 'spreadsheet', label: 'Spreadsheets' },
  { value: 'image', label: 'Images' },
  { value: 'html', label: 'HTML' },
  { value: 'text', label: 'Text' },
]

function matchesTypeFilter(doc: Document, filter: string): boolean {
  if (filter === 'all') return true
  const t = (doc.tags ?? '').toLowerCase()
  const ext = doc.file_path ? doc.file_path.split('.').pop()?.toLowerCase() ?? '' : ''
  switch (filter) {
    case 'pdf': return t.includes('pdf') || ext === 'pdf'
    case 'email': return t.includes('eml') || t.includes('email') || t.includes('msg') || ext === 'eml' || ext === 'msg'
    case 'transcript': return t.includes('transcript') || t.includes('whisper')
    case 'spreadsheet': return t.includes('xlsx') || t.includes('xls') || t.includes('csv') || ext === 'csv'
    case 'image': return t.includes('image') || t.includes('png') || t.includes('jpg')
    case 'html': return (t.includes('html') || ext === 'html') && !t.includes('email') && !t.includes('eml')
    case 'text': return t.includes('txt') || t.includes('.txt') || ext === 'txt'
    default: return true
  }
}

export default function DocumentBrowser() {
  const { slug = '' } = useParams<{ slug: string }>()
  const [searchParams, setSearchParams] = useSearchParams()

  const [docs, setDocs] = useState<Document[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [total, setTotal] = useState(0)

  const [query, setQuery] = useState(() => searchParams.get('q') ?? '')
  const [typeFilter, setTypeFilter] = useState(() => searchParams.get('type') ?? 'all')
  const [sort, setSort] = useState<SortKey>(() => (searchParams.get('sort') as SortKey) ?? 'date_desc')
  const [page, setPage] = useState(() => parseInt(searchParams.get('page') ?? '1', 10))
  const [expandedId, setExpandedId] = useState<string | null>(null)

  // Sync search params
  useEffect(() => {
    const params: Record<string, string> = {}
    if (query) params.q = query
    if (typeFilter !== 'all') params.type = typeFilter
    if (sort !== 'date_desc') params.sort = sort
    if (page > 1) params.page = String(page)
    setSearchParams(params, { replace: true })
  }, [query, typeFilter, sort, page, setSearchParams])

  // Fetch all docs (we filter client-side for instant response, paginate server-side for large sets)
  useEffect(() => {
    if (!slug) return
    setLoading(true)
    setError(null)
    const apiSort = sort === 'date_desc' || sort === 'date_asc' ? 'date' : 'doc_id'
    fetchJSON<Document[]>(`/cases/${slug}/documents?sort=${apiSort}`)
      .then((data) => {
        setDocs(data)
        setTotal(data.length)
      })
      .catch((err) => setError(err.message || 'Failed to load documents'))
      .finally(() => setLoading(false))
  }, [slug, sort])

  const filtered = useMemo(() => {
    let result = docs
    if (query.trim()) {
      const q = query.trim().toLowerCase()
      result = result.filter((d) => d.title.toLowerCase().includes(q))
    }
    if (typeFilter !== 'all') {
      result = result.filter((d) => matchesTypeFilter(d, typeFilter))
    }
    if (sort === 'date_desc') {
      result = [...result].sort((a, b) => {
        if (!a.date && !b.date) return 0
        if (!a.date) return 1
        if (!b.date) return -1
        return b.date.localeCompare(a.date)
      })
    } else if (sort === 'date_asc') {
      result = [...result].sort((a, b) => {
        if (!a.date && !b.date) return 0
        if (!a.date) return 1
        if (!b.date) return -1
        return a.date.localeCompare(b.date)
      })
    } else {
      result = [...result].sort((a, b) => a.title.localeCompare(b.title))
    }
    return result
  }, [docs, query, typeFilter, sort])

  const pageCount = Math.ceil(filtered.length / PAGE_SIZE)
  const pageDocs = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  const handleTypeFilter = useCallback((f: string) => {
    setTypeFilter(f)
    setPage(1)
  }, [])

  const handleSort = useCallback((s: SortKey) => {
    setSort(s)
    setPage(1)
  }, [])

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: '32px 24px' }}>
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: 'var(--text)' }}>Documents</h2>
          {!loading && (
            <div style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 2 }}>
              {filtered.length.toLocaleString()} document{filtered.length !== 1 ? 's' : ''}
              {typeFilter !== 'all' || query ? ` (filtered from ${total.toLocaleString()})` : ''}
            </div>
          )}
        </div>

        {/* Sort selector */}
        <select
          value={sort}
          onChange={(e) => handleSort(e.target.value as SortKey)}
          style={{
            padding: '6px 10px',
            fontSize: 13,
            border: '1px solid var(--border)',
            borderRadius: 6,
            background: 'var(--surface)',
            color: 'var(--text)',
            fontFamily: 'inherit',
            cursor: 'pointer',
          }}
        >
          <option value="date_desc">Date: newest first</option>
          <option value="date_asc">Date: oldest first</option>
          <option value="title">Title A–Z</option>
        </select>
      </div>

      {/* Search input */}
      <div style={{ marginBottom: 16 }}>
        <input
          type="text"
          value={query}
          onChange={(e) => { setQuery(e.target.value); setPage(1) }}
          placeholder="Filter by title..."
          style={{
            width: '100%',
            padding: '10px 16px',
            fontSize: 14,
            fontFamily: 'inherit',
            border: '1px solid var(--border)',
            borderRadius: 8,
            outline: 'none',
            background: 'var(--surface)',
            color: 'var(--text)',
            boxSizing: 'border-box',
          }}
          onFocus={(e) => (e.currentTarget.style.borderColor = 'var(--accent)')}
          onBlur={(e) => (e.currentTarget.style.borderColor = 'var(--border)')}
        />
      </div>

      {/* Type filter pills */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 20, flexWrap: 'wrap' }}>
        {TYPE_FILTERS.map((opt) => {
          const active = typeFilter === opt.value
          return (
            <button
              key={opt.value}
              onClick={() => handleTypeFilter(opt.value)}
              style={{
                padding: '5px 12px',
                fontSize: 12,
                fontWeight: 500,
                fontFamily: 'inherit',
                border: `1px solid ${active ? 'var(--accent)' : 'var(--border)'}`,
                borderRadius: 20,
                background: active ? 'var(--accent)' : 'var(--surface)',
                color: active ? '#fff' : 'var(--text-muted)',
                cursor: 'pointer',
                transition: 'all 0.15s ease',
              }}
            >
              {opt.label}
            </button>
          )
        })}
      </div>

      {/* Error */}
      {error && (
        <div style={{ padding: 16, color: 'var(--danger)', fontSize: 14, marginBottom: 16 }}>
          {error}
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)', fontSize: 14 }}>
          Loading documents...
        </div>
      )}

      {/* Document table */}
      {!loading && pageDocs.length > 0 && (
        <div style={{ border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
          {/* Table header */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '80px 1fr 110px 100px',
              gap: 0,
              padding: '8px 16px',
              background: 'var(--surface)',
              borderBottom: '1px solid var(--border)',
              fontSize: 11,
              fontWeight: 600,
              color: 'var(--text-muted)',
              letterSpacing: '0.06em',
              textTransform: 'uppercase',
            }}
          >
            <div>Type</div>
            <div>Title</div>
            <div style={{ textAlign: 'right' }}>Date</div>
            <div style={{ textAlign: 'right' }}>Size</div>
          </div>

          {/* Rows */}
          {pageDocs.map((doc) => {
            const isExpanded = expandedId === doc.doc_id
            return (
              <div key={doc.doc_id}>
                <div
                  onClick={() => setExpandedId(isExpanded ? null : doc.doc_id)}
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '80px 1fr 110px 100px',
                    gap: 0,
                    padding: '10px 16px',
                    borderBottom: '1px solid var(--border)',
                    cursor: 'pointer',
                    background: isExpanded ? 'var(--accent-light, rgba(59,130,246,0.06))' : 'var(--bg)',
                    transition: 'background 0.1s',
                    alignItems: 'center',
                  }}
                  onMouseEnter={(e) => {
                    if (!isExpanded) (e.currentTarget as HTMLDivElement).style.background = 'var(--surface)'
                  }}
                  onMouseLeave={(e) => {
                    if (!isExpanded) (e.currentTarget as HTMLDivElement).style.background = 'var(--bg)'
                  }}
                >
                  <div>
                    <TypeBadge tags={doc.tags} filePath={doc.file_path} />
                  </div>
                  <div style={{
                    fontSize: 14,
                    color: 'var(--text)',
                    fontWeight: 500,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    paddingRight: 12,
                  }}>
                    {doc.title || doc.doc_id}
                  </div>
                  <div style={{ fontSize: 13, color: 'var(--text-muted)', textAlign: 'right' }}>
                    {doc.date ?? '—'}
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)', textAlign: 'right' }}>
                    {doc.total_chars != null
                      ? doc.total_chars > 1000
                        ? `${Math.round(doc.total_chars / 1000)}k chars`
                        : `${doc.total_chars} chars`
                      : doc.total_pages != null
                      ? `${doc.total_pages}p`
                      : '—'}
                  </div>
                </div>

                {isExpanded && (
                  <div
                    style={{
                      borderBottom: '1px solid var(--border)',
                      background: 'var(--bg)',
                      height: 520,
                      display: 'flex',
                      flexDirection: 'column',
                      overflow: 'hidden',
                    }}
                  >
                    <DocumentReader
                      slug={slug}
                      documentId={doc.doc_id}
                      highlightTerms={query.trim().split(/\s+/).filter((t) => t.length > 1)}
                    />
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Empty state */}
      {!loading && pageDocs.length === 0 && !error && (
        <div style={{ textAlign: 'center', padding: '60px 20px', color: 'var(--text-muted)' }}>
          <div style={{ fontSize: 32, marginBottom: 10 }}>No documents</div>
          <div style={{ fontSize: 14 }}>
            {query || typeFilter !== 'all'
              ? 'Try clearing the filters.'
              : 'No documents have been ingested into this case yet.'}
          </div>
        </div>
      )}

      {/* Pagination */}
      {pageCount > 1 && (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, marginTop: 24 }}>
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            style={paginationBtnStyle(page === 1)}
          >
            Previous
          </button>
          <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>
            Page {page} of {pageCount}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
            disabled={page === pageCount}
            style={paginationBtnStyle(page === pageCount)}
          >
            Next
          </button>
        </div>
      )}
    </div>
  )
}

function paginationBtnStyle(disabled: boolean): React.CSSProperties {
  return {
    padding: '6px 16px',
    fontSize: 13,
    fontWeight: 500,
    fontFamily: 'inherit',
    border: '1px solid var(--border)',
    borderRadius: 6,
    background: disabled ? 'var(--surface)' : 'var(--surface)',
    color: disabled ? 'var(--text-muted)' : 'var(--text)',
    cursor: disabled ? 'not-allowed' : 'pointer',
    opacity: disabled ? 0.5 : 1,
  }
}
