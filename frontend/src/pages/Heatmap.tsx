import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { MapContainer, TileLayer, CircleMarker, Popup } from 'react-leaflet'
import { fetchJSON } from '../api/client'
import 'leaflet/dist/leaflet.css'

interface LocationData {
  location: string
  lat: number
  lng: number
  mentions: number
}

export default function Heatmap() {
  const { slug } = useParams<{ slug: string }>()
  const [locations, setLocations] = useState<LocationData[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!slug) return

    fetchJSON<LocationData[]>(`/cases/${slug}/map`)
      .then(data => {
        setLocations(data)
        setLoading(false)
      })
      .catch(err => {
        setError(err.message)
        setLoading(false)
      })
  }, [slug])

  if (loading) {
    return <div style={styles.loading}>Loading map data...</div>
  }

  if (error) {
    return (
      <div style={styles.errorContainer}>
        <h2 style={styles.errorTitle}>Error loading map</h2>
        <p style={styles.errorMessage}>{error}</p>
      </div>
    )
  }

  if (locations.length === 0) {
    return (
      <div style={styles.emptyContainer}>
        <div style={styles.emptyIcon}>&#x1F5FA;</div>
        <h2 style={styles.emptyTitle}>No geographic data available</h2>
        <p style={styles.emptyMessage}>
          Location data will appear here once documents with geographic
          references have been processed.
        </p>
      </div>
    )
  }

  const maxMentions = Math.max(...locations.map(l => l.mentions))

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <h1 style={styles.title}>Geographic Map</h1>
        <span style={styles.badge}>
          {locations.length} location{locations.length !== 1 ? 's' : ''}
        </span>
      </div>
      <div style={styles.mapWrapper}>
        <MapContainer
          center={[20, 0]}
          zoom={2}
          style={{ width: '100%', height: '100%' }}
          scrollWheelZoom={true}
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          {locations.map((loc, i) => {
            const radius = Math.max(6, Math.sqrt(loc.mentions / maxMentions) * 30)
            return (
              <CircleMarker
                key={i}
                center={[loc.lat, loc.lng]}
                radius={radius}
                pathOptions={{
                  color: 'var(--accent, #6366f1)',
                  fillColor: 'var(--accent, #6366f1)',
                  fillOpacity: 0.35,
                  weight: 2,
                }}
              >
                <Popup>
                  <div style={styles.popup}>
                    <strong style={styles.popupName}>{loc.location}</strong>
                    <span style={styles.popupCount}>
                      {loc.mentions} mention{loc.mentions !== 1 ? 's' : ''}
                    </span>
                  </div>
                </Popup>
              </CircleMarker>
            )
          })}
        </MapContainer>
      </div>

      {/* Legend */}
      <div style={styles.legend}>
        <div style={styles.legendTitle}>Locations by mention count</div>
        <div style={styles.legendItems}>
          {locations
            .sort((a, b) => b.mentions - a.mentions)
            .slice(0, 10)
            .map((loc, i) => (
              <div key={i} style={styles.legendItem}>
                <div
                  style={{
                    ...styles.legendDot,
                    width: Math.max(8, Math.sqrt(loc.mentions / maxMentions) * 20),
                    height: Math.max(8, Math.sqrt(loc.mentions / maxMentions) * 20),
                  }}
                />
                <span style={styles.legendLabel}>{loc.location}</span>
                <span style={styles.legendCount}>{loc.mentions}</span>
              </div>
            ))}
        </div>
      </div>
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    height: 'calc(100vh - 64px)',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    marginBottom: 20,
    flexShrink: 0,
  },
  title: {
    fontSize: 28,
    fontWeight: 700,
    color: 'var(--text)',
    margin: 0,
  },
  badge: {
    display: 'inline-block',
    padding: '4px 12px',
    fontSize: 12,
    fontWeight: 600,
    borderRadius: 20,
    background: 'var(--accent-light)',
    color: 'var(--accent)',
  },
  mapWrapper: {
    flex: 1,
    minHeight: 0,
    borderRadius: 'var(--radius-md)',
    overflow: 'hidden',
    border: '1px solid var(--border)',
  },
  legend: {
    flexShrink: 0,
    marginTop: 16,
    padding: 16,
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-md)',
    maxHeight: 200,
    overflowY: 'auto',
  },
  legendTitle: {
    fontSize: 13,
    fontWeight: 600,
    color: 'var(--text-muted)',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.05em',
    marginBottom: 10,
  },
  legendItems: {
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
  },
  legendItem: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  legendDot: {
    borderRadius: '50%',
    background: 'var(--accent, #6366f1)',
    opacity: 0.6,
    flexShrink: 0,
  },
  legendLabel: {
    fontSize: 13,
    color: 'var(--text)',
    flex: 1,
  },
  legendCount: {
    fontSize: 13,
    fontWeight: 600,
    color: 'var(--text-muted)',
  },
  loading: {
    padding: 32,
    color: 'var(--text-muted)',
    fontSize: 14,
  },
  errorContainer: {
    padding: 32,
  },
  errorTitle: {
    fontSize: 20,
    fontWeight: 700,
    color: 'var(--danger)',
    marginBottom: 8,
  },
  errorMessage: {
    fontSize: 14,
    color: 'var(--text-muted)',
  },
  emptyContainer: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    padding: '80px 20px',
    textAlign: 'center' as const,
  },
  emptyIcon: {
    fontSize: 48,
    marginBottom: 16,
  },
  emptyTitle: {
    fontSize: 20,
    fontWeight: 700,
    color: 'var(--text)',
    marginBottom: 8,
  },
  emptyMessage: {
    fontSize: 14,
    color: 'var(--text-muted)',
    maxWidth: 400,
    lineHeight: 1.5,
  },
  popup: {
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
    minWidth: 120,
  },
  popupName: {
    fontSize: 14,
    fontWeight: 600,
    color: '#1f2937',
  },
  popupCount: {
    fontSize: 12,
    color: '#6b7280',
  },
}
