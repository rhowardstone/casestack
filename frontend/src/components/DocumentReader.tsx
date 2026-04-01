import { useState, useEffect, useCallback } from 'react'
import { fetchJSON } from '../api/client'

interface Page {
  page_number: number
  text_content: string
}

interface DocMeta {
  file_path?: string
  tags?: string
  title?: string
}

interface Props {
  slug: string
  documentId: string
  highlightTerms: string[]
  initialPage?: number
}

const IMAGE_EXTS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'tiff', 'tif'])
const VIDEO_EXTS = new Set(['mp4', 'mov', 'webm', 'avi', 'mkv', 'm4v'])

type MediaMode = 'loading' | 'pdf' | 'image' | 'video' | 'text'
type PdfTab = 'pdf' | 'text'

function getExt(filePath: string): string {
  const parts = filePath.toLowerCase().split('.')
  return parts.length > 1 ? parts[parts.length - 1] : ''
}

function highlightText(text: string, terms: string[]): string {
  if (!terms.length) return text
  const escaped = terms
    .filter(Boolean)
    .map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  if (!escaped.length) return text
  const pattern = new RegExp(`(${escaped.join('|')})`, 'gi')
  return text.replace(pattern, '<mark>$1</mark>')
}

function looksLikeEmail(text: string): boolean {
  // Matches Yahoo Mail HTML table format OR plain email headers
  return /\|\s*From:\s*\|/i.test(text) || /^From:\s+\S/im.test(text)
}

interface EmailHeaders {
  From?: string
  To?: string
  CC?: string
  BCC?: string
  Subject?: string
  Date?: string
}

function parseEmailHeaders(text: string): EmailHeaders {
  const headers: EmailHeaders = {}
  const fields: (keyof EmailHeaders)[] = ['From', 'To', 'CC', 'BCC', 'Subject', 'Date']

  const unescapeMd = (s: string) => s.replace(/\\(.)/g, '$1').trim()

  for (const field of fields) {
    // Yahoo Mail HTML table format: | Field: | value |
    const tableRe = new RegExp(`\\|\\s*${field}:\\s*\\|\\s*(.+?)(?:\\s*\\||\\n)`, 'i')
    const tableMatch = tableRe.exec(text)
    if (tableMatch) {
      headers[field] = unescapeMd(tableMatch[1])
      continue
    }
    // Plain header format: Field: value
    const plainRe = new RegExp(`^${field}:\\s*(.+)$`, 'im')
    const plainMatch = plainRe.exec(text)
    if (plainMatch) {
      headers[field] = unescapeMd(plainMatch[1])
    }
  }
  return headers
}

function EmailHeaderPanel({ headers }: { headers: EmailHeaders }) {
  const rows = (Object.entries(headers) as [keyof EmailHeaders, string][]).filter(([, v]) => v)
  if (!rows.length) return null

  return (
    <div
      style={{
        borderBottom: '1px solid var(--border)',
        background: 'var(--surface)',
        padding: '12px 20px',
        fontSize: 13,
        flexShrink: 0,
      }}
    >
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <tbody>
          {rows.map(([field, value]) => (
            <tr key={field}>
              <td
                style={{
                  paddingRight: 12,
                  paddingBottom: 4,
                  color: 'var(--text-muted)',
                  fontWeight: 600,
                  whiteSpace: 'nowrap',
                  verticalAlign: 'top',
                  width: 72,
                }}
              >
                {field}:
              </td>
              <td
                style={{
                  paddingBottom: 4,
                  color: 'var(--text)',
                  wordBreak: 'break-word',
                }}
              >
                {value}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function DocumentReader({ slug, documentId, highlightTerms, initialPage }: Props) {
  const [pages, setPages] = useState<Page[]>([])
  const [currentIndex, setCurrentIndex] = useState(0)
  const [mode, setMode] = useState<MediaMode>('loading')
  const [pdfTab, setPdfTab] = useState<PdfTab>('pdf')
  const [pdfPages, setPdfPages] = useState<Page[]>([])
  const [pdfPageIndex, setPdfPageIndex] = useState(0)
  const [pdfPagesLoading, setPdfPagesLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [filePath, setFilePath] = useState<string | null>(null)
  const [emailHeaders, setEmailHeaders] = useState<EmailHeaders>({})
  const [jumpInput, setJumpInput] = useState('')
  const [pdfJumpInput, setPdfJumpInput] = useState('')

  useEffect(() => {
    setMode('loading')
    setError(null)
    setFilePath(null)
    setPages([])
    setPdfPages([])
    setPdfTab('pdf')
    setEmailHeaders({})
    setJumpInput('')
    setPdfJumpInput('')

    fetchJSON<DocMeta>(`/cases/${slug}/documents/${documentId}`)
      .then((doc) => {
        const fp = doc.file_path ?? ''
        const ext = getExt(fp)

        if (fp && ext === 'pdf') {
          setFilePath(fp)
          setMode('pdf')
        } else if (fp && IMAGE_EXTS.has(ext)) {
          setFilePath(fp)
          setMode('image')
        } else if (fp && VIDEO_EXTS.has(ext)) {
          setFilePath(fp)
          setMode('video')
        } else {
          return fetchJSON<Page[]>(`/cases/${slug}/documents/${documentId}/pages`)
            .then((rawData) => {
              // Detect emails by content before setting state — strip headers from body
              let pages = rawData
              if (rawData.length > 0 && looksLikeEmail(rawData[0].text_content)) {
                const headers = parseEmailHeaders(rawData[0].text_content)
                if (Object.keys(headers).length >= 2) {
                  setEmailHeaders(headers)
                  const stripped = rawData[0].text_content
                    .replace(/^\|[^|\n]*\|[^\n]*\n?/gm, '')   // remove pipe-table rows
                    .replace(/^\s*\|[-| :]+\|\s*\n?/gm, '')   // remove separator rows
                    .replace(/^---+\s*\n?/m, '')               // remove leading HR separator
                    // remove leading plain-text header block (From:, To:, Subject:, Date:, etc.)
                    .replace(/^((From|To|Subject|Date|Cc|Bcc|Reply-To|Sender|Message-ID|X-\w+):[^\n]*\n?)+/im, '')
                    .trimStart()
                  pages = [{ ...rawData[0], text_content: stripped }, ...rawData.slice(1)]
                }
              }
              setPages(pages)
              if (initialPage != null) {
                const idx = pages.findIndex((p) => p.page_number === initialPage)
                if (idx >= 0) setCurrentIndex(idx)
              }
              setMode('text')
            })
        }
      })
      .catch((err) => {
        setError(err.message || 'Failed to load document')
        setMode('text')
      })
  }, [slug, documentId, initialPage])

  // Load pages for PDF text tab on demand
  const loadPdfPages = useCallback(() => {
    if (pdfPages.length > 0) return
    setPdfPagesLoading(true)
    fetchJSON<Page[]>(`/cases/${slug}/documents/${documentId}/pages`)
      .then((data) => {
        setPdfPages(data)
        if (initialPage != null) {
          const idx = data.findIndex((p) => p.page_number === initialPage)
          if (idx >= 0) setPdfPageIndex(idx)
        }
      })
      .catch(() => {})
      .finally(() => setPdfPagesLoading(false))
  }, [slug, documentId, initialPage, pdfPages.length])

  const handlePdfTabChange = useCallback(
    (tab: PdfTab) => {
      setPdfTab(tab)
      if (tab === 'text') loadPdfPages()
    },
    [loadPdfPages],
  )

  const goNext = useCallback(() => {
    setCurrentIndex((i) => Math.min(i + 1, pages.length - 1))
    setJumpInput('')
  }, [pages.length])

  const goPrev = useCallback(() => {
    setCurrentIndex((i) => Math.max(i - 1, 0))
    setJumpInput('')
  }, [])

  const goPdfNext = useCallback(() => {
    setPdfPageIndex((i) => Math.min(i + 1, pdfPages.length - 1))
    setPdfJumpInput('')
  }, [pdfPages.length])

  const goPdfPrev = useCallback(() => {
    setPdfPageIndex((i) => Math.max(i - 1, 0))
    setPdfJumpInput('')
  }, [])

  const handleJump = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key !== 'Enter') return
      const n = parseInt(jumpInput, 10)
      if (!isNaN(n) && n >= 1 && n <= pages.length) {
        const idx = pages.findIndex((p) => p.page_number === n)
        if (idx >= 0) setCurrentIndex(idx)
        else setCurrentIndex(n - 1)
      }
      setJumpInput('')
    },
    [jumpInput, pages],
  )

  const handlePdfJump = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key !== 'Enter') return
      const n = parseInt(pdfJumpInput, 10)
      if (!isNaN(n) && n >= 1 && n <= pdfPages.length) {
        const idx = pdfPages.findIndex((p) => p.page_number === n)
        if (idx >= 0) setPdfPageIndex(idx)
        else setPdfPageIndex(n - 1)
      }
      setPdfJumpInput('')
    },
    [pdfJumpInput, pdfPages],
  )

  const fileUrl = `/api/cases/${slug}/documents/${documentId}/file`

  if (mode === 'loading') {
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

  // PDF mode — with tab bar for PDF | Text
  if (mode === 'pdf') {
    const page = initialPage ?? 1
    return (
      <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        {/* Tab bar */}
        <div
          style={{
            display: 'flex',
            gap: 0,
            borderBottom: '1px solid var(--border)',
            background: 'var(--surface)',
            flexShrink: 0,
          }}
        >
          {(['pdf', 'text'] as PdfTab[]).map((tab) => (
            <button
              key={tab}
              onClick={() => handlePdfTabChange(tab)}
              style={{
                padding: '8px 18px',
                fontSize: 13,
                fontWeight: 500,
                fontFamily: 'inherit',
                border: 'none',
                borderBottom: pdfTab === tab ? '2px solid var(--accent)' : '2px solid transparent',
                background: 'transparent',
                color: pdfTab === tab ? 'var(--accent)' : 'var(--text-muted)',
                cursor: 'pointer',
                transition: 'color 0.15s',
                textTransform: 'capitalize',
              }}
            >
              {tab === 'pdf' ? 'PDF' : 'Extracted Text'}
            </button>
          ))}
        </div>

        {pdfTab === 'pdf' ? (
          <iframe
            src={`${fileUrl}#page=${page}`}
            style={{ flex: 1, width: '100%', border: 'none', display: 'block' }}
            title="PDF viewer"
          />
        ) : pdfPagesLoading ? (
          <div style={{ padding: '20px 24px', color: 'var(--text-muted)', fontSize: 14 }}>
            Loading text...
          </div>
        ) : pdfPages.length === 0 ? (
          <div style={{ padding: '20px 24px', color: 'var(--text-muted)', fontSize: 14 }}>
            No extracted text available for this PDF.
          </div>
        ) : (
          <TextPageView
            pages={pdfPages}
            currentIndex={pdfPageIndex}
            jumpInput={pdfJumpInput}
            setJumpInput={setPdfJumpInput}
            onPrev={goPdfPrev}
            onNext={goPdfNext}
            onJump={handlePdfJump}
            highlightTerms={highlightTerms}
            emailHeaders={null}
          />
        )}
      </div>
    )
  }

  // Image mode
  if (mode === 'image') {
    return (
      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: 16, display: 'flex', alignItems: 'flex-start', justifyContent: 'center' }}>
        <img
          src={fileUrl}
          alt={documentId}
          style={{ maxWidth: '100%', height: 'auto', borderRadius: 4, boxShadow: '0 2px 8px rgba(0,0,0,0.12)' }}
        />
      </div>
    )
  }

  // Video mode
  if (mode === 'video') {
    return (
      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: 16, display: 'flex', alignItems: 'flex-start', justifyContent: 'center' }}>
        <video
          src={fileUrl}
          controls
          style={{ maxWidth: '100%', borderRadius: 4 }}
        />
      </div>
    )
  }

  // Text mode
  if (!pages.length) {
    return (
      <div style={{ padding: '20px 24px', color: 'var(--text-muted)', fontSize: 14 }}>
        No pages found for this document.
      </div>
    )
  }

  return (
    <TextPageView
      pages={pages}
      currentIndex={currentIndex}
      jumpInput={jumpInput}
      setJumpInput={setJumpInput}
      onPrev={goPrev}
      onNext={goNext}
      onJump={handleJump}
      highlightTerms={highlightTerms}
      emailHeaders={Object.keys(emailHeaders).length > 0 ? emailHeaders : null}
    />
  )
}

interface TextPageViewProps {
  pages: Page[]
  currentIndex: number
  jumpInput: string
  setJumpInput: (v: string) => void
  onPrev: () => void
  onNext: () => void
  onJump: (e: React.KeyboardEvent<HTMLInputElement>) => void
  highlightTerms: string[]
  emailHeaders: EmailHeaders | null
}

function TextPageView({
  pages,
  currentIndex,
  jumpInput,
  setJumpInput,
  onPrev,
  onNext,
  onJump,
  highlightTerms,
  emailHeaders,
}: TextPageViewProps) {
  const page = pages[currentIndex]
  const atStart = currentIndex === 0
  const atEnd = currentIndex === pages.length - 1

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
      {emailHeaders && <EmailHeaderPanel headers={emailHeaders} />}

      {/* Pagination bar */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '8px 20px',
          borderBottom: '1px solid var(--border)',
          flexShrink: 0,
          gap: 8,
        }}
      >
        <button
          onClick={onPrev}
          disabled={atStart}
          style={navBtnStyle(atStart)}
        >
          Prev
        </button>

        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: 'var(--text-muted)' }}>
          <span>Page</span>
          <input
            type="text"
            value={jumpInput}
            onChange={(e) => setJumpInput(e.target.value)}
            onKeyDown={onJump}
            placeholder={String(page.page_number)}
            title="Enter page number and press Enter to jump"
            style={{
              width: 44,
              padding: '2px 6px',
              fontSize: 13,
              textAlign: 'center',
              border: '1px solid var(--border)',
              borderRadius: 4,
              background: 'var(--surface)',
              color: 'var(--text)',
              fontFamily: 'inherit',
              outline: 'none',
            }}
          />
          <span>of {pages.length}</span>
        </div>

        <button
          onClick={onNext}
          disabled={atEnd}
          style={navBtnStyle(atEnd)}
        >
          Next
        </button>
      </div>

      {/* Page content */}
      <div
        style={{
          flex: 1,
          padding: '20px 24px',
          fontSize: 14,
          lineHeight: 1.8,
          color: 'var(--text)',
          whiteSpace: 'pre-wrap',
          overflowY: 'auto',
        }}
        dangerouslySetInnerHTML={{
          __html: highlightText(page.text_content, highlightTerms),
        }}
      />
    </div>
  )
}

function navBtnStyle(disabled: boolean): React.CSSProperties {
  return {
    padding: '4px 14px',
    fontSize: 13,
    fontWeight: 500,
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-sm)',
    background: disabled ? '#f3f4f6' : 'var(--surface)',
    color: disabled ? 'var(--text-muted)' : 'var(--text)',
    cursor: disabled ? 'not-allowed' : 'pointer',
    fontFamily: 'inherit',
  }
}
