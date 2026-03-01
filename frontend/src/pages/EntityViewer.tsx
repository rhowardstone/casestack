import { useEffect, useState, useMemo } from 'react'
import { useParams } from 'react-router-dom'
import { fetchJSON } from '../api/client'
import EntityGraph, {
  type GraphNode,
  type GraphEdge,
} from '../components/EntityGraph'

/* ---------- API response types ---------- */

interface Entity {
  id: string
  name: string
  type: string
  mentions: number
}

interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

/* ---------- constants ---------- */

const PAGE_SIZE = 30

const TYPE_COLORS: Record<string, string> = {
  person: '#3b82f6',
  org: '#22c55e',
  organization: '#22c55e',
  location: '#ef4444',
  place: '#ef4444',
  date: '#f59e0b',
  event: '#8b5cf6',
  money: '#0891b2',
  phone: '#ec4899',
  email: '#6366f1',
}

function badgeColor(type: string): string {
  return TYPE_COLORS[type.toLowerCase()] || '#94a3b8'
}

/* ---------- component ---------- */

type ViewMode = 'directory' | 'graph'

export default function EntityViewer() {
  const { slug = '' } = useParams<{ slug: string }>()

  /* shared state */
  const [view, setView] = useState<ViewMode>('directory')

  /* ---- directory state ---- */
  const [entities, setEntities] = useState<Entity[]>([])
  const [loadingEntities, setLoadingEntities] = useState(false)
  const [entityError, setEntityError] = useState('')
  const [typeFilter, setTypeFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(0)

  /* ---- graph state ---- */
  const [graphData, setGraphData] = useState<GraphData | null>(null)
  const [loadingGraph, setLoadingGraph] = useState(false)
  const [graphError, setGraphError] = useState('')
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null)

  /* ---- fetch entities ---- */
  useEffect(() => {
    if (!slug) return
    setLoadingEntities(true)
    setEntityError('')
    fetchJSON<Entity[]>(`/cases/${slug}/entities`)
      .then(setEntities)
      .catch(err => setEntityError(err.message))
      .finally(() => setLoadingEntities(false))
  }, [slug])

  /* ---- fetch graph when user switches to graph view ---- */
  useEffect(() => {
    if (view !== 'graph' || graphData || !slug) return
    setLoadingGraph(true)
    setGraphError('')
    fetchJSON<GraphData>(`/cases/${slug}/entities/graph`)
      .then(setGraphData)
      .catch(err => setGraphError(err.message))
      .finally(() => setLoadingGraph(false))
  }, [view, graphData, slug])

  /* ---- derived: unique entity types for filter dropdown ---- */
  const entityTypes = useMemo(() => {
    const types = new Set(entities.map(e => e.type))
    return Array.from(types).sort()
  }, [entities])

  /* ---- derived: filtered + searched + paginated entities ---- */
  const filtered = useMemo(() => {
    let list = entities
    if (typeFilter !== 'all') {
      list = list.filter(e => e.type === typeFilter)
    }
    if (search.trim()) {
      const q = search.trim().toLowerCase()
      list = list.filter(e => e.name.toLowerCase().includes(q))
    }
    return list
  }, [entities, typeFilter, search])

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const currentPage = Math.min(page, totalPages - 1)
  const pageEntities = filtered.slice(
    currentPage * PAGE_SIZE,
    (currentPage + 1) * PAGE_SIZE,
  )

  /* Reset page when filters change */
  useEffect(() => {
    setPage(0)
  }, [typeFilter, search])

  /* ---------------------------------------------------------------- */

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto' }}>
      {/* Header */}
      <div style={styles.header}>
        <h1 style={styles.title}>Entities</h1>
        <div style={styles.viewToggle}>
          <button
            onClick={() => setView('directory')}
            style={{
              ...styles.toggleBtn,
              ...(view === 'directory' ? styles.toggleActive : {}),
            }}
          >
            Directory
          </button>
          <button
            onClick={() => setView('graph')}
            style={{
              ...styles.toggleBtn,
              ...(view === 'graph' ? styles.toggleActive : {}),
            }}
          >
            Graph
          </button>
        </div>
      </div>

      {/* ----- DIRECTORY VIEW ----- */}
      {view === 'directory' && (
        <>
          {/* Filters row */}
          <div style={styles.filtersRow}>
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search entities by name..."
              style={styles.searchInput}
              onFocus={e => (e.currentTarget.style.borderColor = 'var(--accent)')}
              onBlur={e => (e.currentTarget.style.borderColor = 'var(--border)')}
            />
            <select
              value={typeFilter}
              onChange={e => setTypeFilter(e.target.value)}
              style={styles.typeSelect}
            >
              <option value="all">All types</option>
              {entityTypes.map(t => (
                <option key={t} value={t}>
                  {t.charAt(0).toUpperCase() + t.slice(1)}
                </option>
              ))}
            </select>
          </div>

          {/* Count */}
          <div style={styles.countLine}>
            {loadingEntities
              ? 'Loading...'
              : `${filtered.length} entit${filtered.length === 1 ? 'y' : 'ies'}`}
          </div>

          {entityError && (
            <div style={styles.error}>{entityError}</div>
          )}

          {/* Entity cards grid */}
          <div style={styles.grid}>
            {pageEntities.map(e => (
              <div key={e.id} style={styles.card}>
                <div style={styles.cardName}>{e.name}</div>
                <div style={styles.cardMeta}>
                  <span
                    style={{
                      ...styles.typeBadge,
                      background: `${badgeColor(e.type)}18`,
                      color: badgeColor(e.type),
                    }}
                  >
                    {e.type}
                  </span>
                  <span style={styles.mentionCount}>
                    {e.mentions} mention{e.mentions !== 1 ? 's' : ''}
                  </span>
                </div>
              </div>
            ))}
          </div>

          {/* Empty state */}
          {!loadingEntities && filtered.length === 0 && (
            <div style={styles.empty}>
              {entities.length === 0
                ? 'No entities found for this case.'
                : 'No entities match your filters.'}
            </div>
          )}

          {/* Pagination */}
          {totalPages > 1 && (
            <div style={styles.pagination}>
              <button
                disabled={currentPage === 0}
                onClick={() => setPage(p => p - 1)}
                style={styles.pageBtn}
              >
                Previous
              </button>
              <span style={styles.pageInfo}>
                Page {currentPage + 1} of {totalPages}
              </span>
              <button
                disabled={currentPage >= totalPages - 1}
                onClick={() => setPage(p => p + 1)}
                style={styles.pageBtn}
              >
                Next
              </button>
            </div>
          )}
        </>
      )}

      {/* ----- GRAPH VIEW ----- */}
      {view === 'graph' && (
        <div style={styles.graphContainer}>
          {loadingGraph && (
            <div style={styles.graphLoading}>Loading graph data...</div>
          )}
          {graphError && <div style={styles.error}>{graphError}</div>}

          {graphData && (
            <div style={styles.graphWrapper}>
              <EntityGraph
                nodes={graphData.nodes}
                edges={graphData.edges}
                onSelectNode={setSelectedNode}
              />

              {/* Legend */}
              <div style={styles.legend}>
                {Object.entries(TYPE_COLORS)
                  .filter(([k]) => !['organization', 'place'].includes(k))
                  .map(([type, color]) => (
                    <div key={type} style={styles.legendItem}>
                      <span
                        style={{
                          ...styles.legendDot,
                          background: color,
                        }}
                      />
                      <span style={styles.legendLabel}>
                        {type.charAt(0).toUpperCase() + type.slice(1)}
                      </span>
                    </div>
                  ))}
              </div>

              {/* Selected node detail */}
              {selectedNode && (
                <div style={styles.nodeDetail}>
                  <div style={styles.nodeDetailName}>{selectedNode.id}</div>
                  <div style={styles.nodeDetailRow}>
                    <span
                      style={{
                        ...styles.typeBadge,
                        background: `${badgeColor(selectedNode.type)}18`,
                        color: badgeColor(selectedNode.type),
                      }}
                    >
                      {selectedNode.type}
                    </span>
                    <span style={styles.mentionCount}>
                      {selectedNode.mentions} mention
                      {selectedNode.mentions !== 1 ? 's' : ''}
                    </span>
                  </div>
                </div>
              )}
            </div>
          )}

          {!loadingGraph && !graphError && !graphData && (
            <div style={styles.empty}>No graph data available.</div>
          )}
        </div>
      )}
    </div>
  )
}

/* ---------- styles ---------- */

const styles: Record<string, React.CSSProperties> = {
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 24,
    flexWrap: 'wrap',
    gap: 16,
  },
  title: {
    fontSize: 28,
    fontWeight: 700,
    color: 'var(--text)',
    margin: 0,
  },
  viewToggle: {
    display: 'flex',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-md)',
    overflow: 'hidden',
  },
  toggleBtn: {
    padding: '8px 20px',
    fontSize: 13,
    fontWeight: 500,
    fontFamily: 'inherit',
    border: 'none',
    background: 'var(--surface)',
    color: 'var(--text-muted)',
    cursor: 'pointer',
    transition: 'all 0.15s ease',
  },
  toggleActive: {
    background: 'var(--accent)',
    color: '#fff',
    fontWeight: 600,
  },
  filtersRow: {
    display: 'flex',
    gap: 12,
    marginBottom: 16,
    flexWrap: 'wrap' as const,
  },
  searchInput: {
    flex: 1,
    minWidth: 200,
    padding: '10px 16px',
    fontSize: 14,
    fontFamily: 'inherit',
    border: '2px solid var(--border)',
    borderRadius: 'var(--radius-md)',
    outline: 'none',
    background: 'var(--surface)',
    color: 'var(--text)',
    transition: 'border-color 0.15s ease',
  },
  typeSelect: {
    padding: '10px 16px',
    fontSize: 14,
    fontFamily: 'inherit',
    border: '2px solid var(--border)',
    borderRadius: 'var(--radius-md)',
    outline: 'none',
    background: 'var(--surface)',
    color: 'var(--text)',
    cursor: 'pointer',
    minWidth: 140,
  },
  countLine: {
    fontSize: 13,
    color: 'var(--text-muted)',
    marginBottom: 16,
  },
  error: {
    padding: 16,
    marginBottom: 16,
    borderRadius: 'var(--radius-md)',
    background: '#fee2e2',
    color: 'var(--danger)',
    fontSize: 14,
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
    gap: 12,
  },
  card: {
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-md)',
    padding: '16px 20px',
    transition: 'border-color 0.15s ease',
  },
  cardName: {
    fontSize: 15,
    fontWeight: 600,
    color: 'var(--text)',
    marginBottom: 8,
    wordBreak: 'break-word' as const,
  },
  cardMeta: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
  },
  typeBadge: {
    display: 'inline-block',
    padding: '3px 10px',
    fontSize: 11,
    fontWeight: 600,
    borderRadius: 12,
    textTransform: 'capitalize' as const,
  },
  mentionCount: {
    fontSize: 12,
    color: 'var(--text-muted)',
  },
  empty: {
    textAlign: 'center' as const,
    padding: '60px 20px',
    color: 'var(--text-muted)',
    fontSize: 15,
  },
  pagination: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 16,
    marginTop: 24,
    paddingBottom: 24,
  },
  pageBtn: {
    padding: '8px 16px',
    fontSize: 13,
    fontWeight: 500,
    fontFamily: 'inherit',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-sm)',
    background: 'var(--surface)',
    color: 'var(--text)',
    cursor: 'pointer',
  },
  pageInfo: {
    fontSize: 13,
    color: 'var(--text-muted)',
  },
  graphContainer: {
    position: 'relative' as const,
  },
  graphLoading: {
    padding: 32,
    textAlign: 'center' as const,
    color: 'var(--text-muted)',
    fontSize: 14,
  },
  graphWrapper: {
    position: 'relative' as const,
    height: 'calc(100vh - 180px)',
    minHeight: 500,
  },
  legend: {
    position: 'absolute' as const,
    top: 12,
    left: 12,
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 6,
    padding: '12px 16px',
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-md)',
    fontSize: 12,
  },
  legendItem: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  legendDot: {
    display: 'inline-block',
    width: 10,
    height: 10,
    borderRadius: '50%',
  },
  legendLabel: {
    color: 'var(--text)',
    fontWeight: 500,
  },
  nodeDetail: {
    position: 'absolute' as const,
    top: 12,
    right: 12,
    padding: '16px 20px',
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-md)',
    minWidth: 180,
  },
  nodeDetailName: {
    fontSize: 15,
    fontWeight: 600,
    color: 'var(--text)',
    marginBottom: 8,
    wordBreak: 'break-word' as const,
  },
  nodeDetailRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
  },
}
