import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchJSON } from '../api/client'
import PipelineToggle, { type PipelineStep } from '../components/PipelineToggle'

/* ---------- helpers ---------- */

function toSlug(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
}

/* ---------- types ---------- */

interface ScanResult {
  [ext: string]: number
}

/* ---------- shared styles ---------- */

const btnBase: React.CSSProperties = {
  padding: '10px 24px',
  borderRadius: 8,
  fontSize: 14,
  fontWeight: 600,
  cursor: 'pointer',
  border: 'none',
  transition: 'all 0.15s ease',
}

const btnPrimary: React.CSSProperties = {
  ...btnBase,
  background: '#2563eb',
  color: '#fff',
}

const btnSecondary: React.CSSProperties = {
  ...btnBase,
  background: '#f3f4f6',
  color: '#374151',
}

const inputStyle: React.CSSProperties = {
  width: '100%',
  padding: '10px 14px',
  fontSize: 14,
  border: '1px solid #d1d5db',
  borderRadius: 8,
  outline: 'none',
  fontFamily: 'inherit',
  boxSizing: 'border-box',
}

const labelStyle: React.CSSProperties = {
  display: 'block',
  fontSize: 13,
  fontWeight: 600,
  color: '#374151',
  marginBottom: 6,
}

/* ---------- step indicators ---------- */

const STEP_LABELS = ['Directory', 'Name', 'Pipeline', 'Review']

function StepIndicator({ current }: { current: number }) {
  return (
    <div style={{ display: 'flex', gap: 8, marginBottom: 32 }}>
      {STEP_LABELS.map((label, i) => (
        <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1 }}>
          <div
            style={{
              width: 28,
              height: 28,
              borderRadius: 14,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 13,
              fontWeight: 700,
              background: i <= current ? '#2563eb' : '#e5e7eb',
              color: i <= current ? '#fff' : '#9ca3af',
              transition: 'all 0.2s ease',
            }}
          >
            {i < current ? '\u2713' : i + 1}
          </div>
          <span
            style={{
              fontSize: 13,
              fontWeight: i === current ? 600 : 400,
              color: i <= current ? '#111827' : '#9ca3af',
            }}
          >
            {label}
          </span>
          {i < STEP_LABELS.length - 1 && (
            <div
              style={{
                flex: 1,
                height: 2,
                background: i < current ? '#2563eb' : '#e5e7eb',
                borderRadius: 1,
                transition: 'background 0.2s ease',
              }}
            />
          )}
        </div>
      ))}
    </div>
  )
}

/* ---------- main wizard ---------- */

export default function NewCaseWizard() {
  const navigate = useNavigate()
  const [step, setStep] = useState(0)

  /* step 0: directory */
  const [dirPath, setDirPath] = useState('')
  const [scanResult, setScanResult] = useState<ScanResult | null>(null)
  const [scanning, setScanning] = useState(false)
  const [scanError, setScanError] = useState('')

  /* step 1: name */
  const [caseName, setCaseName] = useState('')
  const [description, setDescription] = useState('')

  /* step 2: pipeline */
  const [manifest, setManifest] = useState<PipelineStep[]>([])
  const [pipelineOverrides, setPipelineOverrides] = useState<Record<string, boolean>>({})
  const [manifestLoaded, setManifestLoaded] = useState(false)

  /* step 3: submitting */
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState('')

  const slug = toSlug(caseName)

  /* ---------- actions ---------- */

  async function handleScan() {
    setScanning(true)
    setScanError('')
    setScanResult(null)
    try {
      const result = await fetchJSON<ScanResult>('/cases/scan', {
        method: 'POST',
        body: JSON.stringify({ path: dirPath }),
      })
      setScanResult(result)
    } catch (e: unknown) {
      setScanError(e instanceof Error ? e.message : 'Scan failed')
    } finally {
      setScanning(false)
    }
  }

  async function loadManifest() {
    if (manifestLoaded) return
    try {
      const steps = await fetchJSON<PipelineStep[]>('/pipeline/manifest')
      setManifest(steps)
      const defaults: Record<string, boolean> = {}
      for (const s of steps) {
        defaults[s.id] = s.default_enabled
      }
      setPipelineOverrides(defaults)
      setManifestLoaded(true)
    } catch {
      /* manifest optional — page still works */
    }
  }

  function handleToggle(id: string, enabled: boolean) {
    const next = { ...pipelineOverrides, [id]: enabled }
    /* if disabling a step, disable anything that depends on it */
    if (!enabled) {
      for (const s of manifest) {
        if (s.depends_on.includes(id)) {
          next[s.id] = false
        }
      }
    }
    setPipelineOverrides(next)
  }

  function dependenciesMet(s: PipelineStep): boolean {
    return s.depends_on.every((dep) => pipelineOverrides[dep])
  }

  async function handleSubmit() {
    setSubmitting(true)
    setSubmitError('')
    try {
      await fetchJSON('/cases', {
        method: 'POST',
        body: JSON.stringify({
          name: caseName,
          slug,
          documents_dir: dirPath,
          description,
        }),
      })
      await fetchJSON(`/cases/${slug}/ingest/start`, {
        method: 'POST',
        body: JSON.stringify({ pipeline_overrides: pipelineOverrides }),
      })
      navigate(`/case/${slug}`)
    } catch (e: unknown) {
      setSubmitError(e instanceof Error ? e.message : 'Failed to create case')
      setSubmitting(false)
    }
  }

  /* ---------- navigation ---------- */

  function canAdvance(): boolean {
    switch (step) {
      case 0:
        return !!dirPath.trim() && scanResult !== null
      case 1:
        return !!caseName.trim() && !!slug
      case 2:
        return true
      default:
        return false
    }
  }

  function goNext() {
    if (step === 2) loadManifest() /* preload for review */
    if (step < 3) setStep(step + 1)
    if (step === 1) loadManifest()
  }

  /* ---------- render steps ---------- */

  function renderStep0() {
    return (
      <div>
        <h2 style={{ fontSize: 20, fontWeight: 700, color: '#111827', marginBottom: 4 }}>
          Where are your documents?
        </h2>
        <p style={{ fontSize: 14, color: '#6b7280', marginBottom: 24 }}>
          Enter the path to the directory containing your case files.
        </p>

        <label style={labelStyle}>Documents directory</label>
        <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
          <input
            style={{ ...inputStyle, flex: 1 }}
            placeholder="/path/to/documents"
            value={dirPath}
            onChange={(e) => {
              setDirPath(e.target.value)
              setScanResult(null)
              setScanError('')
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && dirPath.trim()) handleScan()
            }}
          />
          <button
            style={{
              ...btnPrimary,
              opacity: !dirPath.trim() || scanning ? 0.6 : 1,
            }}
            onClick={handleScan}
            disabled={!dirPath.trim() || scanning}
          >
            {scanning ? 'Scanning...' : 'Scan'}
          </button>
        </div>

        {scanError && (
          <div
            style={{
              padding: 12,
              background: '#fef2f2',
              border: '1px solid #fecaca',
              borderRadius: 8,
              color: '#dc2626',
              fontSize: 13,
            }}
          >
            {scanError}
          </div>
        )}

        {scanResult && (
          <div
            style={{
              padding: 16,
              background: '#f0fdf4',
              border: '1px solid #bbf7d0',
              borderRadius: 8,
            }}
          >
            <div style={{ fontWeight: 600, fontSize: 14, color: '#166534', marginBottom: 8 }}>
              Files found
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
              {Object.entries(scanResult).map(([ext, count]) => (
                <div
                  key={ext}
                  style={{
                    padding: '6px 12px',
                    background: '#fff',
                    borderRadius: 6,
                    fontSize: 13,
                    fontWeight: 500,
                    color: '#374151',
                    border: '1px solid #d1fae5',
                  }}
                >
                  {ext}: <strong>{count}</strong>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    )
  }

  function renderStep1() {
    return (
      <div>
        <h2 style={{ fontSize: 20, fontWeight: 700, color: '#111827', marginBottom: 4 }}>
          Name your case
        </h2>
        <p style={{ fontSize: 14, color: '#6b7280', marginBottom: 24 }}>
          Give your case a descriptive name. A URL-friendly slug will be generated automatically.
        </p>

        <div style={{ marginBottom: 20 }}>
          <label style={labelStyle}>Case name</label>
          <input
            style={inputStyle}
            placeholder="e.g. Epstein Document Review"
            value={caseName}
            onChange={(e) => setCaseName(e.target.value)}
          />
          {slug && (
            <div style={{ marginTop: 6, fontSize: 12, color: '#6b7280' }}>
              Slug: <code style={{ background: '#f3f4f6', padding: '2px 6px', borderRadius: 4 }}>{slug}</code>
            </div>
          )}
        </div>

        <div>
          <label style={labelStyle}>Description (optional)</label>
          <textarea
            style={{ ...inputStyle, minHeight: 80, resize: 'vertical' }}
            placeholder="Brief description of the case..."
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>
      </div>
    )
  }

  function renderStep2() {
    if (!manifestLoaded) {
      return (
        <div>
          <h2 style={{ fontSize: 20, fontWeight: 700, color: '#111827', marginBottom: 4 }}>
            Configure pipeline
          </h2>
          <p style={{ fontSize: 14, color: '#6b7280' }}>Loading pipeline steps...</p>
        </div>
      )
    }

    return (
      <div>
        <h2 style={{ fontSize: 20, fontWeight: 700, color: '#111827', marginBottom: 4 }}>
          Configure pipeline
        </h2>
        <p style={{ fontSize: 14, color: '#6b7280', marginBottom: 24 }}>
          Choose which processing steps to run on your documents.
        </p>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
            gap: 12,
          }}
        >
          {manifest.map((s) => (
            <PipelineToggle
              key={s.id}
              step={s}
              enabled={!!pipelineOverrides[s.id]}
              onToggle={handleToggle}
              dependenciesMet={dependenciesMet(s)}
            />
          ))}
        </div>

        {manifest.length === 0 && (
          <div
            style={{
              padding: 24,
              background: '#fffbeb',
              border: '1px solid #fde68a',
              borderRadius: 8,
              color: '#92400e',
              fontSize: 14,
            }}
          >
            No pipeline steps available. The server may not be running or the manifest is empty.
          </div>
        )}
      </div>
    )
  }

  function renderStep3() {
    const enabledSteps = manifest.filter((s) => pipelineOverrides[s.id])
    const totalFiles = scanResult ? Object.values(scanResult).reduce((a, b) => a + b, 0) : 0

    return (
      <div>
        <h2 style={{ fontSize: 20, fontWeight: 700, color: '#111827', marginBottom: 4 }}>
          Review &amp; start
        </h2>
        <p style={{ fontSize: 14, color: '#6b7280', marginBottom: 24 }}>
          Confirm your settings, then start ingestion.
        </p>

        <div
          style={{
            display: 'grid',
            gap: 16,
          }}
        >
          {/* Directory summary */}
          <div
            style={{
              padding: 16,
              background: '#fff',
              border: '1px solid #e5e7eb',
              borderRadius: 8,
            }}
          >
            <div style={{ fontSize: 12, fontWeight: 600, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>
              Directory
            </div>
            <div style={{ fontSize: 14, color: '#111827', fontFamily: 'monospace' }}>{dirPath}</div>
            <div style={{ fontSize: 13, color: '#6b7280', marginTop: 4 }}>
              {totalFiles} files total
              {scanResult && (
                <span>
                  {' '}({Object.entries(scanResult).map(([ext, n]) => `${n} ${ext}`).join(', ')})
                </span>
              )}
            </div>
          </div>

          {/* Case name summary */}
          <div
            style={{
              padding: 16,
              background: '#fff',
              border: '1px solid #e5e7eb',
              borderRadius: 8,
            }}
          >
            <div style={{ fontSize: 12, fontWeight: 600, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>
              Case
            </div>
            <div style={{ fontSize: 14, color: '#111827', fontWeight: 600 }}>{caseName}</div>
            <div style={{ fontSize: 13, color: '#6b7280', marginTop: 2 }}>
              Slug: <code style={{ background: '#f3f4f6', padding: '2px 6px', borderRadius: 4 }}>{slug}</code>
            </div>
            {description && (
              <div style={{ fontSize: 13, color: '#6b7280', marginTop: 4 }}>{description}</div>
            )}
          </div>

          {/* Pipeline summary */}
          <div
            style={{
              padding: 16,
              background: '#fff',
              border: '1px solid #e5e7eb',
              borderRadius: 8,
            }}
          >
            <div style={{ fontSize: 12, fontWeight: 600, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>
              Pipeline ({enabledSteps.length} step{enabledSteps.length !== 1 ? 's' : ''})
            </div>
            {enabledSteps.length > 0 ? (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {enabledSteps.map((s) => (
                  <span
                    key={s.id}
                    style={{
                      padding: '4px 10px',
                      background: '#f0fdf4',
                      border: '1px solid #bbf7d0',
                      borderRadius: 6,
                      fontSize: 13,
                      color: '#166534',
                      fontWeight: 500,
                    }}
                  >
                    {s.label}
                  </span>
                ))}
              </div>
            ) : (
              <div style={{ fontSize: 13, color: '#9ca3af' }}>No pipeline steps enabled</div>
            )}
          </div>
        </div>

        {submitError && (
          <div
            style={{
              marginTop: 16,
              padding: 12,
              background: '#fef2f2',
              border: '1px solid #fecaca',
              borderRadius: 8,
              color: '#dc2626',
              fontSize: 13,
            }}
          >
            {submitError}
          </div>
        )}
      </div>
    )
  }

  /* ---------- render ---------- */

  const stepRenderers = [renderStep0, renderStep1, renderStep2, renderStep3]

  return (
    <div
      style={{
        maxWidth: 720,
        margin: '0 auto',
        padding: 32,
        fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
      }}
    >
      <div style={{ marginBottom: 8 }}>
        <a
          href="/"
          onClick={(e) => {
            e.preventDefault()
            navigate('/')
          }}
          style={{ fontSize: 13, color: '#6b7280', textDecoration: 'none' }}
        >
          &larr; Back to cases
        </a>
      </div>

      <h1 style={{ fontSize: 24, fontWeight: 700, color: '#111827', marginBottom: 24 }}>
        New Case
      </h1>

      <StepIndicator current={step} />

      <div
        style={{
          background: '#fff',
          border: '1px solid #e5e7eb',
          borderRadius: 12,
          padding: 28,
          marginBottom: 24,
        }}
      >
        {stepRenderers[step]()}
      </div>

      {/* navigation buttons */}
      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
        <div>
          {step > 0 && (
            <button style={btnSecondary} onClick={() => setStep(step - 1)}>
              Back
            </button>
          )}
        </div>
        <div>
          {step < 3 ? (
            <button
              style={{ ...btnPrimary, opacity: canAdvance() ? 1 : 0.5 }}
              disabled={!canAdvance()}
              onClick={goNext}
            >
              Next
            </button>
          ) : (
            <button
              style={{
                ...btnPrimary,
                background: '#16a34a',
                opacity: submitting ? 0.6 : 1,
              }}
              disabled={submitting}
              onClick={handleSubmit}
            >
              {submitting ? 'Creating...' : 'Create Case & Start Ingestion'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
