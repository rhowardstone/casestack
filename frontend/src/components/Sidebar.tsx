import React, { useState, useEffect } from 'react'
import { NavLink, Link } from 'react-router-dom'

export const TOP_NAV_HEIGHT = 48

type ScreenSize = 'mobile' | 'tablet' | 'desktop'

function useScreenSize(): ScreenSize {
  const [size, setSize] = useState<ScreenSize>(() => {
    const w = window.innerWidth
    return w < 768 ? 'mobile' : w < 1100 ? 'tablet' : 'desktop'
  })
  useEffect(() => {
    const handle = () => {
      const w = window.innerWidth
      setSize(w < 768 ? 'mobile' : w < 1100 ? 'tablet' : 'desktop')
    }
    window.addEventListener('resize', handle)
    return () => window.removeEventListener('resize', handle)
  }, [])
  return size
}

interface Props {
  slug: string
  caseName: string
}

const navItems = [
  {
    to: '', label: 'Dashboard',
    icon: <svg width="15" height="15" viewBox="0 0 16 16" fill="currentColor" style={{ display: 'block' }}><path d="M8.707 1.5a1 1 0 0 0-1.414 0L.646 8.146a.5.5 0 0 0 .708.708L2 8.207V13.5A1.5 1.5 0 0 0 3.5 15h2a.5.5 0 0 0 .5-.5V11h4v3.5a.5.5 0 0 0 .5.5h2a1.5 1.5 0 0 0 1.5-1.5V8.207l.646.647a.5.5 0 0 0 .708-.708L13 5.793V2.5a.5.5 0 0 0-.5-.5h-1a.5.5 0 0 0-.5.5v1.293L8.707 1.5Z"/></svg>,
  },
  {
    to: '/documents', label: 'Browse',
    icon: <svg width="15" height="15" viewBox="0 0 16 16" fill="currentColor" style={{ display: 'block' }}><path d="M4 0h5.293A1 1 0 0 1 10 .293L13.707 4a1 1 0 0 1 .293.707V14a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V2a2 2 0 0 1 2-2m5.5 1.5v2a1 1 0 0 0 1 1h2zM4.5 8a.5.5 0 0 0 0 1h7a.5.5 0 0 0 0-1zm0 2.5a.5.5 0 0 0 0 1h7a.5.5 0 0 0 0-1zm0 2.5a.5.5 0 0 0 0 1h4a.5.5 0 0 0 0-1z"/></svg>,
  },
  {
    to: '/search', label: 'Search',
    icon: <svg width="15" height="15" viewBox="0 0 16 16" fill="currentColor" style={{ display: 'block' }}><path d="M11.742 10.344a6.5 6.5 0 1 0-1.397 1.398h-.001q.044.06.098.115l3.85 3.85a1 1 0 0 0 1.415-1.414l-3.85-3.85a1 1 0 0 0-.115-.099ZM12 6.5a5.5 5.5 0 1 1-11 0 5.5 5.5 0 0 1 11 0Z"/></svg>,
  },
  {
    to: '/entities', label: 'Entities',
    icon: <svg width="15" height="15" viewBox="0 0 16 16" fill="currentColor" style={{ display: 'block' }}><path d="M7 14s-1 0-1-1 1-4 5-4 5 3 5 4-1 1-1 1zm4-6a3 3 0 1 0 0-6 3 3 0 0 0 0 6m-5.784 6A2.24 2.24 0 0 1 5 13c0-1.355.68-2.75 1.936-3.72A6.3 6.3 0 0 0 5 9c-4 0-5 3-5 4s1 1 1 1zM4.5 8a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5"/></svg>,
  },
  {
    to: '/images', label: 'Images',
    icon: <svg width="15" height="15" viewBox="0 0 16 16" fill="currentColor" style={{ display: 'block' }}><path d="M6.002 5.5a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0"/><path d="M1.5 2A1.5 1.5 0 0 0 0 3.5v9A1.5 1.5 0 0 0 1.5 14h13a1.5 1.5 0 0 0 1.5-1.5v-9A1.5 1.5 0 0 0 14.5 2zm13 1a.5.5 0 0 1 .5.5v6l-3.775-1.947a.5.5 0 0 0-.577.093l-3.71 3.71-2.66-1.772a.5.5 0 0 0-.63.062L1.002 12v.54L1 12.5v-9a.5.5 0 0 1 .5-.5z"/></svg>,
  },
  {
    to: '/transcripts', label: 'Transcripts',
    icon: <svg width="15" height="15" viewBox="0 0 16 16" fill="currentColor" style={{ display: 'block' }}><path d="M5 3a3 3 0 0 1 6 0v5a3 3 0 0 1-6 0z"/><path d="M3.5 6.5A.5.5 0 0 1 4 7v1a4 4 0 0 0 8 0V7a.5.5 0 0 1 1 0v1a5 5 0 0 1-4.5 4.975V15h3a.5.5 0 0 1 0 1h-7a.5.5 0 0 1 0-1h3v-2.025A5 5 0 0 1 3 8V7a.5.5 0 0 1 .5-.5"/></svg>,
  },
  {
    to: '/map', label: 'Map',
    icon: <svg width="15" height="15" viewBox="0 0 16 16" fill="currentColor" style={{ display: 'block' }}><path d="M8 16s6-5.686 6-10A6 6 0 0 0 2 6c0 4.314 6 10 6 10m0-7a3 3 0 1 1 0-6 3 3 0 0 1 0 6"/></svg>,
  },
  {
    to: '/ask', label: 'Ask AI',
    icon: <svg width="15" height="15" viewBox="0 0 16 16" fill="currentColor" style={{ display: 'block' }}><path d="M16 8c0 3.866-3.582 7-8 7a9 9 0 0 1-2.347-.306c-.584.297-1.925.864-4.181 1.234-.2.032-.352-.176-.273-.362.354-.836.674-1.95.77-2.966C.744 11.37 0 9.76 0 8c0-3.866 3.582-7 8-7s8 3.134 8 7M5 8a1 1 0 1 0-2 0 1 1 0 0 0 2 0m4 0a1 1 0 1 0-2 0 1 1 0 0 0 2 0m3 0a1 1 0 1 0-2 0 1 1 0 0 0 2 0"/></svg>,
  },
]

const SettingsIcon = () => (
  <svg width="15" height="15" viewBox="0 0 16 16" fill="currentColor" style={{ display: 'block' }}>
    <path fillRule="evenodd" d="M7.429 1.525a6.593 6.593 0 011.142 0c.036.003.108.036.137.146l.289 1.105c.147.56.55.967.997 1.189.174.086.341.183.501.29.417.278.97.423 1.53.27l1.102-.303c.11-.03.175.016.195.046.219.31.41.641.573.989.014.031.022.11-.059.19l-.815.806c-.411.406-.562.957-.53 1.456a4.588 4.588 0 010 .582c-.032.499.119 1.05.53 1.456l.815.806c.08.08.073.159.059.19a6.494 6.494 0 01-.573.989c-.02.03-.085.076-.195.046l-1.102-.303c-.56-.153-1.113-.008-1.53.27a4.506 4.506 0 01-.501.29c-.447.222-.85.629-.997 1.189l-.289 1.105c-.029.11-.101.143-.137.146a6.613 6.613 0 01-1.142 0c-.036-.003-.108-.037-.137-.146l-.289-1.105c-.147-.56-.55-.967-.997-1.189a4.502 4.502 0 01-.501-.29c-.417-.278-.97-.423-1.53-.27l-1.102.303c-.11.03-.175-.016-.195-.046a6.492 6.492 0 01-.573-.989c-.014-.031-.022-.11.059-.19l.815-.806c.411-.406.562-.957.53-1.456a4.587 4.587 0 010-.582c.032-.499-.119-1.05-.53-1.456l-.815-.806c-.08-.08-.073-.159-.059-.19a6.44 6.44 0 01.573-.99c.02-.029.085-.075.195-.045l1.102.303c.56.153 1.113.008 1.53-.27.16-.107.327-.204.5-.29.449-.222.851-.628.998-1.189l.289-1.105c.029-.11.101-.143.137-.146zM8 0c-.236 0-.47.01-.701.03-.743.065-1.29.615-1.458 1.261l-.29 1.106c-.017.066-.078.158-.211.224a5.994 5.994 0 00-.668.386c-.123.082-.233.117-.3.1L3.27 2.801c-.657-.18-1.375.026-1.78.653a7.998 7.998 0 00-.746 1.29c-.3.663-.097 1.39.408 1.89l.815.806c.05.048.098.147.088.294a6.084 6.084 0 000 .532c.01.147-.038.246-.088.294l-.815.806c-.505.5-.708 1.227-.408 1.89.199.44.429.86.746 1.29.404.627 1.122.833 1.78.653l1.102-.303c.067-.018.177.018.3.1.216.144.44.272.668.386.133.066.194.158.212.224l.289 1.106c.169.646.715 1.196 1.458 1.26a8.094 8.094 0 001.402 0c.743-.064 1.29-.614 1.458-1.26l.29-1.106c.017-.066.078-.158.211-.224.228-.114.453-.242.668-.386.123-.082.233-.117.3-.1l1.102.303c.657.18 1.375-.026 1.78-.653.317-.43.547-.85.746-1.29.3-.663.097-1.39-.408-1.89l-.815-.806c-.05-.048-.098-.147-.088-.294a6.1 6.1 0 000-.532c-.01-.147.039-.246.088-.294l.815-.806c.505-.5.708-1.227.408-1.89a7.992 7.992 0 00-.746-1.29c-.404-.627-1.122-.833-1.78-.653l-1.102.303c-.067.018-.177-.018-.3-.1a5.99 5.99 0 00-.668-.386c-.133-.066-.194-.158-.212-.224L10.16 1.29C9.99.645 9.444.095 8.701.031A8.094 8.094 0 008 0zm0 5.5a2.5 2.5 0 100 5 2.5 2.5 0 000-5zM6.5 8a1.5 1.5 0 113 0 1.5 1.5 0 01-3 0z" />
  </svg>
)

const HamburgerIcon = () => (
  <svg width="18" height="18" viewBox="0 0 16 16" fill="currentColor">
    <path fillRule="evenodd" d="M2.5 12a.5.5 0 0 1 .5-.5h10a.5.5 0 0 1 0 1H3a.5.5 0 0 1-.5-.5zm0-4a.5.5 0 0 1 .5-.5h10a.5.5 0 0 1 0 1H3a.5.5 0 0 1-.5-.5zm0-4a.5.5 0 0 1 .5-.5h10a.5.5 0 0 1 0 1H3a.5.5 0 0 1-.5-.5z"/>
  </svg>
)

export default function Sidebar({ slug, caseName }: Props) {
  const basePath = `/case/${slug}`
  const screen = useScreenSize()
  const [menuOpen, setMenuOpen] = useState(false)

  const allNavItems = [
    ...navItems,
    {
      to: '/settings',
      label: 'Settings',
      icon: <SettingsIcon />,
    },
  ]

  const navLinkStyle = (isActive: boolean, screen: ScreenSize): React.CSSProperties => ({
    display: 'flex',
    alignItems: 'center',
    gap: screen === 'desktop' ? 5 : 0,
    padding: screen === 'desktop' ? '5px 8px' : '6px 8px',
    fontSize: 13,
    fontWeight: 500,
    color: isActive ? 'var(--accent)' : 'var(--text-muted)',
    background: isActive ? 'var(--accent-light, rgba(59,130,246,0.1))' : 'transparent',
    textDecoration: 'none',
    borderRadius: 6,
    whiteSpace: 'nowrap' as const,
    transition: 'color 0.15s, background 0.15s',
  })

  return (
    <>
      <nav style={styles.topNav}>
        {/* Left: back + case name */}
        <div style={styles.left}>
          <Link to="/" style={styles.backLink} title="All Cases">
            <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path fillRule="evenodd" d="M15 8a.5.5 0 0 0-.5-.5H2.707l3.147-3.146a.5.5 0 1 0-.708-.708l-4 4a.5.5 0 0 0 0 .708l4 4a.5.5 0 0 0 .708-.708L2.707 8.5H14.5A.5.5 0 0 0 15 8z"/></svg>
          </Link>
          <div style={styles.titleDivider} />
          <span style={styles.caseName} title={caseName}>{caseName || 'Loading…'}</span>
        </div>

        {/* Center: nav items (desktop + tablet) */}
        {screen !== 'mobile' && (
          <div style={styles.center}>
            {allNavItems.map(item => (
              <NavLink
                key={item.to}
                to={`${basePath}${item.to}`}
                end={item.to === ''}
                title={screen === 'tablet' ? item.label : undefined}
                style={({ isActive }) => navLinkStyle(isActive, screen)}
              >
                {item.icon}
                {screen === 'desktop' && item.label}
              </NavLink>
            ))}
          </div>
        )}

        {/* Mobile: hamburger */}
        {screen === 'mobile' && (
          <button
            style={styles.hamburger}
            onClick={() => setMenuOpen(p => !p)}
            aria-label="Navigation menu"
          >
            <HamburgerIcon />
          </button>
        )}
      </nav>

      {/* Mobile dropdown menu */}
      {menuOpen && screen === 'mobile' && (
        <>
          <div style={styles.mobileBackdrop} onClick={() => setMenuOpen(false)} />
          <div style={styles.mobileMenu}>
            {allNavItems.map(item => (
              <NavLink
                key={item.to}
                to={`${basePath}${item.to}`}
                end={item.to === ''}
                onClick={() => setMenuOpen(false)}
                style={({ isActive }) => ({
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  padding: '11px 16px',
                  fontSize: 14,
                  fontWeight: 500,
                  color: isActive ? 'var(--accent)' : 'var(--text)',
                  background: isActive ? 'var(--accent-light, rgba(59,130,246,0.08))' : 'transparent',
                  textDecoration: 'none',
                  borderBottom: '1px solid var(--border)',
                })}
              >
                {item.icon}
                {item.label}
              </NavLink>
            ))}
          </div>
        </>
      )}
    </>
  )
}

const styles: Record<string, React.CSSProperties> = {
  topNav: {
    height: TOP_NAV_HEIGHT,
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '0 12px',
    borderBottom: '1px solid var(--border)',
    background: 'var(--surface)',
    flexShrink: 0,
    position: 'relative',
    zIndex: 10,
  },
  left: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    flexShrink: 0,
    minWidth: 0,
  },
  backLink: {
    display: 'flex',
    alignItems: 'center',
    color: 'var(--text-muted)',
    textDecoration: 'none',
    padding: '4px',
    borderRadius: 4,
    flexShrink: 0,
    transition: 'color 0.15s',
  },
  titleDivider: {
    width: 1,
    height: 16,
    background: 'var(--border)',
    flexShrink: 0,
  },
  caseName: {
    fontSize: 14,
    fontWeight: 700,
    color: 'var(--text)',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    maxWidth: 220,
  },
  center: {
    display: 'flex',
    alignItems: 'center',
    gap: 2,
    flex: 1,
    justifyContent: 'center',
    overflow: 'hidden',
  },
  hamburger: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    background: 'none',
    border: 'none',
    cursor: 'pointer',
    color: 'var(--text-muted)',
    padding: '6px',
    borderRadius: 6,
    marginLeft: 'auto',
  },
  mobileBackdrop: {
    position: 'fixed',
    inset: 0,
    zIndex: 49,
  },
  mobileMenu: {
    position: 'absolute',
    top: TOP_NAV_HEIGHT,
    right: 0,
    left: 0,
    background: 'var(--surface)',
    borderBottom: '1px solid var(--border)',
    zIndex: 50,
    boxShadow: '0 4px 12px rgba(0,0,0,0.08)',
  },
}
