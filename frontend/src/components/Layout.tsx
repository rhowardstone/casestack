import { useEffect, useState } from 'react'
import { Outlet, useParams } from 'react-router-dom'
import { fetchJSON } from '../api/client'
import Sidebar from './Sidebar'

interface CaseInfo {
  slug: string
  name: string
}

export default function Layout() {
  const { slug } = useParams<{ slug: string }>()
  const [caseName, setCaseName] = useState('')

  useEffect(() => {
    if (!slug) return
    fetchJSON<CaseInfo>(`/cases/${slug}`)
      .then(data => setCaseName(data.name))
      .catch(() => setCaseName('Unknown Case'))
  }, [slug])

  return (
    <div style={styles.wrapper}>
      <Sidebar slug={slug || ''} caseName={caseName} />
      <main style={styles.content}>
        <Outlet />
      </main>
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  wrapper: {
    display: 'flex',
    minHeight: '100vh',
    background: 'var(--bg)',
  },
  content: {
    flex: 1,
    padding: 32,
    overflowY: 'auto',
  },
}
