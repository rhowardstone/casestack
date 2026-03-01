import { useState, useRef, useEffect, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { marked } from 'marked'
import { streamAsk } from '../api/ask'

// Configure marked for safe rendering
marked.setOptions({
  breaks: true,
  gfm: true,
})

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

export default function AskAssistant() {
  const { slug = '' } = useParams<{ slug: string }>()
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Auto-focus input on mount
  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const handleSubmit = useCallback(async () => {
    const question = input.trim()
    if (!question || isStreaming) return

    setInput('')
    setIsStreaming(true)

    // Add user message
    const userMsg: Message = { role: 'user', content: question }
    const assistantMsg: Message = { role: 'assistant', content: '', loading: true }
    setMessages(prev => [...prev, userMsg, assistantMsg])

    try {
      const stream = streamAsk(slug, question)
      let fullContent = ''

      for await (const event of stream) {
        switch (event.type) {
          case 'status':
            setMessages(prev => {
              const updated = [...prev]
              const last = updated[updated.length - 1]
              if (last.role === 'assistant') {
                updated[updated.length - 1] = {
                  ...last,
                  status: event.data.message,
                }
              }
              return updated
            })
            break

          case 'token':
            fullContent += event.data.text || ''
            setMessages(prev => {
              const updated = [...prev]
              const last = updated[updated.length - 1]
              if (last.role === 'assistant') {
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

          case 'done':
            setMessages(prev => {
              const updated = [...prev]
              const last = updated[updated.length - 1]
              if (last.role === 'assistant') {
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

          case 'error':
            setMessages(prev => {
              const updated = [...prev]
              const last = updated[updated.length - 1]
              if (last.role === 'assistant') {
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
        if (last.role === 'assistant') {
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
  }, [input, isStreaming, slug])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  return (
    <div style={styles.container}>
      {/* Header */}
      <div style={styles.header}>
        <h1 style={styles.title}>AI Research Assistant</h1>
        <p style={styles.subtitle}>
          Ask questions about the documents in this case. Answers are generated
          from document content with citations.
        </p>
      </div>

      {/* Messages area */}
      <div style={styles.messagesArea}>
        {messages.length === 0 && (
          <div style={styles.emptyState}>
            <div style={styles.emptyIcon}>?</div>
            <div style={styles.emptyTitle}>Ask a question</div>
            <div style={styles.emptyHint}>
              Try questions like:
            </div>
            <div style={styles.suggestions}>
              {[
                'What are the key findings in this case?',
                'Who are the main persons mentioned?',
                'Summarize the financial transactions',
              ].map((q, i) => (
                <button
                  key={i}
                  style={styles.suggestionBtn}
                  onClick={() => {
                    setInput(q)
                    inputRef.current?.focus()
                  }}
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
                  dangerouslySetInnerHTML={{
                    __html: marked.parse(msg.content) as string,
                  }}
                />
              )}
              {msg.sources && msg.sources.length > 0 && (
                <div style={styles.sourcesSection}>
                  <div style={styles.sourcesLabel}>Sources:</div>
                  <div style={styles.sourceChips}>
                    {deduplicateSources(msg.sources).map((src, j) => (
                      <span key={j} style={styles.sourceChip}>
                        {src.title} [p.{src.page}]
                      </span>
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
            {isStreaming ? '...' : 'Send'}
          </button>
        </div>
      </div>
    </div>
  )
}

/** Deduplicate sources by doc_id + page */
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
  container: {
    display: 'flex',
    flexDirection: 'column',
    height: 'calc(100vh - 64px)',
    maxWidth: 860,
    margin: '0 auto',
    padding: '0 24px',
  },
  header: {
    padding: '24px 0 16px',
    borderBottom: '1px solid var(--border)',
  },
  title: {
    fontSize: 24,
    fontWeight: 700,
    color: 'var(--text)',
    margin: 0,
  },
  subtitle: {
    fontSize: 14,
    color: 'var(--text-muted)',
    marginTop: 6,
  },
  messagesArea: {
    flex: 1,
    overflowY: 'auto',
    padding: '20px 0',
    display: 'flex',
    flexDirection: 'column',
    gap: 16,
  },
  emptyState: {
    textAlign: 'center' as const,
    padding: '60px 20px',
    color: 'var(--text-muted)',
  },
  emptyIcon: {
    fontSize: 48,
    marginBottom: 16,
    opacity: 0.4,
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
    flexDirection: 'column' as const,
    gap: 8,
    alignItems: 'center',
  },
  suggestionBtn: {
    padding: '10px 20px',
    fontSize: 14,
    fontFamily: 'inherit',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-md, 8px)',
    background: 'var(--surface)',
    color: 'var(--text)',
    cursor: 'pointer',
    transition: 'all 0.15s ease',
    maxWidth: 400,
    textAlign: 'left' as const,
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
    wordBreak: 'break-word' as const,
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
    textTransform: 'uppercase' as const,
    letterSpacing: '0.5px',
  },
  sourceChips: {
    display: 'flex',
    flexWrap: 'wrap' as const,
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
    whiteSpace: 'nowrap' as const,
  },
  inputBar: {
    padding: '16px 0',
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
    borderRadius: 'var(--radius-md, 8px)',
    background: 'var(--surface)',
    color: 'var(--text)',
    resize: 'none' as const,
    outline: 'none',
    minHeight: 44,
    maxHeight: 120,
    lineHeight: 1.4,
  },
  sendBtn: {
    padding: '10px 24px',
    fontSize: 14,
    fontWeight: 600,
    fontFamily: 'inherit',
    background: 'var(--accent)',
    color: '#fff',
    border: 'none',
    borderRadius: 'var(--radius-md, 8px)',
    cursor: 'pointer',
    transition: 'opacity 0.15s ease',
    whiteSpace: 'nowrap' as const,
  },
}
