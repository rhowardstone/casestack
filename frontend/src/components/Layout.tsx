import { useEffect, useState } from 'react'
import { Outlet, useParams, useLocation } from 'react-router-dom'
import { fetchJSON } from '../api/client'
import Sidebar from './Sidebar'

interface CaseInfo {
  slug: string
  name: string
}

export default function Layout() {
  const { slug } = useParams<{ slug: string }>()
  const location = useLocation()
  const [caseName, setCaseName] = useState('')

  // Ask page is full-height and manages its own scroll — no padding or overflow
  const isAskPage = location.pathname.endsWith('/ask')

  useEffect(() => {
    if (!slug) return
    fetchJSON<CaseInfo>(`/cases/${slug}`)
      .then(data => setCaseName(data.name))
      .catch(() => setCaseName('Unknown Case'))
  }, [slug])

  return (
    <div style={styles.wrapper}>
      <Sidebar slug={slug || ''} caseName={caseName} />
      <main
        style={{
          ...styles.content,
          padding: isAskPage ? 0 : 32,
          overflow: isAskPage ? 'hidden' : 'auto',
        }}
      >
        <Outlet />
      </main>
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  wrapper: {
    display: 'flex',
    flexDirection: 'column',
    height: '100vh',
    overflow: 'hidden',
    background: 'var(--bg)',
  },
  content: {
    flex: 1,
    minHeight: 0,
  },
}
