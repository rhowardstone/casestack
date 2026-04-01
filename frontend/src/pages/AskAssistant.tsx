import { useState, useRef, useEffect, useCallback } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { TOP_NAV_HEIGHT } from '../components/Sidebar'
import { marked } from 'marked'
import { streamAsk } from '../api/ask'
import {
  listConversations,
  deleteConversation,
  getConversation,
  type Conversation,
  type ConversationMessage,
} from '../api/conversations'
import { fetchJSON } from '../api/client'
import DocumentReader from '../components/DocumentReader'

marked.setOptions({ breaks: true, gfm: true })

interface Source {
  doc_id: string
  title: string
  page: number
}

interface Message {
  role: 'user' | 'assistant'
  content: string
  sources?: Source[]
  status?: string
  loading?: boolean
}

interface CaseStats {
  date_min: string | null
  date_max: string | null
  docs_by_year: { year: string; count: number }[]
  top_entities: { name: string; type: string; count: number }[]
}

const FALLBACK_QUESTIONS = [
  'What are the key findings in this case?',
  'Who are the main persons mentioned?',
  'Summarize the financial transactions',
]

function buildSuggestedQuestions(stats: CaseStats): string[] {
  const questions: string[] = []

  // Add person-specific questions for top entities
  const persons = stats.top_entities.filter(e => e.type === 'PERSON').slice(0, 2)
  for (const p of persons) {
    questions.push(`Who is ${p.name} and what role do they play in this case?`)
  }

  // Peak year question
  if (stats.docs_by_year.length > 0) {
    const peakYear = stats.docs_by_year.reduce((a, b) => a.count > b.count ? a : b)
    questions.push(`What was happening in ${peakYear.year}? Why the spike in activity?`)
  }

  // ORG/GPE entities
  const places = stats.top_entities.filter(e => e.type === 'GPE' || e.type === 'ORG').slice(0, 1)
  if (places.length > 0) {
    questions.push(`What is the significance of ${places[0].name} in this case?`)
  }

  // Generic fallback questions
  questions.push('What are the most unusual or suspicious documents?')

  return questions.slice(0, 4)
}

function useIsMobile() {
  const [isMobile, setIsMobile] = useState(() => window.innerWidth < 768)
  useEffect(() => {
    const handle = () => setIsMobile(window.innerWidth < 768)
    window.addEventListener('resize', handle)
    return () => window.removeEventListener('resize', handle)
  }, [])
  return isMobile
}

// Conversation history sidebar opens by default only when there's room for all three panels
const SIDEBAR_AUTO_OPEN_WIDTH = 1024

export default function AskAssistant() {
  const { slug = '' } = useParams<{ slug: string }>()
  const [searchParams] = useSearchParams()
  const isMobile = useIsMobile()

  // Corpus-specific suggested questions
  const [suggestedQuestions, setSuggestedQuestions] = useState<string[]>(FALLBACK_QUESTIONS)

  // Conversations sidebar state — start closed on mobile
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeConvId, setActiveConvId] = useState<string | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth >= SIDEBAR_AUTO_OPEN_WIDTH)

  // Chat state
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)

  // Document viewer state (clicked source chip)
  const [viewerDoc, setViewerDoc] = useState<{ docId: string; page: number; title: string } | null>(null)

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  // Load conversation list on mount; open ?conv=<id> if provided
  useEffect(() => {
    const convParam = searchParams.get('conv')
    listConversations(slug)
      .then(list => {
        setConversations(list)
        if (convParam && list.find(c => c.id === convParam)) {
          switchConversation(convParam)
        }
      })
      .catch(() => {}) // non-fatal

    // Load corpus stats for suggested questions
    fetchJSON<CaseStats>(`/cases/${slug}/stats`)
      .then(stats => {
        const qs = buildSuggestedQuestions(stats)
        if (qs.length > 0) setSuggestedQuestions(qs)
      })
      .catch(() => {}) // non-fatal — fall back to defaults
  }, [slug]) // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Focus input after render
  useEffect(() => {
    inputRef.current?.focus()
  }, [activeConvId])

  const switchConversation = useCallback(async (convId: string) => {
    try {
      const detail = await getConversation(slug, convId)
      setActiveConvId(convId)
      const loaded: Message[] = detail.messages.map((m: ConversationMessage) => ({
        role: m.role,
        content: m.content,
        sources: m.sources_json ? JSON.parse(m.sources_json) : undefined,
      }))
      // If the last message is from the user with no assistant reply, the response was lost
      if (loaded.length > 0 && loaded[loaded.length - 1].role === 'user') {
        loaded.push({
          role: 'assistant',
          content: '*Response was not saved — this conversation may have been interrupted. You can ask again below.*',
        })
      }
      setMessages(loaded)
    } catch {
      // ignore
    }
  }, [slug])

  const startNewChat = useCallback(() => {
    setActiveConvId(null)
    setMessages([])
    setInput('')
    inputRef.current?.focus()
  }, [])

  const handleDeleteConversation = useCallback(async (convId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    await deleteConversation(slug, convId)
    setConversations(prev => prev.filter(c => c.id !== convId))
    if (activeConvId === convId) {
      startNewChat()
    }
  }, [slug, activeConvId, startNewChat])

  const handleSubmit = useCallback(async () => {
    const question = input.trim()
    if (!question || isStreaming) return

    setInput('')
    setIsStreaming(true)

    const userMsg: Message = { role: 'user', content: question }
    const assistantMsg: Message = { role: 'assistant', content: '', loading: true }
    setMessages(prev => [...prev, userMsg, assistantMsg])

    try {
      const stream = streamAsk(slug, question, activeConvId ?? undefined)
      let fullContent = ''

      for await (const event of stream) {
        switch (event.type) {
          case 'status':
            setMessages(prev => {
              const updated = [...prev]
              const last = updated[updated.length - 1]
              if (last?.role === 'assistant') {
                updated[updated.length - 1] = { ...last, status: event.data.message }
              }
              return updated
            })
            break

          case 'token':
            fullContent += event.data.text || ''
            setMessages(prev => {
              const updated = [...prev]
              const last = updated[updated.length - 1]
              if (last?.role === 'assistant') {
                updated[updated.length - 1] = {
                  ...last,
                  content: fullContent,
                  loading: false,
                  status: undefined,
                }
              }
              return updated
            })
            break

          case 'done': {
            const newConvId = event.data.conversation_id
            if (newConvId && !activeConvId) {
              setActiveConvId(newConvId)
              // Refresh sidebar
              listConversations(slug).then(setConversations).catch(() => {})
            } else if (newConvId && activeConvId) {
              // Update updated_at in sidebar
              listConversations(slug).then(setConversations).catch(() => {})
            }
            setMessages(prev => {
              const updated = [...prev]
              const last = updated[updated.length - 1]
              if (last?.role === 'assistant') {
                updated[updated.length - 1] = {
                  ...last,
                  content: fullContent,
                  sources: event.data.sources,
                  loading: false,
                  status: undefined,
                }
              }
              return updated
            })
            break
          }

          case 'error':
            setMessages(prev => {
              const updated = [...prev]
              const last = updated[updated.length - 1]
              if (last?.role === 'assistant') {
                updated[updated.length - 1] = {
                  ...last,
                  content: `**Error:** ${event.data.message || 'Something went wrong.'}`,
                  loading: false,
                  status: undefined,
                }
              }
              return updated
            })
            break
        }
      }
    } catch (err) {
      setMessages(prev => {
        const updated = [...prev]
        const last = updated[updated.length - 1]
        if (last?.role === 'assistant') {
          updated[updated.length - 1] = {
            ...last,
            content: `**Error:** ${err instanceof Error ? err.message : 'Connection failed.'}`,
            loading: false,
            status: undefined,
          }
        }
        return updated
      })
    } finally {
      setIsStreaming(false)
      inputRef.current?.focus()
    }
  }, [input, isStreaming, slug, activeConvId])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const sidebarContent = (
    <>
      <div style={styles.sidebarHeader}>
        {/* Toggle button lives here when sidebar is open */}
        <button
          style={styles.sidebarToggleInner}
          onClick={() => setSidebarOpen(false)}
          title="Close sidebar"
        >
          <SidebarIcon />
        </button>
        <button
          style={styles.newChatIconBtn}
          onClick={() => { startNewChat(); if (isMobile) setSidebarOpen(false) }}
          title="New chat"
        >
          <ComposeIcon />
        </button>
        {isMobile && (
          <button style={styles.sidebarCloseBtn} onClick={() => setSidebarOpen(false)} title="Close">
            ✕
          </button>
        )}
      </div>
      <div style={styles.convList}>
        {conversations.length === 0 && (
          <div style={styles.convEmpty}>No conversations yet</div>
        )}
        {conversations.map(conv => (
          <div
            key={conv.id}
            style={{
              ...styles.convItem,
              ...(conv.id === activeConvId ? styles.convItemActive : {}),
            }}
            onClick={() => { switchConversation(conv.id); if (isMobile) setSidebarOpen(false) }}
          >
            <span style={styles.convTitle}>
              {conv.title || 'Untitled'}
            </span>
            <button
              style={styles.convDelete}
              onClick={e => handleDeleteConversation(conv.id, e)}
              title="Delete"
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </>
  )

  return (
    <div style={{ ...styles.root, height: `calc(100dvh - ${TOP_NAV_HEIGHT}px)` }}>
      {/* Mobile backdrop */}
      {isMobile && sidebarOpen && (
        <div style={styles.backdrop} onClick={() => setSidebarOpen(false)} />
      )}

      {/* Sidebar — inline on desktop, overlay drawer on mobile */}
      {isMobile ? (
        sidebarOpen && (
          <div style={styles.sidebarOverlay}>
            {sidebarContent}
          </div>
        )
      ) : (
        sidebarOpen && (
          <div style={styles.sidebar}>
            {sidebarContent}
          </div>
        )
      )}

      {/* Main chat area */}
      <div style={styles.main}>
        {/* Top bar */}
        <div style={styles.topBar}>
          {/* Show sidebar toggle here only when the sidebar is hidden */}
          {(!sidebarOpen || isMobile) && (
            <button
              style={styles.sidebarToggle}
              onClick={() => setSidebarOpen(p => !p)}
              title="Show history"
            >
              <SidebarIcon />
            </button>
          )}
          <h1 style={styles.title}>AI Research Assistant</h1>
        </div>

        {/* Messages */}
        <div style={styles.messagesArea}>
          {messages.length === 0 && (
            <div style={styles.emptyState}>
              <div style={styles.emptyIcon}>
                <svg width="48" height="48" viewBox="0 0 16 16" fill="currentColor">
                  <path d="M16 8c0 3.866-3.582 7-8 7a9 9 0 0 1-2.347-.306c-.584.297-1.925.864-4.181 1.234-.2.032-.352-.176-.273-.362.354-.836.674-1.95.77-2.966C.744 11.37 0 9.76 0 8c0-3.866 3.582-7 8-7s8 3.134 8 7M5 8a1 1 0 1 0-2 0 1 1 0 0 0 2 0m4 0a1 1 0 1 0-2 0 1 1 0 0 0 2 0m3 0a1 1 0 1 0-2 0 1 1 0 0 0 2 0"/>
                </svg>
              </div>
              <div style={styles.emptyTitle}>Ask a question</div>
              <div style={styles.emptyHint}>Try questions like:</div>
              <div style={styles.suggestions}>
                {suggestedQuestions.map((q, i) => (
                  <button
                    key={i}
                    style={styles.suggestionBtn}
                    onClick={() => { setInput(q); inputRef.current?.focus() }}
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg, i) => (
            <div
              key={i}
              style={{
                ...styles.messageRow,
                justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
              }}
            >
              <div
                style={{
                  ...styles.messageBubble,
                  ...(msg.role === 'user' ? styles.userBubble : styles.assistantBubble),
                }}
              >
                {msg.loading && msg.status && (
                  <div style={styles.statusBar}>
                    <span style={styles.spinner} />
                    {msg.status}
                  </div>
                )}
                {msg.loading && !msg.status && !msg.content && (
                  <div style={styles.statusBar}>
                    <span style={styles.spinner} />
                    Thinking...
                  </div>
                )}
                {msg.content && (
                  <div
                    style={styles.messageContent}
                    className="markdown-content"
                    onClick={(e) => {
                      const target = e.target as HTMLElement
                      if (target.classList.contains('inline-cite')) {
                        const docId = target.dataset.doc
                        const page = parseInt(target.dataset.page ?? '1', 10)
                        if (docId) {
                          const src = msg.sources?.find(s => s.doc_id === docId)
                          setViewerDoc(prev => {
                            const next = prev?.docId === docId && prev?.page === page
                              ? null
                              : { docId, page, title: src?.title ?? docId }
                            // collapse the conv sidebar when opening viewer so chat stays readable
                            if (next && !isMobile) setSidebarOpen(false)
                            return next
                          })
                        }
                      }
                    }}
                    dangerouslySetInnerHTML={{
                      __html: marked.parse(
                        msg.role === 'assistant' && msg.sources?.length
                          ? processCitations(msg.content, msg.sources)
                          : msg.content
                      ) as string,
                    }}
                  />
                )}
              </div>
            </div>
          ))}

          <div ref={messagesEndRef} />
        </div>

        {/* Input bar */}
        <div style={styles.inputBar}>
          <div style={styles.inputWrapper}>
            <textarea
              ref={inputRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask a question about this case..."
              rows={1}
              style={styles.textarea}
              disabled={isStreaming}
            />
            <button
              onClick={handleSubmit}
              disabled={!input.trim() || isStreaming}
              style={{
                ...styles.sendBtn,
                opacity: !input.trim() || isStreaming ? 0.4 : 1,
              }}
            >
              {isStreaming ? (
              <span style={styles.spinner} />
            ) : (
              <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><path d="M15.964.686a.5.5 0 0 0-.65-.65L.767 5.855H.766l-.452.18a.5.5 0 0 0-.082.887l.41.26.001.002 4.995 3.178 3.178 4.995.002.002.26.41a.5.5 0 0 0 .886-.083l6-15Zm-1.833 1.89L6.637 10.07l-.215-.338a.5.5 0 0 0-.154-.154l-.338-.215 7.494-7.494 1.178-.471-.47 1.178Z"/></svg>
            )}
            </button>
          </div>
        </div>
      </div>

      {/* Document viewer panel — slides in when a source chip is clicked */}
      {viewerDoc && (
        <div style={styles.viewerPanel}>
          <div style={styles.viewerHeader}>
            <span style={styles.viewerTitle}>{viewerDoc.title}</span>
            <button style={styles.viewerClose} onClick={() => setViewerDoc(null)}>✕</button>
          </div>
          <div style={styles.viewerBody}>
            <DocumentReader
              slug={slug}
              documentId={viewerDoc.docId}
              highlightTerms={[]}
              initialPage={viewerDoc.page}
            />
          </div>

        </div>
      )}
    </div>
  )
}

/**
 * Replace [DOC-ID, page N] or [DOC-ID1, page N; DOC-ID2, page N] patterns in
 * the LLM response with clickable inline citation chips.
 *
 * The pattern produced by the model is:  [eml-abc123, page 1]
 * Multi-citation:  [eml-abc, page 1; eml-def, page 2]
 * We inject <span class="inline-cite"> elements; clicks are caught via event
 * delegation on the parent div.
 */
function processCitations(text: string, sources: Source[]): string {
  const srcMap = new Map(sources.map(s => [s.doc_id, s]))

  function makeChip(docId: string, page: number): string {
    const src = srcMap.get(docId)
    const title = src?.title ?? docId
    const label = title.length > 22 ? title.slice(0, 22) + '…' : title
    return `<span class="inline-cite" data-doc="${docId}" data-page="${page}" title="${title} — page ${page}">${label} p.${page}</span>`
  }

  function processPart(part: string): string {
    const trimmed = part.trim()
    // Standard format: [doc-id, page N]
    const pageMatch = trimmed.match(/^([a-z0-9_\-]+),\s*page\s*(\d+)/i)
    if (pageMatch) return makeChip(pageMatch[1], parseInt(pageMatch[2], 10))

    // Legacy email format: [doc-id, From: ... → ..., date] — extract just the doc-id
    const docIdMatch = trimmed.match(/^([a-z0-9_\-]+),\s*/i)
    if (docIdMatch && srcMap.has(docIdMatch[1])) {
      const src = srcMap.get(docIdMatch[1])!
      return makeChip(docIdMatch[1], src.page)
    }

    return `[${part}]`
  }

  // Match brackets containing what looks like one or more doc-id citations
  // Handles both [doc-id, page N] and [doc-id, anything; doc-id, anything] patterns
  return text.replace(
    /\[([a-z0-9_\-]+,\s*(?:page\s*\d+|[^\]]+?)(?:\s*;\s*[a-z0-9_\-]+,\s*(?:page\s*\d+|[^\]]+?))*)\]/gi,
    (_match, inner) => {
      const parts = inner.split(/\s*;\s*/)
      const chips = parts.map(processPart)
      // Only replace if at least one chip was actually created
      return chips.some(c => c.includes('inline-cite')) ? chips.join('') : _match
    },
  )
}

// Sidebar panel icon (two-column layout with left panel)
function SidebarIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
      <line x1="9" y1="3" x2="9" y2="21" />
    </svg>
  )
}

// Compose / new chat icon (pencil on paper)
function ComposeIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 20h9" />
      <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
    </svg>
  )
}


// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const styles: Record<string, React.CSSProperties> = {
  root: {
    display: 'flex',
    // height is set dynamically inline (100dvh on mobile, calc(100vh-64px) on desktop)
    height: 'calc(100vh - 64px)',
    overflow: 'hidden',
    position: 'relative',
  },

  // Mobile overlay backdrop
  backdrop: {
    position: 'fixed',
    inset: 0,
    background: 'rgba(0,0,0,0.4)',
    zIndex: 99,
  },

  // Mobile slide-over drawer
  sidebarOverlay: {
    position: 'fixed',
    top: 0,
    left: 0,
    bottom: 0,
    width: 280,
    maxWidth: '85vw',
    background: 'var(--surface)',
    borderRight: '1px solid var(--border)',
    display: 'flex',
    flexDirection: 'column' as const,
    overflow: 'hidden',
    zIndex: 100,
  },

  sidebarCloseBtn: {
    background: 'none',
    border: 'none',
    fontSize: 18,
    cursor: 'pointer',
    color: 'var(--text-muted)',
    padding: '0 4px',
    lineHeight: 1,
    flexShrink: 0,
  },

  // Desktop inline sidebar
  sidebar: {
    width: 240,
    minWidth: 240,
    borderRight: '1px solid var(--border)',
    display: 'flex',
    flexDirection: 'column',
    background: 'var(--surface)',
    overflow: 'hidden',
  },
  sidebarHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 4,
    padding: '10px 10px 10px 12px',
    borderBottom: '1px solid var(--border)',
  },
  // Toggle button that lives inside the sidebar header when open
  sidebarToggleInner: {
    background: 'none',
    border: 'none',
    borderRadius: 6,
    padding: '5px 6px',
    cursor: 'pointer',
    color: 'var(--text-muted)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  },
  // New chat icon button (compose icon)
  newChatIconBtn: {
    marginLeft: 'auto',
    background: 'none',
    border: 'none',
    borderRadius: 6,
    padding: '5px 6px',
    cursor: 'pointer',
    color: 'var(--text-muted)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  },
  convList: {
    flex: 1,
    overflowY: 'auto',
    padding: '4px 0',
  },
  convEmpty: {
    padding: '16px 12px',
    fontSize: 13,
    color: 'var(--text-muted)',
    textAlign: 'center',
  },
  convItem: {
    display: 'flex',
    alignItems: 'center',
    gap: 4,
    padding: '8px 12px',
    cursor: 'pointer',
    borderRadius: 0,
    transition: 'background 0.1s',
    background: 'transparent',
  },
  convItemActive: {
    background: 'var(--accent-light, rgba(59,130,246,0.12))',
  },
  convTitle: {
    flex: 1,
    fontSize: 13,
    color: 'var(--text)',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    display: 'block',
  },
  convDelete: {
    flexShrink: 0,
    background: 'none',
    border: 'none',
    color: 'var(--text-muted)',
    fontSize: 16,
    cursor: 'pointer',
    padding: '0 2px',
    lineHeight: 1,
    opacity: 0.6,
  },

  // Main
  main: {
    flex: 1,
    minWidth: 0,
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
  },
  topBar: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    padding: '12px 20px',
    borderBottom: '1px solid var(--border)',
    minHeight: 52,
  },
  // Toggle button shown in the topBar only when sidebar is closed
  sidebarToggle: {
    background: 'none',
    border: 'none',
    borderRadius: 6,
    padding: '5px 6px',
    cursor: 'pointer',
    color: 'var(--text-muted)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  },
  title: {
    fontSize: 20,
    fontWeight: 700,
    color: 'var(--text)',
    margin: 0,
  },

  // Messages
  messagesArea: {
    flex: 1,
    minWidth: 0,
    overflowY: 'auto',
    overflowX: 'hidden',
    padding: '20px 24px',
    display: 'flex',
    flexDirection: 'column',
    gap: 16,
  },
  emptyState: {
    textAlign: 'center',
    padding: '60px 20px',
    color: 'var(--text-muted)',
  },
  emptyIcon: {
    marginBottom: 16,
    opacity: 0.35,
    display: 'flex',
    justifyContent: 'center',
  },
  emptyTitle: {
    fontSize: 20,
    fontWeight: 600,
    color: 'var(--text)',
    marginBottom: 8,
  },
  emptyHint: {
    fontSize: 14,
    marginBottom: 16,
  },
  suggestions: {
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
    alignItems: 'center',
  },
  suggestionBtn: {
    padding: '10px 20px',
    fontSize: 14,
    fontFamily: 'inherit',
    border: '1px solid var(--border)',
    borderRadius: 8,
    background: 'var(--surface)',
    color: 'var(--text)',
    cursor: 'pointer',
    maxWidth: 400,
    textAlign: 'left',
  },
  messageRow: {
    display: 'flex',
    width: '100%',
  },
  messageBubble: {
    maxWidth: '80%',
    padding: '12px 16px',
    borderRadius: 12,
    fontSize: 15,
    lineHeight: 1.6,
  },
  userBubble: {
    background: 'var(--accent)',
    color: '#fff',
    borderBottomRightRadius: 4,
  },
  assistantBubble: {
    background: 'var(--surface)',
    color: 'var(--text)',
    border: '1px solid var(--border)',
    borderBottomLeftRadius: 4,
  },
  statusBar: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    fontSize: 13,
    color: 'var(--text-muted)',
    padding: '4px 0',
  },
  spinner: {
    display: 'inline-block',
    width: 14,
    height: 14,
    border: '2px solid var(--border)',
    borderTopColor: 'var(--accent)',
    borderRadius: '50%',
    animation: 'spin 0.8s linear infinite',
  },
  messageContent: {
    wordBreak: 'break-word',
  },
  sourcesSection: {
    marginTop: 12,
    paddingTop: 10,
    borderTop: '1px solid var(--border)',
  },
  sourcesLabel: {
    fontSize: 12,
    fontWeight: 600,
    color: 'var(--text-muted)',
    marginBottom: 6,
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
  },
  sourceChips: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 6,
  },
  sourceChip: {
    display: 'inline-block',
    padding: '3px 10px',
    fontSize: 12,
    fontWeight: 500,
    background: 'var(--accent-light, rgba(59, 130, 246, 0.1))',
    color: 'var(--accent)',
    borderRadius: 12,
    whiteSpace: 'nowrap',
    transition: 'background 0.15s, transform 0.1s',
  },
  sourceChipActive: {
    background: 'var(--accent)',
    color: '#fff',
  },

  // Document viewer panel — flex sibling of main, pushes chat area left when open
  viewerPanel: {
    width: 460,
    minWidth: 460,
    borderLeft: '1px solid var(--border)',
    background: 'var(--surface)',
    display: 'flex',
    flexDirection: 'column' as const,
    overflow: 'hidden',
  },
  viewerHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '14px 20px',
    borderBottom: '1px solid var(--border)',
    background: 'var(--bg)',
    flexShrink: 0,
  },
  viewerTitle: {
    fontWeight: 600,
    fontSize: 14,
    color: 'var(--text)',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
    flex: 1,
    marginRight: 12,
  },
  viewerClose: {
    background: 'none',
    border: 'none',
    fontSize: 16,
    cursor: 'pointer',
    color: 'var(--text-muted)',
    padding: '2px 6px',
    borderRadius: 4,
    flexShrink: 0,
  },
  viewerBody: {
    flex: 1,
    overflow: 'hidden',
    display: 'flex',
    flexDirection: 'column' as const,
  },

  // Input
  inputBar: {
    padding: '12px 24px 16px',
    borderTop: '1px solid var(--border)',
  },
  inputWrapper: {
    display: 'flex',
    gap: 10,
    alignItems: 'flex-end',
  },
  textarea: {
    flex: 1,
    padding: '12px 16px',
    fontSize: 15,
    fontFamily: 'inherit',
    border: '2px solid var(--border)',
    borderRadius: 8,
    background: 'var(--surface)',
    color: 'var(--text)',
    resize: 'none',
    outline: 'none',
    minHeight: 44,
    maxHeight: 120,
    lineHeight: 1.4,
  },
  sendBtn: {
    width: 44,
    height: 44,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
    background: 'var(--accent)',
    color: '#fff',
    border: 'none',
    borderRadius: 8,
    cursor: 'pointer',
  },
}
