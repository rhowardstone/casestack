import { useState, useEffect, useMemo } from 'react'
import { useParams } from 'react-router-dom'
import { fetchJSON } from '../api/client'
import Lightbox, { type LightboxImage } from '../components/Lightbox'

interface ImageRecord {
  id: string
  document_id: string
  page_number: number | null
  file_path: string
  description: string | null
}

interface ImagesResponse {
  total: number
  images: ImageRecord[]
}

const FILTER_OPTIONS = [
  { value: 'all', label: 'All' },
  { value: 'with_description', label: 'With description' },
] as const

export default function ImageGallery() {
  const { slug = '' } = useParams<{ slug: string }>()
  const [images, setImages] = useState<ImageRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<'all' | 'with_description'>('all')
  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null)

  useEffect(() => {
    if (!slug) return
    setLoading(true)
    setError(null)
    fetchJSON<ImagesResponse>(`/cases/${slug}/images`)
      .then((data) => setImages(data.images))
      .catch((err) => setError(err.message || 'Failed to load images'))
      .finally(() => setLoading(false))
  }, [slug])

  const filtered = useMemo(() => {
    if (filter === 'with_description') {
      return images.filter((img) => img.description && img.description.trim().length > 0)
    }
    return images
  }, [images, filter])

  const lightboxImages: LightboxImage[] = useMemo(
    () =>
      filtered.map((img) => ({
        id: img.id,
        document_id: img.document_id,
        page_number: img.page_number,
        description: img.description,
        src: `/api/cases/${slug}/images/${img.id}/file`,
      })),
    [filtered, slug],
  )

  const thumbUrl = (img: ImageRecord) => `/api/cases/${slug}/images/${img.id}/file`

  if (error) {
    return (
      <div style={styles.errorContainer}>
        <h2 style={styles.errorTitle}>Error loading images</h2>
        <p style={styles.errorMessage}>{error}</p>
      </div>
    )
  }

  if (loading) {
    return <div style={styles.loading}>Loading images...</div>
  }

  return (
    <div>
      <div style={styles.header}>
        <h1 style={styles.title}>Images</h1>
        <span style={styles.count}>
          {filtered.length}
          {filter !== 'all' ? ` of ${images.length}` : ''} image
          {filtered.length !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Filter pills */}
      <div style={styles.filterRow}>
        {FILTER_OPTIONS.map((opt) => {
          const active = filter === opt.value
          return (
            <button
              key={opt.value}
              onClick={() => setFilter(opt.value as typeof filter)}
              style={{
                padding: '6px 16px',
                fontSize: 13,
                fontWeight: 500,
                fontFamily: 'inherit',
                border: `1px solid ${active ? 'var(--accent)' : 'var(--border)'}`,
                borderRadius: 20,
                background: active ? 'var(--accent)' : 'var(--surface)',
                color: active ? '#fff' : 'var(--text-muted)',
                cursor: 'pointer',
                transition: 'all 0.15s ease',
              }}
            >
              {opt.label}
            </button>
          )
        })}
      </div>

      {/* Gallery grid */}
      {filtered.length > 0 ? (
        <div style={styles.grid}>
          {filtered.map((img, idx) => (
            <div
              key={img.id}
              className="image-card"
              style={styles.card}
              onClick={() => setLightboxIndex(idx)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  setLightboxIndex(idx)
                }
              }}
            >
              <div style={styles.thumbWrapper}>
                <img
                  src={thumbUrl(img)}
                  alt={img.description || `Image from ${img.document_id}`}
                  style={styles.thumb}
                  loading="lazy"
                />
              </div>
              <div style={styles.cardInfo}>
                <div style={styles.docId} title={img.document_id}>
                  {img.document_id}
                </div>
                {img.page_number != null && (
                  <div style={styles.pageNum}>Page {img.page_number}</div>
                )}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div style={styles.empty}>
          <div style={styles.emptyTitle}>No images found</div>
          <div style={styles.emptyHint}>
            {filter === 'with_description'
              ? 'No images have AI descriptions yet. Try switching to "All".'
              : 'This case has no extracted images.'}
          </div>
        </div>
      )}

      {/* Lightbox */}
      {lightboxIndex != null && (
        <Lightbox
          images={lightboxImages}
          currentIndex={lightboxIndex}
          onClose={() => setLightboxIndex(null)}
          onNavigate={setLightboxIndex}
        />
      )}
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
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
  header: {
    display: 'flex',
    alignItems: 'baseline',
    gap: 16,
    marginBottom: 20,
  },
  title: {
    fontSize: 28,
    fontWeight: 700,
    color: 'var(--text)',
    margin: 0,
  },
  count: {
    fontSize: 14,
    color: 'var(--text-muted)',
    fontWeight: 500,
  },
  filterRow: {
    display: 'flex',
    gap: 8,
    marginBottom: 24,
    flexWrap: 'wrap' as const,
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
    gap: 16,
  },
  card: {
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-md)',
    overflow: 'hidden',
    cursor: 'pointer',
    transition: 'border-color 0.15s ease, box-shadow 0.15s ease',
  },
  thumbWrapper: {
    width: '100%',
    aspectRatio: '1',
    overflow: 'hidden',
    background: '#f3f4f6',
  },
  thumb: {
    width: '100%',
    height: '100%',
    objectFit: 'cover',
    display: 'block',
    transition: 'transform 0.2s ease',
  },
  cardInfo: {
    padding: '10px 12px',
  },
  docId: {
    fontSize: 12,
    fontWeight: 600,
    color: 'var(--text)',
    whiteSpace: 'nowrap' as const,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  },
  pageNum: {
    fontSize: 11,
    color: 'var(--text-muted)',
    marginTop: 2,
  },
  empty: {
    textAlign: 'center' as const,
    padding: '80px 20px',
    color: 'var(--text-muted)',
  },
  emptyTitle: {
    fontSize: 24,
    marginBottom: 12,
    fontWeight: 600,
  },
  emptyHint: {
    fontSize: 15,
  },
}
