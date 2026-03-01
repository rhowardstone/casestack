import { useState, useEffect, useRef } from 'react'
import { fetchJSON } from '../api/client'

export interface SearchResult {
  type: 'page' | 'transcript' | 'image'
  document_id: string
  title?: string
  page_number?: number
  file_path?: string
  snippet: string
  rank: number
}

interface SearchResponse {
  total: number
  results: SearchResult[]
}

export function useSearch(slug: string, query: string, type: string = 'all') {
  const [results, setResults] = useState<SearchResult[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const timerRef = useRef<number | undefined>(undefined)

  useEffect(() => {
    if (!query.trim()) {
      setResults([])
      setTotal(0)
      setLoading(false)
      return
    }

    setLoading(true)
    clearTimeout(timerRef.current)
    timerRef.current = window.setTimeout(async () => {
      try {
        const params = new URLSearchParams({ q: query, type })
        const data = await fetchJSON<SearchResponse>(`/cases/${slug}/search?${params}`)
        setResults(data.results)
        setTotal(data.total)
      } catch {
        setResults([])
        setTotal(0)
      } finally {
        setLoading(false)
      }
    }, 300)

    return () => clearTimeout(timerRef.current)
  }, [slug, query, type])

  return { results, total, loading }
}
