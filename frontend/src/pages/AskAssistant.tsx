import { useState, useRef, useEffect, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { marked } from 'marked'
import { streamAsk } from '../api/ask'
import {
  listConversations,
  deleteConversation,
  getConversation,
  type Conversation,
  type ConversationMessage,
} from '../api/conversations'
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

const SUGGESTED_QUESTIONS = [
  'What are the key findings in this case?',
  'Who are the main persons mentioned?',
  'Summarize the financial transactions',
]

export default function AskAssistant() {
  const { slug = '' } = useParams<{ slug: string }>()

  // Conversations sidebar state
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeConvId, setActiveConvId] = useState<string | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(true)

  // Chat state
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)

  // Document viewer state (clicked source chip)
  const [viewerDoc, setViewerDoc] = useState<{ docId: string; page: number; title: string } | null>(null)

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  // Load conversation list on mount
  useEffect(() => {
    listConversations(slug)
      .then(setConversations)
      .catch(() => {}) // non-fatal
  }, [slug])

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

  return (
    <div style={styles.root}>
      {/* Sidebar — full (240px) or collapsed icon-strip (48px) */}
      <div style={sidebarOpen ? styles.sidebar : styles.sidebarCollapsed}>
        {sidebarOpen ? (
          <>
            <div style={styles.sidebarHeader}>
              <button style={styles.newChatBtn} onClick={startNewChat}>
                + New chat
              </button>
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
                  onClick={() => switchConversation(conv.id)}
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
        ) : (
          <div style={styles.sidebarIconStrip}>
            <button
              style={styles.iconStripNewChat}
              onClick={startNewChat}
              title="New chat"
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                <path d="M8 2a.5.5 0 0 1 .5.5v5h5a.5.5 0 0 1 0 1h-5v5a.5.5 0 0 1-1 0v-5h-5a.5.5 0 0 1 0-1h5v-5A.5.5 0 0 1 8 2"/>
              </svg>
            </button>
          </div>
        )}
      </div>

      {/* Main chat area */}
      <div style={styles.main}>
        {/* Top bar */}
        <div style={styles.topBar}>
          <button
            style={styles.sidebarToggle}
            onClick={() => setSidebarOpen(p => !p)}
            title={sidebarOpen ? 'Hide history' : 'Show history'}
          >
            {sidebarOpen ? (
              <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor"><path d="M11.354 1.646a.5.5 0 0 1 0 .708L5.707 8l5.647 5.646a.5.5 0 0 1-.708.708l-6-6a.5.5 0 0 1 0-.708l6-6a.5.5 0 0 1 .708 0z"/></svg>
            ) : (
              <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor"><path d="M4.646 1.646a.5.5 0 0 1 .708 0l6 6a.5.5 0 0 1 0 .708l-6 6a.5.5 0 0 1-.708-.708L10.293 8 4.646 2.354a.5.5 0 0 1 0-.708z"/></svg>
            )}
          </button>
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
                {SUGGESTED_QUESTIONS.map((q, i) => (
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
                    dangerouslySetInnerHTML={{ __html: marked.parse(msg.content) as string }}
                  />
                )}
                {msg.sources && msg.sources.length > 0 && (
                  <div style={styles.sourcesSection}>
                    <div style={styles.sourcesLabel}>Sources:</div>
                    <div style={styles.sourceChips}>
                      {deduplicateSources(msg.sources).map((src, j) => (
                        <button
                          key={j}
                          style={{
                            ...styles.sourceChip,
                            cursor: 'pointer',
                            border: 'none',
                            ...(viewerDoc?.docId === src.doc_id ? styles.sourceChipActive : {}),
                          }}
                          onClick={() =>
                            setViewerDoc(prev =>
                              prev?.docId === src.doc_id && prev?.page === src.page
                                ? null
                                : { docId: src.doc_id, page: src.page, title: src.title }
                            )
                          }
                          title="Open document"
                        >
                          {src.title} [p.{src.page}]
                        </button>
                      ))}
                    </div>
                  </div>
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

function deduplicateSources(sources: Source[]): Source[] {
  const seen = new Set<string>()
  return sources.filter(s => {
    const key = `${s.doc_id}:${s.page}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const styles: Record<string, React.CSSProperties> = {
  root: {
    display: 'flex',
    height: 'calc(100vh - 64px)',
    overflow: 'hidden',
  },

  // Sidebar
  sidebar: {
    width: 240,
    minWidth: 240,
    borderRight: '1px solid var(--border)',
    display: 'flex',
    flexDirection: 'column',
    background: 'var(--surface)',
    overflow: 'hidden',
  },
  sidebarCollapsed: {
    width: 48,
    minWidth: 48,
    borderRight: '1px solid var(--border)',
    display: 'flex',
    flexDirection: 'column' as const,
    background: 'var(--surface)',
    overflow: 'hidden',
  },
  sidebarIconStrip: {
    display: 'flex',
    flexDirection: 'column' as const,
    alignItems: 'center',
    padding: '12px 0',
    gap: 8,
  },
  iconStripNewChat: {
    background: 'none',
    border: '1px solid var(--border)',
    borderRadius: 6,
    padding: '6px',
    cursor: 'pointer',
    color: 'var(--text-muted)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  },
  sidebarHeader: {
    padding: '12px 12px 8px',
    borderBottom: '1px solid var(--border)',
  },
  newChatBtn: {
    width: '100%',
    padding: '8px 12px',
    fontSize: 13,
    fontWeight: 600,
    fontFamily: 'inherit',
    background: 'var(--accent)',
    color: '#fff',
    border: 'none',
    borderRadius: 6,
    cursor: 'pointer',
    textAlign: 'left',
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
    gap: 12,
    padding: '16px 24px 12px',
    borderBottom: '1px solid var(--border)',
  },
  sidebarToggle: {
    background: 'none',
    border: '1px solid var(--border)',
    borderRadius: 6,
    padding: '4px 8px',
    cursor: 'pointer',
    fontSize: 12,
    color: 'var(--text-muted)',
    fontFamily: 'inherit',
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
    overflow: 'auto',
    padding: 20,
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
