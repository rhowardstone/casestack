interface Props {
  label: string
  percent: number
}

export default function ProgressBar({ label, percent }: Props) {
  const clamped = Math.max(0, Math.min(100, percent))

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <span style={styles.label}>{label}</span>
        <span style={styles.percent}>{Math.round(clamped)}%</span>
      </div>
      <div style={styles.track}>
        <div
          style={{
            ...styles.fill,
            width: `${clamped}%`,
          }}
        />
      </div>
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    width: '100%',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 6,
  },
  label: {
    fontSize: 13,
    fontWeight: 500,
    color: 'var(--text)',
  },
  percent: {
    fontSize: 13,
    fontWeight: 600,
    color: 'var(--accent)',
  },
  track: {
    width: '100%',
    height: 8,
    background: 'var(--border)',
    borderRadius: 4,
    overflow: 'hidden',
  },
  fill: {
    height: '100%',
    background: 'var(--accent)',
    borderRadius: 4,
    transition: 'width 0.4s ease',
  },
}
