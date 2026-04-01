import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { fetchJSON } from '../api/client'

interface DatasetSummary { slug: string; name: string; document_count: number }
interface YearBucket { year: number; count: number }
interface EntityRow { type: string; name: string; doc_count: number }
interface ProjectStats {
  date_min: string | null
  date_max: string | null
  docs_by_year: YearBucket[]
  top_entities: EntityRow[]
  datasets: DatasetSummary[]
}
interface Project {
  slug: string; name: string; description: string
  datasets: DatasetSummary[]
  total_documents: number
}

const ENTITY_COLORS: Record<string, string> = {
  PERSON: '#3b5bdb', ORG: '#0c8599', GPE: '#2f9e44',
  EMAIL_ADDR: '#e67700', DATE: '#9c36b5', LOC: '#c92a2a',
}

function TimelineChart({ data }: { data: YearBucket[] }) {
  if (!data.length) return null
  const maxCount = Math.max(...data.map(d => d.count))
  const chartH = 80
  const barW = Math.min(36, Math.floor(560 / data.length) - 4)

  return (
    <svg width="100%" viewBox={`0 0 ${Math.max(data.length * (barW + 4), 400)} ${chartH + 28}`}
      style={{ display: 'block', overflow: 'visible' }}>
      {data.map((d, i) => {
        const barH = Math.max(4, Math.round(Math.sqrt(d.count / maxCount) * chartH))
        const x = i * (barW + 4)
        const y = chartH - barH
        const isPeak = d.count === maxCount
        return (
          <g key={d.year}>
            <rect x={x} y={y} width={barW} height={barH}
              fill={isPeak ? 'var(--accent)' : 'var(--border)'}
              opacity={isPeak ? 1 : 0.7} rx={2} />
            <text x={x + barW / 2} y={barH >= 18 ? y + barH - 5 : y - 4}
              textAnchor="middle" fontSize={9} fill={barH >= 18 ? '#fff' : 'var(--text-muted)'}>
              {d.count}
            </text>
            <text x={x + barW / 2} y={chartH + 14} textAnchor="middle"
              fontSize={9} fill="var(--text-muted)">{d.year}</text>
          </g>
        )
      })}
    </svg>
  )
}

export default function ProjectDashboard() {
  const { slug } = useParams<{ slug: string }>()
  const [project, setProject] = useState<Project | null>(null)
  const [stats, setStats] = useState<ProjectStats | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!slug) return
    Promise.all([
      fetchJSON<Project>(`/projects/${slug}`),
      fetchJSON<ProjectStats>(`/projects/${slug}/stats`),
    ]).then(([p, s]) => { setProject(p); setStats(s) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [slug])

  if (loading) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '60vh',
      color: 'var(--text-muted)', gap: 10 }}>
      <div style={{ width: 20, height: 20, border: '2px solid var(--border)',
        borderTopColor: 'var(--accent)', borderRadius: '50%', animation: 'spin 0.6s linear infinite' }} />
      Loading project…
    </div>
  )

  if (!project) return (
    <div style={{ padding: 48, color: 'var(--text-muted)' }}>Project not found. <Link to="/">Back</Link></div>
  )

  const dateRange = stats?.date_min
    ? `${stats.date_min.slice(0, 4)} – ${stats.date_max?.slice(0, 4) ?? '?'}`
    : null

  const persons = stats?.top_entities.filter(e => e.type === 'PERSON').slice(0, 8) ?? []
  const orgs = stats?.top_entities.filter(e => e.type === 'ORG').slice(0, 6) ?? []

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)' }}>
      {/* Top bar */}
      <header style={{ background: 'var(--surface)', borderBottom: '1px solid var(--border)', padding: '0 32px' }}>
        <div style={{ maxWidth: 1100, margin: '0 auto', padding: '16px 0', display: 'flex',
          justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <Link to="/" style={{ color: 'var(--text-muted)', textDecoration: 'none', fontSize: 13 }}>
              ← All Projects
            </Link>
            <span style={{ color: 'var(--border)' }}>/</span>
            <h1 style={{ fontSize: 18, fontWeight: 700, margin: 0, color: 'var(--text)' }}>{project.name}</h1>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            {project.datasets?.slice(0, 1).map(d => (
              <Link key={d.slug} to={`/case/${d.slug}/ask`}
                style={{ padding: '8px 18px', background: 'var(--accent)', color: '#fff',
                  borderRadius: 'var(--radius-md)', fontSize: 13, fontWeight: 600,
                  textDecoration: 'none' }}>
                Ask AI
              </Link>
            ))}
          </div>
        </div>
      </header>

      <main style={{ maxWidth: 1100, margin: '0 auto', padding: '32px 32px 64px' }}>
        {/* Stats row */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16, marginBottom: 28 }}>
          {[
            { label: 'Total Documents', value: (project.total_documents ?? 0).toLocaleString() },
            { label: 'Datasets', value: String(project.datasets?.length ?? stats?.datasets.length ?? 0) },
            { label: 'Date Range', value: dateRange ?? '—' },
          ].map(({ label, value }) => (
            <div key={label} style={{ background: 'var(--surface)', border: '1px solid var(--border)',
              borderRadius: 'var(--radius-lg)', padding: '20px 24px' }}>
              <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase',
                color: 'var(--text-muted)', marginBottom: 8 }}>{label}</div>
              <div style={{ fontSize: 24, fontWeight: 700, color: 'var(--text)' }}>{value}</div>
            </div>
          ))}
        </div>

        {/* Datasets in project */}
        <div style={{ marginBottom: 28, background: 'var(--surface)', border: '1px solid var(--border)',
          borderRadius: 'var(--radius-lg)', padding: '20px 24px' }}>
          <h2 style={{ fontSize: 13, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase',
            color: 'var(--text-muted)', margin: '0 0 14px' }}>Datasets in this project</h2>
          <div style={{ display: 'flex', flexWrap: 'wrap' as const, gap: 10 }}>
            {(project.datasets ?? stats?.datasets ?? []).map(d => (
              <Link key={d.slug} to={`/case/${d.slug}`}
                style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 14px',
                  background: '#f0f4ff', border: '1px solid #c5d5ff', borderRadius: 8,
                  textDecoration: 'none', color: '#3b5bdb', fontSize: 13, fontWeight: 500 }}>
                <span>{d.name}</span>
                {'document_count' in d && (
                  <span style={{ fontSize: 11, color: '#6888cc' }}>
                    {(d as DatasetSummary).document_count.toLocaleString()} docs
                  </span>
                )}
              </Link>
            ))}
          </div>
        </div>

        {/* Timeline + entities */}
        <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 20 }}>
          {/* Timeline */}
          <div style={{ background: 'var(--surface)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius-lg)', padding: '20px 24px' }}>
            <h2 style={{ fontSize: 13, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase',
              color: 'var(--text-muted)', margin: '0 0 20px' }}>Document Timeline (all datasets)</h2>
            {stats?.docs_by_year.length ? (
              <TimelineChart data={stats.docs_by_year} />
            ) : (
              <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>No dated documents yet.</p>
            )}
          </div>

          {/* Top entities */}
          <div style={{ background: 'var(--surface)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius-lg)', padding: '20px 24px', overflowY: 'auto' as const, maxHeight: 340 }}>
            <h2 style={{ fontSize: 13, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase',
              color: 'var(--text-muted)', margin: '0 0 14px' }}>Key People</h2>
            {persons.map(e => (
              <div key={e.name} style={{ display: 'flex', justifyContent: 'space-between',
                alignItems: 'center', padding: '6px 0', borderBottom: '1px solid var(--border)',
                fontSize: 13, gap: 8 }}>
                <span style={{ color: 'var(--text)', fontWeight: 500, overflow: 'hidden',
                  textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const }}>{e.name}</span>
                <span style={{ color: 'var(--text-muted)', fontSize: 11, flexShrink: 0 }}>
                  {e.doc_count} docs
                </span>
              </div>
            ))}
            {orgs.length > 0 && (
              <>
                <h2 style={{ fontSize: 13, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase',
                  color: 'var(--text-muted)', margin: '16px 0 10px' }}>Orgs / Places</h2>
                {orgs.map(e => (
                  <div key={e.name} style={{ display: 'flex', justifyContent: 'space-between',
                    alignItems: 'center', padding: '6px 0', borderBottom: '1px solid var(--border)',
                    fontSize: 13, gap: 8 }}>
                    <span style={{ color: 'var(--text)', fontWeight: 500, overflow: 'hidden',
                      textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const }}>{e.name}</span>
                    <span style={{ color: 'var(--text-muted)', fontSize: 11, flexShrink: 0 }}>
                      {e.doc_count}
                    </span>
                  </div>
                ))}
              </>
            )}
          </div>
        </div>
      </main>
    </div>
  )
}
