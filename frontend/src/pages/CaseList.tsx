import { useEffect, useState } from 'react'
import { fetchJSON } from '../api/client'

interface Case {
  slug: string
  name: string
  description: string
  document_count: number
}

export default function CaseList() {
  const [cases, setCases] = useState<Case[]>([])

  useEffect(() => {
    fetchJSON<Case[]>('/cases').then(setCases)
  }, [])

  return (
    <div style={{ maxWidth: 800, margin: '0 auto', padding: 32 }}>
      <h1>CaseStack</h1>
      <p>Document Intelligence Platform</p>
      {cases.length === 0 ? (
        <div style={{ marginTop: 32, padding: 24, background: '#fff', borderRadius: 8 }}>
          <h2>No cases yet</h2>
          <p>Create your first case to get started.</p>
        </div>
      ) : (
        cases.map(c => (
          <div key={c.slug} style={{ padding: 16, margin: '8px 0', background: '#fff', borderRadius: 8 }}>
            <h3>{c.name}</h3>
            <p>{c.document_count} documents</p>
          </div>
        ))
      )}
    </div>
  )
}
