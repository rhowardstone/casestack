import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
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
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <div>
          <h1 style={{ margin: 0 }}>CaseStack</h1>
          <p style={{ margin: '4px 0 0', color: '#6b7280' }}>Document Intelligence Platform</p>
        </div>
        <Link
          to="/new"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            padding: '10px 20px',
            background: '#2563eb',
            color: '#fff',
            borderRadius: 8,
            fontSize: 14,
            fontWeight: 600,
            textDecoration: 'none',
            transition: 'background 0.15s ease',
          }}
        >
          + New Case
        </Link>
      </div>
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
