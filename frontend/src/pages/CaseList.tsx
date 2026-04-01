import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchJSON } from '../api/client'

interface Dataset {
  slug: string
  name: string
  description: string
  document_count: number
  created_at?: string
  last_opened_at?: string
  ingest_status?: 'running' | 'completed' | 'failed' | 'never_run'
}

interface ProjectDataset {
  slug: string
  name: string
}

interface Project {
  slug: string
  name: string
  description: string
  dataset_count: number
  total_documents: number
  datasets: ProjectDataset[]
  created_at?: string
  last_opened_at?: string
}

function formatDate(dateStr?: string): string {
  if (!dateStr) return ''
  try {
    return new Date(dateStr).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
  } catch { return '' }
}

function StatusBadge({ status }: { status?: string }) {
  const map: Record<string, { label: string; bg: string; color: string }> = {
    completed: { label: 'Indexed', bg: '#dcfce7', color: 'var(--success)' },
    running:   { label: 'Indexing…', bg: 'var(--accent-light)', color: 'var(--accent)' },
    failed:    { label: 'Failed', bg: '#fee2e2', color: 'var(--danger)' },
  }
  const s = map[status ?? ''] ?? { label: 'Not indexed', bg: '#f3f4f6', color: 'var(--text-muted)' }
  return (
    <span style={{ display: 'inline-block', padding: '3px 10px', fontSize: 11, fontWeight: 600,
      borderRadius: 'var(--radius-sm)', letterSpacing: '0.02em', background: s.bg, color: s.color }}>
      {s.label}
    </span>
  )
}

function DatasetChip({ name }: { name: string }) {
  return (
    <span style={{ display: 'inline-block', padding: '2px 8px', fontSize: 11, fontWeight: 500,
      borderRadius: 4, background: '#f0f4ff', color: '#3b5bdb', border: '1px solid #c5d5ff',
      whiteSpace: 'nowrap' as const }}>
      {name}
    </span>
  )
}

export default function CaseList() {
  const [tab, setTab] = useState<'projects' | 'datasets'>('projects')
  const [projects, setProjects] = useState<Project[]>([])
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      fetchJSON<Project[]>('/projects').catch(() => []),
      fetchJSON<Dataset[]>('/cases').catch(() => []),
    ]).then(([p, d]) => {
      setProjects(p)
      setDatasets(d)
    }).finally(() => setLoading(false))
  }, [])

  return (
    <div style={S.page}>
      <header style={S.header}>
        <div style={S.headerInner}>
          <div>
            <h1 style={S.logo}>CaseStack</h1>
            <p style={S.tagline}>Document Intelligence Platform</p>
          </div>
          <Link to="/new" style={S.newBtn}>
            <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
              <path d="M8 2a.75.75 0 01.75.75v4.5h4.5a.75.75 0 010 1.5h-4.5v4.5a.75.75 0 01-1.5 0v-4.5h-4.5a.75.75 0 010-1.5h4.5v-4.5A.75.75 0 018 2z" />
            </svg>
            New Dataset
          </Link>
        </div>
      </header>

      <main style={S.content}>
        {/* Tab switcher */}
        <div style={S.tabs}>
          <button style={{ ...S.tab, ...(tab === 'projects' ? S.tabActive : {}) }}
            onClick={() => setTab('projects')}>
            Projects
            <span style={S.tabCount}>{projects.length}</span>
          </button>
          <button style={{ ...S.tab, ...(tab === 'datasets' ? S.tabActive : {}) }}
            onClick={() => setTab('datasets')}>
            Datasets
            <span style={S.tabCount}>{datasets.length}</span>
          </button>
        </div>

        {loading ? (
          <div style={S.loading}><div style={S.spinner} /><span>Loading…</span></div>
        ) : tab === 'projects' ? (
          <ProjectsView projects={projects} />
        ) : (
          <DatasetsView datasets={datasets} />
        )}
      </main>
    </div>
  )
}

function ProjectsView({ projects }: { projects: Project[] }) {
  if (projects.length === 0) {
    return (
      <div style={S.empty}>
        <p style={{ color: 'var(--text-muted)', fontSize: 15 }}>
          No projects yet. Create a dataset first, then group datasets into a project.
        </p>
        <Link to="/new" style={S.emptyBtn}>Add Your First Dataset</Link>
      </div>
    )
  }
  return (
    <div style={S.grid}>
      {projects.map(p => (
        <Link key={p.slug} to={`/project/${p.slug}`} style={S.card} className="case-card">
          <div style={S.cardTop}>
            <h3 style={S.cardName}>{p.name}</h3>
            <span style={S.docCount}>{(p.total_documents ?? 0).toLocaleString()} docs</span>
          </div>
          {p.description && <p style={S.cardDesc}>{p.description}</p>}
          {p.datasets && p.datasets.length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap' as const, gap: 6, marginTop: 12 }}>
              {p.datasets.map(d => <DatasetChip key={d.slug} name={d.name} />)}
            </div>
          )}
          <div style={S.cardMeta}>
            <span>{p.dataset_count} {p.dataset_count === 1 ? 'dataset' : 'datasets'}</span>
            {p.last_opened_at && <span>Opened {formatDate(p.last_opened_at)}</span>}
          </div>
        </Link>
      ))}
    </div>
  )
}

function DatasetsView({ datasets }: { datasets: Dataset[] }) {
  if (datasets.length === 0) {
    return (
      <div style={S.empty}>
        <p style={{ color: 'var(--text-muted)', fontSize: 15 }}>No datasets yet.</p>
        <Link to="/new" style={S.emptyBtn}>Add Your First Dataset</Link>
      </div>
    )
  }
  return (
    <div style={S.grid}>
      {datasets.map(d => (
        <Link key={d.slug} to={`/case/${d.slug}`} style={S.card} className="case-card">
          <div style={S.cardTop}>
            <h3 style={S.cardName}>{d.name}</h3>
            <StatusBadge status={d.ingest_status} />
          </div>
          {d.description && <p style={S.cardDesc}>{d.description}</p>}
          <div style={S.cardMeta}>
            <span>{(d.document_count ?? 0).toLocaleString()} {d.document_count === 1 ? 'document' : 'documents'}</span>
            {d.last_opened_at && <span>Opened {formatDate(d.last_opened_at)}</span>}
          </div>
        </Link>
      ))}
    </div>
  )
}

const S: Record<string, React.CSSProperties> = {
  page: { minHeight: '100vh', background: 'var(--bg)' },
  header: { background: 'var(--surface)', borderBottom: '1px solid var(--border)', padding: '0 32px' },
  headerInner: { maxWidth: 960, margin: '0 auto', display: 'flex', justifyContent: 'space-between',
    alignItems: 'center', padding: '24px 0' },
  logo: { fontSize: 24, fontWeight: 700, color: 'var(--text)', margin: 0, letterSpacing: '-0.02em' },
  tagline: { fontSize: 13, color: 'var(--text-muted)', margin: '2px 0 0' },
  newBtn: { display: 'inline-flex', alignItems: 'center', gap: 8, padding: '10px 24px',
    background: 'var(--accent)', color: '#fff', borderRadius: 'var(--radius-md)', fontSize: 14,
    fontWeight: 600, textDecoration: 'none', boxShadow: '0 1px 3px rgba(37,99,235,0.3)' },
  content: { maxWidth: 960, margin: '0 auto', padding: '32px 32px 64px' },
  tabs: { display: 'flex', gap: 4, marginBottom: 24, borderBottom: '1px solid var(--border)',
    paddingBottom: 0 },
  tab: { display: 'inline-flex', alignItems: 'center', gap: 8, padding: '10px 16px 12px',
    fontSize: 14, fontWeight: 500, color: 'var(--text-muted)', background: 'none', border: 'none',
    borderBottom: '2px solid transparent', cursor: 'pointer', marginBottom: -1, transition: 'all 0.15s' },
  tabActive: { color: 'var(--accent)', borderBottom: '2px solid var(--accent)' },
  tabCount: { display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
    minWidth: 20, height: 20, padding: '0 6px', fontSize: 11, fontWeight: 600,
    borderRadius: 10, background: '#f3f4f6', color: 'var(--text-muted)' },
  grid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 16 },
  card: { display: 'block', background: 'var(--surface)', border: '1px solid var(--border)',
    borderRadius: 'var(--radius-lg)', padding: 24, textDecoration: 'none', color: 'inherit',
    transition: 'all 0.2s ease', cursor: 'pointer' },
  cardTop: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
    gap: 12, marginBottom: 8 },
  cardName: { fontSize: 16, fontWeight: 600, color: 'var(--text)', margin: 0, lineHeight: 1.3 },
  cardDesc: { fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.5, margin: '0 0 4px',
    display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' as const, overflow: 'hidden' },
  cardMeta: { display: 'flex', alignItems: 'center', gap: 16, paddingTop: 14, marginTop: 12,
    borderTop: '1px solid var(--border)', fontSize: 12, color: 'var(--text-muted)' },
  docCount: { fontSize: 12, fontWeight: 600, color: 'var(--text-muted)',
    background: '#f3f4f6', padding: '2px 8px', borderRadius: 4, whiteSpace: 'nowrap' as const },
  empty: { display: 'flex', flexDirection: 'column' as const, alignItems: 'center',
    padding: '80px 32px', textAlign: 'center' as const, gap: 20 },
  emptyBtn: { display: 'inline-flex', alignItems: 'center', gap: 8, padding: '12px 32px',
    background: 'var(--accent)', color: '#fff', borderRadius: 'var(--radius-md)',
    fontSize: 15, fontWeight: 600, textDecoration: 'none' },
  loading: { display: 'flex', alignItems: 'center', justifyContent: 'center',
    gap: 12, padding: 64, color: 'var(--text-muted)', fontSize: 14 },
  spinner: { width: 20, height: 20, border: '2px solid var(--border)',
    borderTopColor: 'var(--accent)', borderRadius: '50%', animation: 'spin 0.6s linear infinite' },
}
