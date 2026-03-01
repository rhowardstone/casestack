import type { SearchResult } from '../hooks/useSearch'

const TYPE_STYLES: Record<string, { bg: string; color: string; label: string }> = {
  page: { bg: 'var(--accent-light)', color: 'var(--accent)', label: 'Page' },
  transcript: { bg: '#dcfce7', color: '#16a34a', label: 'Transcript' },
  image: { bg: '#f3e8ff', color: '#9333ea', label: 'Image' },
}

interface Props {
  result: SearchResult
  expanded: boolean
  onToggle: () => void
}

export default function SearchResultCard({ result, expanded, onToggle }: Props) {
  const typeStyle = TYPE_STYLES[result.type] ?? TYPE_STYLES.page

  return (
    <div
      style={{
        background: 'var(--surface)',
        border: `1px solid ${expanded ? 'var(--accent)' : 'var(--border)'}`,
        borderRadius: 'var(--radius-md)',
        overflow: 'hidden',
        transition: 'border-color 0.15s ease',
      }}
    >
      <button
        onClick={onToggle}
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          gap: 12,
          width: '100%',
          padding: '16px 20px',
          background: 'none',
          border: 'none',
          cursor: 'pointer',
          textAlign: 'left',
          fontFamily: 'inherit',
          color: 'inherit',
        }}
      >
        {/* Type badge */}
        <span
          style={{
            flexShrink: 0,
            display: 'inline-block',
            padding: '2px 10px',
            borderRadius: 'var(--radius-sm)',
            fontSize: 12,
            fontWeight: 600,
            background: typeStyle.bg,
            color: typeStyle.color,
            marginTop: 2,
          }}
        >
          {typeStyle.label}
        </span>

        <div style={{ flex: 1, minWidth: 0 }}>
          {/* Title row */}
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 4 }}>
            <span style={{ fontWeight: 600, fontSize: 15, color: 'var(--text)' }}>
              {result.title || result.document_id}
            </span>
            {result.page_number != null && (
              <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>
                p.{result.page_number}
              </span>
            )}
          </div>

          {/* Snippet with highlighted <mark> tags */}
          <div
            style={{ fontSize: 14, color: 'var(--text-muted)', lineHeight: 1.6 }}
            dangerouslySetInnerHTML={{ __html: result.snippet }}
          />
        </div>

        {/* Expand/collapse chevron */}
        <span
          style={{
            flexShrink: 0,
            fontSize: 18,
            color: 'var(--text-muted)',
            transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)',
            transition: 'transform 0.15s ease',
            marginTop: 2,
          }}
        >
          &#9660;
        </span>
      </button>
    </div>
  )
}
