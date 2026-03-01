import { useState } from 'react'

interface Props {
  slug: string
  documentId: string
  /** Optional file path hint to determine audio vs video */
  sourcePath?: string
}

const VIDEO_EXTS = ['.mp4', '.webm', '.ogv', '.mov', '.avi', '.mkv']
const AUDIO_EXTS = ['.mp3', '.wav', '.ogg', '.flac', '.aac', '.m4a', '.wma']

function isVideo(path?: string): boolean {
  if (!path) return false
  const lower = path.toLowerCase()
  return VIDEO_EXTS.some((ext) => lower.endsWith(ext))
}

function isAudio(path?: string): boolean {
  if (!path) return false
  const lower = path.toLowerCase()
  return AUDIO_EXTS.some((ext) => lower.endsWith(ext))
}

export default function MediaPlayer({ slug, documentId, sourcePath }: Props) {
  const [error, setError] = useState(false)

  if (error) {
    return (
      <div style={styles.fallback}>
        <span style={styles.fallbackIcon}>--</span>
        <span style={styles.fallbackText}>Media file unavailable</span>
      </div>
    )
  }

  const mediaUrl = `/api/cases/${slug}/media/${documentId}`

  // Determine media type from source path
  const useVideo = isVideo(sourcePath)
  const useAudio = isAudio(sourcePath)

  // Default to audio if we can't determine, since transcripts are typically audio
  if (useVideo) {
    return (
      <div style={styles.container}>
        <video
          src={mediaUrl}
          controls
          preload="metadata"
          onError={() => setError(true)}
          style={styles.video}
        >
          Your browser does not support the video element.
        </video>
      </div>
    )
  }

  // Audio player (default)
  return (
    <div style={styles.container}>
      <audio
        src={mediaUrl}
        controls
        preload="metadata"
        onError={() => setError(true)}
        style={styles.audio}
      >
        Your browser does not support the audio element.
      </audio>
      {!useAudio && !useVideo && sourcePath && (
        <div style={styles.hint}>
          Unknown format — attempting audio playback
        </div>
      )}
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    padding: '12px 0',
  },
  audio: {
    width: '100%',
    borderRadius: 'var(--radius-sm)',
  },
  video: {
    width: '100%',
    maxHeight: 360,
    borderRadius: 'var(--radius-sm)',
    background: '#000',
  },
  fallback: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '12px 16px',
    background: '#f9fafb',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-sm)',
    fontSize: 13,
    color: 'var(--text-muted)',
  },
  fallbackIcon: {
    fontSize: 14,
    opacity: 0.6,
  },
  fallbackText: {
    fontSize: 13,
  },
  hint: {
    fontSize: 11,
    color: 'var(--text-muted)',
    marginTop: 4,
    fontStyle: 'italic',
  },
}
