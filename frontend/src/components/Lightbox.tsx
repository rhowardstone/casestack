import { useEffect, useCallback } from 'react'

export interface LightboxImage {
  id: string
  document_id: string
  page_number: number | null
  description: string | null
  src: string
}

interface Props {
  images: LightboxImage[]
  currentIndex: number
  onClose: () => void
  onNavigate: (index: number) => void
}

export default function Lightbox({ images, currentIndex, onClose, onNavigate }: Props) {
  const image = images[currentIndex]
  const hasPrev = currentIndex > 0
  const hasNext = currentIndex < images.length - 1

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      if (e.key === 'ArrowLeft' && hasPrev) onNavigate(currentIndex - 1)
      if (e.key === 'ArrowRight' && hasNext) onNavigate(currentIndex + 1)
    },
    [onClose, onNavigate, currentIndex, hasPrev, hasNext],
  )

  useEffect(() => {
    document.addEventListener('keydown', handleKeyDown)
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = ''
    }
  }, [handleKeyDown])

  const handleOverlayClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) onClose()
  }

  if (!image) return null

  return (
    <div style={styles.overlay} onClick={handleOverlayClick}>
      <div style={styles.container}>
        {/* Close button */}
        <button
          onClick={onClose}
          style={styles.closeButton}
          aria-label="Close lightbox"
        >
          &times;
        </button>

        {/* Navigation arrows */}
        {hasPrev && (
          <button
            onClick={() => onNavigate(currentIndex - 1)}
            style={{ ...styles.navButton, left: 16 }}
            aria-label="Previous image"
          >
            &#8249;
          </button>
        )}
        {hasNext && (
          <button
            onClick={() => onNavigate(currentIndex + 1)}
            style={{ ...styles.navButton, right: 16 }}
            aria-label="Next image"
          >
            &#8250;
          </button>
        )}

        {/* Image area */}
        <div style={styles.imageWrapper}>
          <img
            src={image.src}
            alt={image.description || `Image from ${image.document_id}`}
            style={styles.image}
          />
        </div>

        {/* Info panel below image */}
        <div style={styles.infoPanel}>
          {image.description && (
            <p style={styles.description}>{image.description}</p>
          )}
          <div style={styles.meta}>
            <span style={styles.metaItem}>
              Document: <strong>{image.document_id}</strong>
            </span>
            {image.page_number != null && (
              <span style={styles.metaItem}>
                Page: <strong>{image.page_number}</strong>
              </span>
            )}
            <span style={styles.counter}>
              {currentIndex + 1} / {images.length}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  overlay: {
    position: 'fixed',
    inset: 0,
    background: 'rgba(0, 0, 0, 0.85)',
    zIndex: 9999,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    animation: 'lightbox-fade-in 0.2s ease',
  },
  container: {
    position: 'relative',
    maxWidth: '90vw',
    maxHeight: '90vh',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
  },
  closeButton: {
    position: 'absolute',
    top: -40,
    right: -8,
    background: 'none',
    border: 'none',
    color: '#fff',
    fontSize: 32,
    cursor: 'pointer',
    padding: '4px 12px',
    lineHeight: 1,
    opacity: 0.8,
    zIndex: 10,
    fontFamily: 'inherit',
  },
  navButton: {
    position: 'fixed',
    top: '50%',
    transform: 'translateY(-50%)',
    background: 'rgba(255, 255, 255, 0.1)',
    border: '1px solid rgba(255, 255, 255, 0.2)',
    color: '#fff',
    fontSize: 40,
    cursor: 'pointer',
    padding: '8px 16px',
    lineHeight: 1,
    borderRadius: 8,
    zIndex: 10,
    fontFamily: 'inherit',
    transition: 'background 0.15s ease',
  },
  imageWrapper: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    maxHeight: '70vh',
    overflow: 'hidden',
  },
  image: {
    maxWidth: '85vw',
    maxHeight: '70vh',
    objectFit: 'contain',
    borderRadius: 4,
  },
  infoPanel: {
    marginTop: 16,
    maxWidth: '85vw',
    width: '100%',
  },
  description: {
    color: '#e5e7eb',
    fontSize: 15,
    lineHeight: 1.6,
    margin: '0 0 12px 0',
    textAlign: 'center' as const,
  },
  meta: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 20,
    flexWrap: 'wrap' as const,
  },
  metaItem: {
    color: '#9ca3af',
    fontSize: 13,
  },
  counter: {
    color: '#6b7280',
    fontSize: 13,
    fontWeight: 500,
  },
}
