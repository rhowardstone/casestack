import { useState, useEffect, useCallback } from 'react'
import { fetchJSON } from '../api/client'

interface Page {
  page_number: number
  text_content: string
}

interface Props {
  slug: string
  documentId: string
  highlightTerms: string[]
  initialPage?: number
}

function highlightText(text: string, terms: string[]): string {
  if (!terms.length) return text
  // Escape regex special chars and build pattern
  const escaped = terms
    .filter(Boolean)
    .map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  if (!escaped.length) return text
  const pattern = new RegExp(`(${escaped.join('|')})`, 'gi')
  return text.replace(pattern, '<mark>$1</mark>')
}

export default function DocumentReader({ slug, documentId, highlightTerms, initialPage }: Props) {
  const [pages, setPages] = useState<Page[]>([])
  const [currentIndex, setCurrentIndex] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    fetchJSON<Page[]>(`/cases/${slug}/documents/${documentId}/pages`)
      .then((data) => {
        setPages(data)
        // Jump to the page matching initialPage if specified
        if (initialPage != null) {
          const idx = data.findIndex((p) => p.page_number === initialPage)
          if (idx >= 0) setCurrentIndex(idx)
        }
      })
      .catch((err) => {
        setError(err.message || 'Failed to load pages')
      })
      .finally(() => setLoading(false))
  }, [slug, documentId, initialPage])

  const goNext = useCallback(() => {
    setCurrentIndex((i) => Math.min(i + 1, pages.length - 1))
  }, [pages.length])

  const goPrev = useCallback(() => {
    setCurrentIndex((i) => Math.max(i - 1, 0))
  }, [])

  if (loading) {
    return (
      <div style={{ padding: '20px 24px', color: 'var(--text-muted)', fontSize: 14 }}>
        Loading document...
      </div>
    )
  }

  if (error) {
    return (
      <div style={{ padding: '20px 24px', color: 'var(--danger)', fontSize: 14 }}>
        {error}
      </div>
    )
  }

  if (!pages.length) {
    return (
      <div style={{ padding: '20px 24px', color: 'var(--text-muted)', fontSize: 14 }}>
        No pages found for this document.
      </div>
    )
  }

  const page = pages[currentIndex]

  return (
    <div
      style={{
        borderTop: '1px solid var(--border)',
        background: '#f9fafb',
      }}
    >
      {/* Navigation header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '10px 20px',
          borderBottom: '1px solid var(--border)',
        }}
      >
        <button
          onClick={goPrev}
          disabled={currentIndex === 0}
          style={{
            padding: '4px 14px',
            fontSize: 13,
            fontWeight: 500,
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius-sm)',
            background: currentIndex === 0 ? '#f3f4f6' : 'var(--surface)',
            color: currentIndex === 0 ? 'var(--text-muted)' : 'var(--text)',
            cursor: currentIndex === 0 ? 'not-allowed' : 'pointer',
            fontFamily: 'inherit',
          }}
        >
          Prev
        </button>

        <span style={{ fontSize: 13, color: 'var(--text-muted)', fontWeight: 500 }}>
          Page {page.page_number} of {pages.length}
        </span>

        <button
          onClick={goNext}
          disabled={currentIndex === pages.length - 1}
          style={{
            padding: '4px 14px',
            fontSize: 13,
            fontWeight: 500,
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius-sm)',
            background: currentIndex === pages.length - 1 ? '#f3f4f6' : 'var(--surface)',
            color: currentIndex === pages.length - 1 ? 'var(--text-muted)' : 'var(--text)',
            cursor: currentIndex === pages.length - 1 ? 'not-allowed' : 'pointer',
            fontFamily: 'inherit',
          }}
        >
          Next
        </button>
      </div>

      {/* Page content */}
      <div
        style={{
          padding: '20px 24px',
          fontSize: 14,
          lineHeight: 1.8,
          color: 'var(--text)',
          whiteSpace: 'pre-wrap',
          maxHeight: 400,
          overflowY: 'auto',
        }}
        dangerouslySetInnerHTML={{
          __html: highlightText(page.text_content, highlightTerms),
        }}
      />
    </div>
  )
}
