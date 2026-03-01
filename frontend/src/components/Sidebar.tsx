import { NavLink, Link } from 'react-router-dom'

interface Props {
  slug: string
  caseName: string
}

const navItems = [
  { to: '', label: 'Dashboard', icon: '\u2302' },
  { to: '/search', label: 'Search', icon: '\u{1F50D}' },
  { to: '/entities', label: 'Entities', icon: '\u{1F465}' },
  { to: '/images', label: 'Images', icon: '\u{1F5BC}' },
  { to: '/transcripts', label: 'Transcripts', icon: '\u{1F399}' },
  { to: '/map', label: 'Map', icon: '\u{1F5FA}' },
  { to: '/ask', label: 'Ask AI', icon: '\u2728' },
]

export default function Sidebar({ slug, caseName }: Props) {
  const basePath = `/case/${slug}`

  return (
    <aside style={styles.sidebar}>
      <Link to="/" style={styles.backLink}>
        &larr; All Cases
      </Link>

      <div style={styles.caseHeader}>
        <div style={styles.caseName}>{caseName || 'Loading...'}</div>
      </div>

      <nav style={styles.nav}>
        {navItems.map(item => (
          <NavLink
            key={item.to}
            to={`${basePath}${item.to}`}
            end={item.to === ''}
            style={({ isActive }) => ({
              ...styles.navLink,
              ...(isActive ? styles.navLinkActive : {}),
            })}
          >
            <span style={styles.navIcon}>{item.icon}</span>
            {item.label}
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}

const styles: Record<string, React.CSSProperties> = {
  sidebar: {
    width: 240,
    minWidth: 240,
    height: '100vh',
    background: 'var(--surface)',
    borderRight: '1px solid var(--border)',
    display: 'flex',
    flexDirection: 'column',
    position: 'sticky',
    top: 0,
    overflowY: 'auto',
  },
  backLink: {
    display: 'block',
    padding: '16px 20px 12px',
    fontSize: 13,
    color: 'var(--text-muted)',
    textDecoration: 'none',
    fontWeight: 500,
    transition: 'color 0.15s',
  },
  caseHeader: {
    padding: '4px 20px 20px',
    borderBottom: '1px solid var(--border)',
  },
  caseName: {
    fontSize: 16,
    fontWeight: 700,
    color: 'var(--text)',
    lineHeight: 1.3,
  },
  nav: {
    display: 'flex',
    flexDirection: 'column',
    gap: 2,
    padding: '12px 8px',
    flex: 1,
  },
  navLink: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    padding: '10px 12px',
    fontSize: 14,
    fontWeight: 500,
    color: 'var(--text-muted)',
    textDecoration: 'none',
    borderRadius: 'var(--radius-sm)',
    transition: 'all 0.15s',
  },
  navLinkActive: {
    color: 'var(--accent)',
    background: 'var(--accent-light)',
    fontWeight: 600,
  },
  navIcon: {
    fontSize: 16,
    width: 20,
    textAlign: 'center' as const,
  },
}
