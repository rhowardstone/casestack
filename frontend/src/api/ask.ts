/**
 * SSE client for the AI Research Assistant endpoint.
 *
 * Streams events from POST /api/cases/{slug}/ask as an async generator.
 */

export interface AskEvent {
  type: 'status' | 'token' | 'done' | 'error'
  data: {
    message?: string
    text?: string
    sources?: Array<{ doc_id: string; title: string; page: number }>
    conversation_id?: string
  }
}

/**
 * Stream ask events from the backend. Yields AskEvent objects
 * as they arrive over the SSE connection.
 */
export async function* streamAsk(
  slug: string,
  question: string,
  conversationId?: string,
): AsyncGenerator<AskEvent> {
  const res = await fetch(`/api/cases/${slug}/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, conversation_id: conversationId }),
  })

  if (!res.ok) {
    yield { type: 'error', data: { message: res.statusText } }
    return
  }

  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''

    let eventType = ''
    for (const line of lines) {
      if (line.startsWith('event: ')) {
        eventType = line.slice(7)
      } else if (line.startsWith('data: ') && eventType) {
        try {
          yield {
            type: eventType as AskEvent['type'],
            data: JSON.parse(line.slice(6)),
          }
        } catch {
          // Skip malformed JSON
        }
        eventType = ''
      }
    }
  }
}
