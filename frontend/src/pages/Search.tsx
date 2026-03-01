import { useState, useMemo } from 'react'
import { useParams } from 'react-router-dom'
import { useSearch } from '../hooks/useSearch'
import SearchResultCard from '../components/SearchResultCard'
import DocumentReader from '../components/DocumentReader'

const TYPE_OPTIONS = [
  { value: 'all', label: 'All' },
  { value: 'page', label: 'Pages' },
  { value: 'transcript', label: 'Transcripts' },
  { value: 'image', label: 'Images' },
] as const

export default function Search() {
  const { slug = '' } = useParams<{ slug: string }>()
  const [query, setQuery] = useState('')
  const [typeFilter, setTypeFilter] = useState('all')
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const { results, total, loading } = useSearch(slug, query, typeFilter)

  // Extract search terms for highlighting inside DocumentReader
  const highlightTerms = useMemo(
    () =>
      query
        .trim()
        .split(/\s+/)
        .filter((t) => t.length > 1),
    [query],
  )

  return (
    <div style={{ maxWidth: 860, margin: '0 auto', padding: '40px 24px' }}>
      {/* Search input */}
      <div style={{ marginBottom: 28 }}>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search documents, transcripts, images..."
          style={{
            width: '100%',
            padding: '14px 20px',
            fontSize: 17,
            fontFamily: 'inherit',
            border: '2px solid var(--border)',
            borderRadius: 'var(--radius-lg)',
            outline: 'none',
            background: 'var(--surface)',
            color: 'var(--text)',
            transition: 'border-color 0.15s ease',
          }}
          onFocus={(e) => (e.currentTarget.style.borderColor = 'var(--accent)')}
          onBlur={(e) => (e.currentTarget.style.borderColor = 'var(--border)')}
        />
      </div>

      {/* Type filter pills */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 24, flexWrap: 'wrap' }}>
        {TYPE_OPTIONS.map((opt) => {
          const active = typeFilter === opt.value
          return (
            <button
              key={opt.value}
              onClick={() => setTypeFilter(opt.value)}
              style={{
                padding: '6px 16px',
                fontSize: 13,
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

      {/* Results count / loading */}
      {query.trim() && (
        <div style={{ marginBottom: 16, fontSize: 14, color: 'var(--text-muted)' }}>
          {loading ? (
            'Searching...'
          ) : (
            <>
              {total} result{total !== 1 ? 's' : ''} found
            </>
          )}
        </div>
      )}

      {/* Results list */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {results.map((r) => {
          const key = `${r.document_id}-${r.page_number ?? 'x'}-${r.rank}`
          const isExpanded = expandedId === key

          return (
            <div key={key}>
              <SearchResultCard
                result={r}
                expanded={isExpanded}
                onToggle={() => setExpandedId(isExpanded ? null : key)}
              />
              {isExpanded && (
                <DocumentReader
                  slug={slug}
                  documentId={r.document_id}
                  highlightTerms={highlightTerms}
                  initialPage={r.page_number}
                />
              )}
            </div>
          )
        })}
      </div>

      {/* Empty state */}
      {!loading && query.trim() && results.length === 0 && (
        <div
          style={{
            textAlign: 'center',
            padding: '60px 20px',
            color: 'var(--text-muted)',
          }}
        >
          <div style={{ fontSize: 36, marginBottom: 12 }}>No results</div>
          <div style={{ fontSize: 15 }}>
            Try different keywords or change the type filter.
          </div>
        </div>
      )}

      {/* Initial state */}
      {!query.trim() && (
        <div
          style={{
            textAlign: 'center',
            padding: '80px 20px',
            color: 'var(--text-muted)',
          }}
        >
          <div style={{ fontSize: 36, marginBottom: 12 }}>Search</div>
          <div style={{ fontSize: 15 }}>
            Enter a query above to search across all documents in this case.
          </div>
        </div>
      )}
    </div>
  )
}
