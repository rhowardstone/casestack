import React from 'react'
import { NavLink, Link } from 'react-router-dom'

interface Props {
  slug: string
  caseName: string
}

const navItems: { to: string; label: string; icon: React.ReactNode }[] = [
  {
    to: '', label: 'Dashboard',
    icon: <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" style={{ display: 'block' }}><path d="M8.707 1.5a1 1 0 0 0-1.414 0L.646 8.146a.5.5 0 0 0 .708.708L2 8.207V13.5A1.5 1.5 0 0 0 3.5 15h2a.5.5 0 0 0 .5-.5V11h4v3.5a.5.5 0 0 0 .5.5h2a1.5 1.5 0 0 0 1.5-1.5V8.207l.646.647a.5.5 0 0 0 .708-.708L13 5.793V2.5a.5.5 0 0 0-.5-.5h-1a.5.5 0 0 0-.5.5v1.293L8.707 1.5Z"/></svg>,
  },
  {
    to: '/search', label: 'Search',
    icon: <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" style={{ display: 'block' }}><path d="M11.742 10.344a6.5 6.5 0 1 0-1.397 1.398h-.001q.044.06.098.115l3.85 3.85a1 1 0 0 0 1.415-1.414l-3.85-3.85a1 1 0 0 0-.115-.099ZM12 6.5a5.5 5.5 0 1 1-11 0 5.5 5.5 0 0 1 11 0Z"/></svg>,
  },
  {
    to: '/entities', label: 'Entities',
    icon: <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" style={{ display: 'block' }}><path d="M7 14s-1 0-1-1 1-4 5-4 5 3 5 4-1 1-1 1zm4-6a3 3 0 1 0 0-6 3 3 0 0 0 0 6m-5.784 6A2.24 2.24 0 0 1 5 13c0-1.355.68-2.75 1.936-3.72A6.3 6.3 0 0 0 5 9c-4 0-5 3-5 4s1 1 1 1zM4.5 8a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5"/></svg>,
  },
  {
    to: '/images', label: 'Images',
    icon: <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" style={{ display: 'block' }}><path d="M6.002 5.5a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0"/><path d="M1.5 2A1.5 1.5 0 0 0 0 3.5v9A1.5 1.5 0 0 0 1.5 14h13a1.5 1.5 0 0 0 1.5-1.5v-9A1.5 1.5 0 0 0 14.5 2zm13 1a.5.5 0 0 1 .5.5v6l-3.775-1.947a.5.5 0 0 0-.577.093l-3.71 3.71-2.66-1.772a.5.5 0 0 0-.63.062L1.002 12v.54L1 12.5v-9a.5.5 0 0 1 .5-.5z"/></svg>,
  },
  {
    to: '/transcripts', label: 'Transcripts',
    icon: <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" style={{ display: 'block' }}><path d="M5 3a3 3 0 0 1 6 0v5a3 3 0 0 1-6 0z"/><path d="M3.5 6.5A.5.5 0 0 1 4 7v1a4 4 0 0 0 8 0V7a.5.5 0 0 1 1 0v1a5 5 0 0 1-4.5 4.975V15h3a.5.5 0 0 1 0 1h-7a.5.5 0 0 1 0-1h3v-2.025A5 5 0 0 1 3 8V7a.5.5 0 0 1 .5-.5"/></svg>,
  },
  {
    to: '/map', label: 'Map',
    icon: <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" style={{ display: 'block' }}><path d="M8 16s6-5.686 6-10A6 6 0 0 0 2 6c0 4.314 6 10 6 10m0-7a3 3 0 1 1 0-6 3 3 0 0 1 0 6"/></svg>,
  },
  {
    to: '/ask', label: 'Ask AI',
    icon: <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" style={{ display: 'block' }}><path d="M16 8c0 3.866-3.582 7-8 7a9 9 0 0 1-2.347-.306c-.584.297-1.925.864-4.181 1.234-.2.032-.352-.176-.273-.362.354-.836.674-1.95.77-2.966C.744 11.37 0 9.76 0 8c0-3.866 3.582-7 8-7s8 3.134 8 7M5 8a1 1 0 1 0-2 0 1 1 0 0 0 2 0m4 0a1 1 0 1 0-2 0 1 1 0 0 0 2 0m3 0a1 1 0 1 0-2 0 1 1 0 0 0 2 0"/></svg>,
  },
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

      <div style={styles.bottomNav}>
        <NavLink
          to={`${basePath}/settings`}
          style={({ isActive }) => ({
            ...styles.navLink,
            ...(isActive ? styles.navLinkActive : {}),
          })}
        >
          <span style={styles.navIcon}>
            <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" style={{ display: 'block' }}>
              <path fillRule="evenodd" d="M7.429 1.525a6.593 6.593 0 011.142 0c.036.003.108.036.137.146l.289 1.105c.147.56.55.967.997 1.189.174.086.341.183.501.29.417.278.97.423 1.53.27l1.102-.303c.11-.03.175.016.195.046.219.31.41.641.573.989.014.031.022.11-.059.19l-.815.806c-.411.406-.562.957-.53 1.456a4.588 4.588 0 010 .582c-.032.499.119 1.05.53 1.456l.815.806c.08.08.073.159.059.19a6.494 6.494 0 01-.573.989c-.02.03-.085.076-.195.046l-1.102-.303c-.56-.153-1.113-.008-1.53.27a4.506 4.506 0 01-.501.29c-.447.222-.85.629-.997 1.189l-.289 1.105c-.029.11-.101.143-.137.146a6.613 6.613 0 01-1.142 0c-.036-.003-.108-.037-.137-.146l-.289-1.105c-.147-.56-.55-.967-.997-1.189a4.502 4.502 0 01-.501-.29c-.417-.278-.97-.423-1.53-.27l-1.102.303c-.11.03-.175-.016-.195-.046a6.492 6.492 0 01-.573-.989c-.014-.031-.022-.11.059-.19l.815-.806c.411-.406.562-.957.53-1.456a4.587 4.587 0 010-.582c.032-.499-.119-1.05-.53-1.456l-.815-.806c-.08-.08-.073-.159-.059-.19a6.44 6.44 0 01.573-.99c.02-.029.085-.075.195-.045l1.102.303c.56.153 1.113.008 1.53-.27.16-.107.327-.204.5-.29.449-.222.851-.628.998-1.189l.289-1.105c.029-.11.101-.143.137-.146zM8 0c-.236 0-.47.01-.701.03-.743.065-1.29.615-1.458 1.261l-.29 1.106c-.017.066-.078.158-.211.224a5.994 5.994 0 00-.668.386c-.123.082-.233.117-.3.1L3.27 2.801c-.657-.18-1.375.026-1.78.653a7.998 7.998 0 00-.746 1.29c-.3.663-.097 1.39.408 1.89l.815.806c.05.048.098.147.088.294a6.084 6.084 0 000 .532c.01.147-.038.246-.088.294l-.815.806c-.505.5-.708 1.227-.408 1.89.199.44.429.86.746 1.29.404.627 1.122.833 1.78.653l1.102-.303c.067-.018.177.018.3.1.216.144.44.272.668.386.133.066.194.158.212.224l.289 1.106c.169.646.715 1.196 1.458 1.26a8.094 8.094 0 001.402 0c.743-.064 1.29-.614 1.458-1.26l.29-1.106c.017-.066.078-.158.211-.224.228-.114.453-.242.668-.386.123-.082.233-.117.3-.1l1.102.303c.657.18 1.375-.026 1.78-.653.317-.43.547-.85.746-1.29.3-.663.097-1.39-.408-1.89l-.815-.806c-.05-.048-.098-.147-.088-.294a6.1 6.1 0 000-.532c-.01-.147.039-.246.088-.294l.815-.806c.505-.5.708-1.227.408-1.89a7.992 7.992 0 00-.746-1.29c-.404-.627-1.122-.833-1.78-.653l-1.102.303c-.067.018-.177-.018-.3-.1a5.99 5.99 0 00-.668-.386c-.133-.066-.194-.158-.212-.224L10.16 1.29C9.99.645 9.444.095 8.701.031A8.094 8.094 0 008 0zm0 5.5a2.5 2.5 0 100 5 2.5 2.5 0 000-5zM6.5 8a1.5 1.5 0 113 0 1.5 1.5 0 01-3 0z" />
            </svg>
          </span>
          Settings
        </NavLink>
      </div>
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
    width: 20,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  },
  bottomNav: {
    padding: '8px 8px 16px',
    borderTop: '1px solid var(--border)',
    marginTop: 'auto',
  },
}
