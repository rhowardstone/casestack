import { fetchJSON } from './client'

export interface Conversation {
  id: string
  case_slug: string
  created_at: string
  updated_at: string
  title: string | null
}

export interface ConversationMessage {
  id: number
  conversation_id: string
  role: 'user' | 'assistant'
  content: string
  sources_json: string | null
  created_at: string
}

export interface ConversationDetail {
  conversation: Conversation
  messages: ConversationMessage[]
}

export function listConversations(slug: string): Promise<Conversation[]> {
  return fetchJSON(`/cases/${slug}/conversations`)
}

export function createConversation(slug: string, title?: string): Promise<Conversation> {
  return fetchJSON(`/cases/${slug}/conversations`, {
    method: 'POST',
    body: JSON.stringify({ title: title ?? null }),
  })
}

export function getConversation(slug: string, convId: string): Promise<ConversationDetail> {
  return fetchJSON(`/cases/${slug}/conversations/${convId}`)
}

export function renameConversation(slug: string, convId: string, title: string): Promise<Conversation> {
  return fetchJSON(`/cases/${slug}/conversations/${convId}`, {
    method: 'PATCH',
    body: JSON.stringify({ title }),
  })
}

export async function deleteConversation(slug: string, convId: string): Promise<void> {
  await fetch(`/api/cases/${slug}/conversations/${convId}`, { method: 'DELETE' })
}
