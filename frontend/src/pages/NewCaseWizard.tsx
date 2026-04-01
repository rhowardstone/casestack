import { useState, useRef, useCallback, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchJSON } from '../api/client'
import PipelineToggle, { type PipelineStep } from '../components/PipelineToggle'

function toSlug(s: string) { return s.toLowerCase().trim().replace(/[^a-z0-9\s-]/g, '').replace(/\s+/g, '-').replace(/-+/g, '-') }
function fmtSize(b: number) { return b < 1024 ? `${b} B` : b < 1048576 ? `${(b / 1024).toFixed(0)} KB` : `${(b / 1048576).toFixed(1)} MB` }
function fmtEta(seconds: number): string { if (seconds < 60) return `${Math.ceil(seconds)}s`; const m = Math.floor(seconds / 60); const s = Math.ceil(seconds % 60); return `${m}m ${s}s` }

interface FileCounts { [k: string]: number }
interface AddedItem { name: string; kind?: 'file' | 'folder' | 'archive'; status: 'ok' | 'uploading' | 'error' | 'extracted'; detail?: string; size?: number; error?: string; files_extracted?: number; file_count?: number }

const btn: React.CSSProperties = { padding: '10px 24px', borderRadius: 8, fontSize: 14, fontWeight: 600, cursor: 'pointer', border: 'none', transition: 'all 0.15s ease' }
const btnB: React.CSSProperties = { ...btn, background: '#2563eb', color: '#fff' }
const btnG: React.CSSProperties = { ...btn, background: '#f3f4f6', color: '#374151' }
const inp: React.CSSProperties = { width: '100%', padding: '10px 14px', fontSize: 14, border: '1px solid #d1d5db', borderRadius: 8, outline: 'none', fontFamily: 'inherit', boxSizing: 'border-box' }

const STEPS = ['Documents', 'Name', 'Pipeline', 'Review']
function Steps({ n }: { n: number }) {
  return (
    <div style={{ display: 'flex', gap: 8, marginBottom: 32 }}>
      {STEPS.map((l, i) => (
        <div key={l} style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1 }}>
          <div style={{ width: 28, height: 28, borderRadius: 14, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13, fontWeight: 700, background: i <= n ? '#2563eb' : '#e5e7eb', color: i <= n ? '#fff' : '#9ca3af' }}>{i < n ? '\u2713' : i + 1}</div>
          <span style={{ fontSize: 13, fontWeight: i === n ? 600 : 400, color: i <= n ? '#111827' : '#9ca3af' }}>{l}</span>
          {i < 3 && <div style={{ flex: 1, height: 2, background: i < n ? '#2563eb' : '#e5e7eb', borderRadius: 1 }} />}
        </div>
      ))}
    </div>
  )
}

const CC: Record<string, { bg: string; fg: string; bd: string }> = {
  pdf: { bg: '#fff7ed', fg: '#c2410c', bd: '#fed7aa' }, media: { bg: '#fef3c7', fg: '#d97706', bd: '#fde68a' },
  text: { bg: '#ecfdf5', fg: '#059669', bd: '#a7f3d0' }, office: { bg: '#eff6ff', fg: '#2563eb', bd: '#bfdbfe' },
  image: { bg: '#fdf4ff', fg: '#9333ea', bd: '#e9d5ff' }, other: { bg: '#f3f4f6', fg: '#6b7280', bd: '#e5e7eb' },
}
function Badge({ k, n }: { k: string; n: number }) {
  if (k === 'total' || n === 0) return null
  const c = CC[k] || CC.other
  return <span style={{ padding: '3px 8px', background: c.bg, border: `1px solid ${c.bd}`, borderRadius: 5, fontSize: 12, fontWeight: 600, color: c.fg }}>{n} {k}</span>
}

/* --- read dropped folders recursively --- */
async function readEntries(entry: any): Promise<File[]> {
  if (entry.isFile) {
    return [await new Promise<File>((res) => entry.file(res))]
  }
  if (entry.isDirectory) {
    const reader = entry.createReader()
    const files: File[] = []
    let batch: any[]
    do {
      batch = await new Promise<any[]>((res, rej) => reader.readEntries(res, rej))
      for (const e of batch) files.push(...await readEntries(e))
    } while (batch.length > 0)
    return files
  }
  return []
}

interface DropResult { folders: { name: string; files: File[] }[]; files: File[] }

async function getDropped(dt: DataTransfer): Promise<DropResult> {
  const result: DropResult = { folders: [], files: [] }
  const items = Array.from(dt.items)
  const entries = items.map(i => (i as any).webkitGetAsEntry?.() || (i as any).getAsEntry?.()).filter(Boolean)
  if (entries.length > 0) {
    for (const entry of entries) {
      if (entry.isDirectory) {
        const files = await readEntries(entry)
        result.folders.push({ name: entry.name, files })
      } else if (entry.isFile) {
        const f = await new Promise<File>((res) => entry.file(res))
        result.files.push(f)
      }
    }
    return result
  }
  result.files = Array.from(dt.files)
  return result
}

/* ========== WIZARD ========== */

export default function NewCaseWizard() {
  const nav = useNavigate()
  const [step, setStep] = useState(0)

  const [, setSid] = useState('')
  const sidRef = useRef('')
  const [counts, setCounts] = useState<FileCounts | null>(null)
  const [items, setItems] = useState<AddedItem[]>([])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [drag, setDrag] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const folderRef = useRef<HTMLInputElement>(null)

  // Upload progress
  const [uploadProgress, setUploadProgress] = useState<{ loaded: number; total: number; startedAt: number; saving?: boolean } | null>(null)

  const [caseName, setCaseName] = useState('')
  const [desc, setDesc] = useState('')
  const [slugErr, setSlugErr] = useState('')
  const [manifest, setManifest] = useState<PipelineStep[]>([])
  const [overrides, setOverrides] = useState<Record<string, boolean>>({})
  const [mLoaded, setMLoaded] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [submitErr, setSubmitErr] = useState('')

  const slug = toSlug(caseName)
  const has = counts && (counts.total || 0) > 0

  // Validate slug uniqueness when name changes
  useEffect(() => {
    if (!slug) { setSlugErr(''); return }
    const timer = setTimeout(() => {
      fetch(`/api/cases/${slug}`).then(r => {
        if (r.ok) setSlugErr('A case with this name already exists')
        else setSlugErr('')
      }).catch(() => setSlugErr(''))
    }, 300)
    return () => clearTimeout(timer)
  }, [slug])

  async function getSid() {
    if (sidRef.current) return sidRef.current
    const r = await fetchJSON<{ session_id: string }>('/staging/create', { method: 'POST' })
    sidRef.current = r.session_id
    setSid(r.session_id)
    return r.session_id
  }

  async function uploadFiles(files: File[], folderName?: string) {
    if (!files.length) return
    setBusy(true); setErr('')
    const id = `${folderName || 'files'}-${Date.now()}`
    if (folderName) {
      setItems(p => [...p, { name: folderName, kind: 'folder', status: 'uploading', file_count: files.length, detail: id }])
    } else {
      setItems(p => [...p, ...files.map(f => ({ name: f.name, kind: 'file' as const, status: 'uploading' as const, size: f.size, detail: id }))])
    }
    try {
      const s = await getSid()
      const form = new FormData()
      for (const f of files) {
        const fname = folderName ? `${folderName}/${f.name}` : f.name
        form.append('files', f, fname)
      }

      // Use XMLHttpRequest for upload progress
      const data = await new Promise<{ uploads: AddedItem[]; counts: FileCounts }>((resolve, reject) => {
        const xhr = new XMLHttpRequest()
        const startTime = Date.now()
        xhr.upload.addEventListener('progress', (e) => {
          if (e.lengthComputable) {
            setUploadProgress({
              loaded: e.loaded,
              total: e.total,
              startedAt: startTime,
              saving: e.loaded >= e.total,
            })
          }
        })
        xhr.addEventListener('load', () => {
          setUploadProgress(null)
          if (xhr.status >= 200 && xhr.status < 300) {
            try { resolve(JSON.parse(xhr.responseText)) } catch { reject(new Error('Invalid response')) }
          } else {
            try { const e = JSON.parse(xhr.responseText); reject(new Error(e.detail || xhr.statusText)) }
            catch { reject(new Error(xhr.statusText)) }
          }
        })
        xhr.addEventListener('error', () => { setUploadProgress(null); reject(new Error('Upload failed')) })
        xhr.open('POST', `/api/staging/${s}/upload`)
        xhr.send(form)
      })

      if (folderName) {
        setItems(p => [...p.filter(u => u.detail !== id),
          { name: folderName, kind: 'folder', status: 'ok', file_count: data.uploads.length }])
      } else {
        setItems(p => [...p.filter(u => u.detail !== id), ...data.uploads.map(u => ({ ...u, kind: 'file' as const }))])
      }
      setCounts(data.counts)
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Upload failed')
      setItems(p => p.filter(u => u.detail !== id))
    } finally { setBusy(false); setUploadProgress(null) }
  }

  function removeItem(index: number) {
    setItems(p => p.filter((_, i) => i !== index))
  }

  const onOver = useCallback((e: React.DragEvent) => { e.preventDefault(); setDrag(true) }, [])
  const onLeave = useCallback((e: React.DragEvent) => { e.preventDefault(); setDrag(false) }, [])
  const onDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault(); setDrag(false)
    const drop = await getDropped(e.dataTransfer)
    // Serialize all uploads to avoid races
    if (drop.files.length) await uploadFiles(drop.files)
    for (const folder of drop.folders) {
      await uploadFiles(folder.files, folder.name)
    }
    // Refresh counts from server after all uploads
    if (sidRef.current) {
      try {
        const session = await fetchJSON<{ counts: FileCounts }>(`/staging/${sidRef.current}`)
        if (session.counts) setCounts(session.counts)
      } catch {}
    }
  }, [])

  async function loadManifest() {
    if (mLoaded) return
    try {
      const s = await fetchJSON<PipelineStep[]>('/pipeline/manifest')
      setManifest(s); const d: Record<string, boolean> = {}; for (const x of s) d[x.id] = x.default_enabled; setOverrides(d); setMLoaded(true)
    } catch {}
  }

  function toggle(id: string, on: boolean) {
    const n = { ...overrides, [id]: on }
    if (!on) for (const s of manifest) { if (s.depends_on.includes(id)) n[s.id] = false }
    setOverrides(n)
  }

  async function submit() {
    setSubmitting(true); setSubmitErr('')
    try {
      await fetchJSON('/cases', { method: 'POST', body: JSON.stringify({ name: caseName, slug, description: desc, staging_session: sidRef.current }) })
      await fetchJSON(`/cases/${slug}/ingest/start`, { method: 'POST', body: JSON.stringify({ pipeline_overrides: overrides }) })
      nav(`/case/${slug}`)
    } catch (e: unknown) { setSubmitErr(e instanceof Error ? e.message : 'Failed'); setSubmitting(false) }
  }

  function goNext() { if (step === 1) loadManifest(); if (step === 2) loadManifest(); if (step < 3) setStep(step + 1) }

  /* --- STEP 0 --- */
  function renderDocs() {
    return (
      <div>
        <h2 style={{ fontSize: 20, fontWeight: 700, color: '#111827', marginBottom: 4 }}>Add your documents</h2>
        <p style={{ fontSize: 14, color: '#6b7280', marginBottom: 20 }}>
          Drop files or folders here, or click to browse.
        </p>

        <input ref={fileRef} type="file" multiple style={{ display: 'none' }}
          onChange={e => { if (e.target.files?.length) { uploadFiles(Array.from(e.target.files)); e.target.value = '' } }}
        />
        {/* @ts-expect-error webkitdirectory is non-standard */}
        <input ref={folderRef} type="file" webkitdirectory="" style={{ display: 'none' }}
          onChange={e => {
            if (e.target.files?.length) {
              const files = Array.from(e.target.files)
              const folderName = files[0]?.webkitRelativePath?.split('/')[0] || 'folder'
              uploadFiles(files, folderName)
              e.target.value = ''
            }
          }}
        />

        <div
          onDragOver={onOver} onDragLeave={onLeave} onDrop={onDrop}
          onClick={() => folderRef.current?.click()}
          style={{
            border: `2px dashed ${drag ? '#2563eb' : '#d1d5db'}`, borderRadius: 12,
            padding: '48px 24px', textAlign: 'center', cursor: 'pointer',
            background: drag ? '#eff6ff' : '#fafafa', transition: 'all 0.15s ease', marginBottom: 8,
          }}
        >
          <div style={{ fontSize: 40, marginBottom: 8, lineHeight: 1 }}>{busy ? '\u23F3' : '\uD83D\uDCC1'}</div>
          <div style={{ fontSize: 15, fontWeight: 600, color: '#374151', marginBottom: 4 }}>
            {busy ? 'Uploading...' : 'Select a folder or drop files here'}
          </div>
          <div style={{ fontSize: 13, color: '#9ca3af' }}>
            Files, folders, or archives
          </div>
        </div>
        <div style={{ textAlign: 'center', marginBottom: 16 }}>
          <span onClick={() => fileRef.current?.click()}
            style={{ fontSize: 13, color: '#6b7280', cursor: 'pointer' }}>
            or <span style={{ color: '#2563eb', textDecoration: 'underline' }}>select individual files</span>
          </span>
        </div>

        {uploadProgress && (
          <div style={{ marginBottom: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 4 }}>
              <span style={{ color: '#374151', fontWeight: 500 }}>
                {uploadProgress.saving
                  ? 'Saving files to server...'
                  : `Uploading ${fmtSize(uploadProgress.loaded)} / ${fmtSize(uploadProgress.total)}`}
              </span>
              <span style={{ color: '#6b7280' }}>
                {!uploadProgress.saving && `${Math.round((uploadProgress.loaded / uploadProgress.total) * 100)}%`}
                {!uploadProgress.saving && uploadProgress.loaded > 0 && (() => {
                  const elapsed = (Date.now() - uploadProgress.startedAt) / 1000
                  const rate = uploadProgress.loaded / elapsed
                  const remaining = (uploadProgress.total - uploadProgress.loaded) / rate
                  return remaining > 1 ? ` — ${fmtEta(remaining)} remaining` : ''
                })()}
              </span>
            </div>
            <div style={{ width: '100%', height: 6, background: '#e5e7eb', borderRadius: 3, overflow: 'hidden' }}>
              <div style={{
                height: '100%',
                width: uploadProgress.saving ? '100%' : `${(uploadProgress.loaded / uploadProgress.total) * 100}%`,
                background: '#2563eb',
                borderRadius: 3,
                transition: uploadProgress.saving ? 'opacity 0.8s ease-in-out' : 'width 0.2s ease',
                animation: uploadProgress.saving ? 'pulse 1.2s ease-in-out infinite' : 'none',
              }} />
            </div>
          </div>
        )}

        {err && <div style={{ padding: 12, background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 8, color: '#dc2626', fontSize: 13, marginBottom: 12 }}>{err}</div>}

        {items.length > 0 && (
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>
              {items.length} item{items.length !== 1 ? 's' : ''} added
            </div>
            <div style={{ border: '1px solid #e5e7eb', borderRadius: 8, overflow: 'hidden', maxHeight: 260, overflowY: 'auto' }}>
              {items.map((it, i) => (
                <div key={`${it.name}-${i}`} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', background: it.status === 'error' ? '#fef2f2' : i % 2 === 0 ? '#fff' : '#f9fafb', borderBottom: i < items.length - 1 ? '1px solid #f3f4f6' : 'none', fontSize: 13 }}>
                  <span style={{ width: 18, textAlign: 'center', flexShrink: 0 }}>
                    {it.status === 'uploading' ? '\u23F3' : it.status === 'error' ? '\u274C' : it.kind === 'folder' ? '\uD83D\uDCC1' : it.status === 'extracted' ? '\uD83D\uDCE6' : '\u2705'}
                  </span>
                  <span style={{ flex: 1, color: '#374151', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{it.kind === 'folder' ? `${it.name}/` : it.name}</span>
                  {it.kind === 'folder' && it.file_count && <span style={{ color: '#6b7280', fontSize: 12, flexShrink: 0 }}>{it.file_count} file{it.file_count !== 1 ? 's' : ''}</span>}
                  {it.files_extracted && <span style={{ color: '#059669', fontSize: 12, flexShrink: 0 }}>{it.files_extracted} extracted</span>}
                  {it.error && <span style={{ color: '#dc2626', fontSize: 12 }}>{it.error}</span>}
                  {it.kind !== 'folder' && it.size && it.status === 'ok' && <span style={{ color: '#9ca3af', fontSize: 12, flexShrink: 0 }}>{fmtSize(it.size)}</span>}
                  {it.status !== 'uploading' && <span onClick={() => removeItem(i)}
                    style={{ width: 20, height: 20, display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: 10, cursor: 'pointer', color: '#9ca3af', flexShrink: 0, fontSize: 14, lineHeight: 1 }}
                    onMouseEnter={e => { e.currentTarget.style.color = '#dc2626'; e.currentTarget.style.background = '#fef2f2' }}
                    onMouseLeave={e => { e.currentTarget.style.color = '#9ca3af'; e.currentTarget.style.background = 'transparent' }}
                  >&times;</span>}
                </div>
              ))}
            </div>
          </div>
        )}

        {has && (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <span style={{ fontWeight: 600, fontSize: 14, color: '#166534' }}>{counts?.total || 0} files ready</span>
              {Object.entries(counts || {}).map(([k, v]) => <Badge key={k} k={k} n={v as number} />)}
            </div>
            <button style={btnB} onClick={() => setStep(1)}>Continue</button>
          </div>
        )}
      </div>
    )
  }

  /* --- STEP 1 --- */
  function renderName() {
    return (
      <div>
        <h2 style={{ fontSize: 20, fontWeight: 700, color: '#111827', marginBottom: 4 }}>Name your case</h2>
        <p style={{ fontSize: 14, color: '#6b7280', marginBottom: 24 }}>Give your case a descriptive name.</p>
        <div style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#374151', marginBottom: 6 }}>Case name</div>
          <input style={{ ...inp, borderColor: slugErr ? '#dc2626' : '#d1d5db' }} placeholder="e.g. FOIA Document Review" value={caseName} onChange={e => setCaseName(e.target.value)} autoFocus />
          {slug && <div style={{ marginTop: 6, fontSize: 12, color: slugErr ? '#dc2626' : '#6b7280' }}>
            Slug: <code style={{ background: slugErr ? '#fef2f2' : '#f3f4f6', padding: '2px 6px', borderRadius: 4 }}>{slug}</code>
            {slugErr && <span style={{ marginLeft: 8 }}>{slugErr}</span>}
          </div>}
        </div>
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#374151', marginBottom: 6 }}>Description (optional)</div>
          <textarea style={{ ...inp, minHeight: 80, resize: 'vertical' }} placeholder="Brief description..." value={desc} onChange={e => setDesc(e.target.value)} />
        </div>
      </div>
    )
  }

  /* --- STEP 2 --- */
  function renderPipeline() {
    if (!mLoaded) return <div><h2 style={{ fontSize: 20, fontWeight: 700, color: '#111827' }}>Configure pipeline</h2><p style={{ fontSize: 14, color: '#6b7280' }}>Loading...</p></div>
    return (
      <div>
        <h2 style={{ fontSize: 20, fontWeight: 700, color: '#111827', marginBottom: 4 }}>Configure pipeline</h2>
        <p style={{ fontSize: 14, color: '#6b7280', marginBottom: 24 }}>Choose which processing steps to run.</p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 }}>
          {manifest.map(s => <PipelineToggle key={s.id} step={s} enabled={!!overrides[s.id]} onToggle={toggle} dependenciesMet={s.depends_on.every(d => overrides[d])} />)}
        </div>
      </div>
    )
  }

  /* --- STEP 3 --- */
  function renderReview() {
    const en = manifest.filter(s => overrides[s.id])
    return (
      <div>
        <h2 style={{ fontSize: 20, fontWeight: 700, color: '#111827', marginBottom: 4 }}>Review &amp; start</h2>
        <p style={{ fontSize: 14, color: '#6b7280', marginBottom: 24 }}>Confirm and start ingestion.</p>
        <div style={{ display: 'grid', gap: 16 }}>
          <div style={{ padding: 16, background: '#fff', border: '1px solid #e5e7eb', borderRadius: 8 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>Documents</div>
            <div style={{ fontSize: 13, color: '#111827', marginBottom: 4 }}>{items.filter(u => u.status !== 'error').length} items uploaded</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
              <span style={{ fontSize: 13, color: '#6b7280' }}>{counts?.total || 0} files</span>
              {Object.entries(counts || {}).map(([k, v]) => <Badge key={k} k={k} n={v as number} />)}
            </div>
          </div>
          <div style={{ padding: 16, background: '#fff', border: '1px solid #e5e7eb', borderRadius: 8 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>Case</div>
            <div style={{ fontSize: 14, color: '#111827', fontWeight: 600 }}>{caseName}</div>
            <div style={{ fontSize: 13, color: '#6b7280', marginTop: 2 }}>Slug: <code style={{ background: '#f3f4f6', padding: '2px 6px', borderRadius: 4 }}>{slug}</code></div>
            {desc && <div style={{ fontSize: 13, color: '#6b7280', marginTop: 4 }}>{desc}</div>}
          </div>
          <div style={{ padding: 16, background: '#fff', border: '1px solid #e5e7eb', borderRadius: 8 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>Pipeline ({en.length} steps)</div>
            {en.length > 0 ? (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>{en.map(s => <span key={s.id} style={{ padding: '4px 10px', background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 6, fontSize: 13, color: '#166534', fontWeight: 500 }}>{s.label}</span>)}</div>
            ) : <div style={{ fontSize: 13, color: '#9ca3af' }}>No steps enabled</div>}
          </div>
        </div>
        {submitErr && <div style={{ marginTop: 16, padding: 12, background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 8, color: '#dc2626', fontSize: 13 }}>{submitErr}</div>}
      </div>
    )
  }

  const R = [renderDocs, renderName, renderPipeline, renderReview]
  return (
    <div style={{ maxWidth: 720, margin: '0 auto', padding: 32, fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" }}>
      <div style={{ marginBottom: 8 }}><a href="/" onClick={e => { e.preventDefault(); nav('/') }} style={{ fontSize: 13, color: '#6b7280', textDecoration: 'none' }}>&larr; Back to cases</a></div>
      <h1 style={{ fontSize: 24, fontWeight: 700, color: '#111827', marginBottom: 24 }}>New Case</h1>
      <Steps n={step} />
      <div style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: 12, padding: 28, marginBottom: 24 }}>{R[step]()}</div>
      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
        <div>{step > 0 && <button style={btnG} onClick={() => setStep(step - 1)}>Back</button>}</div>
        <div>
          {step > 0 && step < 3 ? <button style={{ ...btnB, opacity: step === 1 ? (caseName.trim() && !slugErr ? 1 : 0.5) : 1 }} disabled={step === 1 && (!caseName.trim() || !!slugErr)} onClick={goNext}>Next</button>
          : step === 3 ? <button style={{ ...btnB, background: '#16a34a', opacity: submitting ? 0.6 : 1 }} disabled={submitting} onClick={submit}>{submitting ? 'Creating...' : 'Create Case & Start Ingestion'}</button>
          : null}
        </div>
      </div>
    </div>
  )
}
