import { useEffect, useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { fetchJSON } from '../api/client'

interface CaseData {
  slug: string
  name: string
  description: string
  document_count: number
}

interface PipelineStep {
  name: string
  enabled: boolean
  description?: string
}

interface PipelineConfig {
  steps: PipelineStep[]
}

export default function CaseSettings() {
  const { slug } = useParams<{ slug: string }>()
  const navigate = useNavigate()

  const [caseData, setCaseData] = useState<CaseData | null>(null)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [pipeline, setPipeline] = useState<PipelineStep[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')
  const [rerunning, setRerunning] = useState(false)
  const [showDeleteDialog, setShowDeleteDialog] = useState(false)
  const [deleteConfirmText, setDeleteConfirmText] = useState('')
  const [deleting, setDeleting] = useState(false)

  useEffect(() => {
    if (!slug) return

    setLoading(true)
    Promise.all([
      fetchJSON<CaseData>(`/cases/${slug}`),
      fetchJSON<PipelineConfig>(`/cases/${slug}/pipeline`).catch(() => ({ steps: [] })),
    ])
      .then(([data, pipelineData]) => {
        setCaseData(data)
        setName(data.name)
        setDescription(data.description || '')
        setPipeline(pipelineData.steps || [])
      })
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }, [slug])

  const handleSave = useCallback(async () => {
    if (!slug || saving) return
    setSaving(true)
    setSaved(false)
    try {
      await fetchJSON(`/cases/${slug}`, {
        method: 'PUT',
        body: JSON.stringify({ name, description }),
      })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save')
    } finally {
      setSaving(false)
    }
  }, [slug, name, description, saving])

  const handleRerunIngest = useCallback(async () => {
    if (!slug || rerunning) return
    setRerunning(true)
    try {
      await fetchJSON(`/cases/${slug}/ingest/start`, { method: 'POST' })
      navigate(`/case/${slug}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start ingest')
      setRerunning(false)
    }
  }, [slug, rerunning, navigate])

  const handleDelete = useCallback(async () => {
    if (!slug || deleting) return
    setDeleting(true)
    try {
      await fetchJSON(`/cases/${slug}`, { method: 'DELETE' })
      navigate('/')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete case')
      setDeleting(false)
    }
  }, [slug, deleting, navigate])

  if (loading) {
    return (
      <div style={styles.loading}>
        <div style={styles.spinner} />
        Loading settings...
      </div>
    )
  }

  if (error && !caseData) {
    return (
      <div style={styles.errorContainer}>
        <h2 style={styles.errorTitle}>Error loading settings</h2>
        <p style={styles.errorMessage}>{error}</p>
      </div>
    )
  }

  const hasChanges = caseData && (name !== caseData.name || description !== (caseData.description || ''))

  return (
    <div style={styles.page}>
      <h1 style={styles.pageTitle}>Settings</h1>
      <p style={styles.pageDescription}>Manage your case configuration and pipeline settings.</p>

      {error && (
        <div style={styles.errorBanner}>
          {error}
          <button onClick={() => setError('')} style={styles.dismissButton}>Dismiss</button>
        </div>
      )}

      {/* General section */}
      <section style={styles.section}>
        <h2 style={styles.sectionTitle}>General</h2>
        <div style={styles.card}>
          <div style={styles.field}>
            <label style={styles.label}>Case Name</label>
            <input
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              style={styles.input}
              placeholder="Enter case name"
            />
          </div>
          <div style={styles.field}>
            <label style={styles.label}>Description</label>
            <textarea
              value={description}
              onChange={e => setDescription(e.target.value)}
              style={styles.textarea}
              placeholder="Brief description of this case"
              rows={3}
            />
          </div>
          <div style={styles.actions}>
            <button
              onClick={handleSave}
              disabled={saving || !hasChanges}
              style={{
                ...styles.primaryButton,
                opacity: saving || !hasChanges ? 0.5 : 1,
                cursor: saving || !hasChanges ? 'not-allowed' : 'pointer',
              }}
            >
              {saving ? 'Saving...' : saved ? 'Saved!' : 'Save Changes'}
            </button>
          </div>
        </div>
      </section>

      {/* Pipeline section */}
      <section style={styles.section}>
        <h2 style={styles.sectionTitle}>Pipeline Configuration</h2>
        <div style={styles.card}>
          {pipeline.length === 0 ? (
            <p style={styles.emptyPipeline}>
              No pipeline steps configured. Pipeline configuration will appear here after the first ingest run.
            </p>
          ) : (
            <div style={styles.pipelineList}>
              {pipeline.map((step, i) => (
                <div key={i} style={styles.pipelineStep}>
                  <div style={styles.stepInfo}>
                    <span style={styles.stepName}>{step.name}</span>
                    {step.description && (
                      <span style={styles.stepDescription}>{step.description}</span>
                    )}
                  </div>
                  <span
                    style={{
                      ...styles.stepBadge,
                      ...(step.enabled ? styles.stepEnabled : styles.stepDisabled),
                    }}
                  >
                    {step.enabled ? 'Enabled' : 'Disabled'}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>

      {/* Ingest section */}
      <section style={styles.section}>
        <h2 style={styles.sectionTitle}>Ingest</h2>
        <div style={styles.card}>
          <p style={styles.ingestDescription}>
            Re-run the ingest pipeline to reprocess all documents in this case.
            This will overwrite existing extracted data.
          </p>
          <button
            onClick={handleRerunIngest}
            disabled={rerunning}
            style={{
              ...styles.secondaryButton,
              opacity: rerunning ? 0.5 : 1,
              cursor: rerunning ? 'not-allowed' : 'pointer',
            }}
          >
            {rerunning ? 'Starting...' : 'Re-run Ingest'}
          </button>
        </div>
      </section>

      {/* Danger zone */}
      <section style={styles.section}>
        <h2 style={{ ...styles.sectionTitle, color: 'var(--danger)' }}>Danger Zone</h2>
        <div style={styles.dangerCard}>
          <div style={styles.dangerContent}>
            <div>
              <h3 style={styles.dangerTitle}>Delete this case</h3>
              <p style={styles.dangerDescription}>
                Permanently delete this case and all associated data. This action cannot be undone.
              </p>
            </div>
            <button
              onClick={() => setShowDeleteDialog(true)}
              style={styles.dangerButton}
            >
              Delete Case
            </button>
          </div>
        </div>
      </section>

      {/* Delete confirmation dialog */}
      {showDeleteDialog && (
        <div style={styles.overlay} onClick={() => setShowDeleteDialog(false)}>
          <div style={styles.dialog} onClick={e => e.stopPropagation()}>
            <h3 style={styles.dialogTitle}>Delete Case</h3>
            <p style={styles.dialogText}>
              This will permanently delete <strong>{caseData?.name}</strong> and all its data.
              This action cannot be undone.
            </p>
            <div style={styles.field}>
              <label style={styles.label}>
                Type <strong>{caseData?.name}</strong> to confirm
              </label>
              <input
                type="text"
                value={deleteConfirmText}
                onChange={e => setDeleteConfirmText(e.target.value)}
                style={styles.input}
                placeholder={caseData?.name}
                autoFocus
              />
            </div>
            <div style={styles.dialogActions}>
              <button
                onClick={() => {
                  setShowDeleteDialog(false)
                  setDeleteConfirmText('')
                }}
                style={styles.cancelButton}
              >
                Cancel
              </button>
              <button
                onClick={handleDelete}
                disabled={deleteConfirmText !== caseData?.name || deleting}
                style={{
                  ...styles.confirmDeleteButton,
                  opacity: deleteConfirmText !== caseData?.name || deleting ? 0.5 : 1,
                  cursor: deleteConfirmText !== caseData?.name || deleting ? 'not-allowed' : 'pointer',
                }}
              >
                {deleting ? 'Deleting...' : 'Delete Case'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  page: {
    maxWidth: 720,
  },
  pageTitle: {
    fontSize: 28,
    fontWeight: 700,
    color: 'var(--text)',
    marginBottom: 4,
  },
  pageDescription: {
    fontSize: 15,
    color: 'var(--text-muted)',
    marginBottom: 32,
  },
  loading: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    padding: 32,
    color: 'var(--text-muted)',
    fontSize: 14,
  },
  spinner: {
    width: 20,
    height: 20,
    border: '2px solid var(--border)',
    borderTopColor: 'var(--accent)',
    borderRadius: '50%',
    animation: 'spin 0.6s linear infinite',
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
  errorBanner: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '12px 16px',
    background: '#fee2e2',
    color: 'var(--danger)',
    borderRadius: 'var(--radius-md)',
    fontSize: 14,
    marginBottom: 24,
  },
  dismissButton: {
    background: 'none',
    border: 'none',
    color: 'var(--danger)',
    fontWeight: 600,
    cursor: 'pointer',
    fontSize: 13,
    padding: '4px 8px',
  },
  section: {
    marginBottom: 32,
  },
  sectionTitle: {
    fontSize: 16,
    fontWeight: 600,
    color: 'var(--text)',
    marginBottom: 12,
  },
  card: {
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-md)',
    padding: 24,
  },
  field: {
    marginBottom: 20,
  },
  label: {
    display: 'block',
    fontSize: 13,
    fontWeight: 600,
    color: 'var(--text)',
    marginBottom: 6,
  },
  input: {
    display: 'block',
    width: '100%',
    padding: '10px 12px',
    fontSize: 14,
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-sm)',
    background: 'var(--bg)',
    color: 'var(--text)',
    outline: 'none',
    fontFamily: 'inherit',
    transition: 'border-color 0.15s',
  },
  textarea: {
    display: 'block',
    width: '100%',
    padding: '10px 12px',
    fontSize: 14,
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-sm)',
    background: 'var(--bg)',
    color: 'var(--text)',
    outline: 'none',
    fontFamily: 'inherit',
    resize: 'vertical' as const,
    transition: 'border-color 0.15s',
  },
  actions: {
    display: 'flex',
    justifyContent: 'flex-end',
    gap: 12,
    marginTop: 4,
  },
  primaryButton: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
    padding: '10px 20px',
    background: 'var(--accent)',
    color: '#fff',
    border: 'none',
    borderRadius: 'var(--radius-sm)',
    fontSize: 14,
    fontWeight: 600,
    fontFamily: 'inherit',
    cursor: 'pointer',
    transition: 'all 0.15s ease',
  },
  secondaryButton: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
    padding: '10px 20px',
    background: 'var(--surface)',
    color: 'var(--text)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-sm)',
    fontSize: 14,
    fontWeight: 600,
    fontFamily: 'inherit',
    cursor: 'pointer',
    transition: 'all 0.15s ease',
  },
  // Pipeline
  emptyPipeline: {
    fontSize: 14,
    color: 'var(--text-muted)',
    fontStyle: 'italic' as const,
  },
  pipelineList: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 1,
  },
  pipelineStep: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '12px 0',
    borderBottom: '1px solid var(--border)',
  },
  stepInfo: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 2,
  },
  stepName: {
    fontSize: 14,
    fontWeight: 500,
    color: 'var(--text)',
    textTransform: 'capitalize' as const,
  },
  stepDescription: {
    fontSize: 12,
    color: 'var(--text-muted)',
  },
  stepBadge: {
    display: 'inline-block',
    padding: '3px 10px',
    fontSize: 11,
    fontWeight: 600,
    borderRadius: 'var(--radius-sm)',
  },
  stepEnabled: {
    background: '#dcfce7',
    color: 'var(--success)',
  },
  stepDisabled: {
    background: '#f3f4f6',
    color: 'var(--text-muted)',
  },
  // Ingest
  ingestDescription: {
    fontSize: 14,
    color: 'var(--text-muted)',
    lineHeight: 1.6,
    marginBottom: 16,
  },
  // Danger zone
  dangerCard: {
    background: 'var(--surface)',
    border: '1px solid #fca5a5',
    borderRadius: 'var(--radius-md)',
    padding: 24,
  },
  dangerContent: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: 24,
  },
  dangerTitle: {
    fontSize: 15,
    fontWeight: 600,
    color: 'var(--text)',
    marginBottom: 4,
  },
  dangerDescription: {
    fontSize: 13,
    color: 'var(--text-muted)',
    lineHeight: 1.5,
  },
  dangerButton: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
    padding: '10px 20px',
    background: '#fee2e2',
    color: 'var(--danger)',
    border: '1px solid #fca5a5',
    borderRadius: 'var(--radius-sm)',
    fontSize: 14,
    fontWeight: 600,
    fontFamily: 'inherit',
    cursor: 'pointer',
    transition: 'all 0.15s ease',
    whiteSpace: 'nowrap' as const,
    flexShrink: 0,
  },
  // Delete dialog
  overlay: {
    position: 'fixed' as const,
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    background: 'rgba(0, 0, 0, 0.5)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 1000,
    animation: 'lightbox-fade-in 0.15s ease',
  },
  dialog: {
    background: 'var(--surface)',
    borderRadius: 'var(--radius-lg)',
    padding: 32,
    width: '100%',
    maxWidth: 440,
    boxShadow: '0 20px 60px rgba(0, 0, 0, 0.15)',
  },
  dialogTitle: {
    fontSize: 18,
    fontWeight: 700,
    color: 'var(--text)',
    marginBottom: 12,
  },
  dialogText: {
    fontSize: 14,
    color: 'var(--text-muted)',
    lineHeight: 1.6,
    marginBottom: 20,
  },
  dialogActions: {
    display: 'flex',
    justifyContent: 'flex-end',
    gap: 12,
    marginTop: 24,
  },
  cancelButton: {
    padding: '10px 20px',
    background: 'var(--bg)',
    color: 'var(--text)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-sm)',
    fontSize: 14,
    fontWeight: 500,
    fontFamily: 'inherit',
    cursor: 'pointer',
  },
  confirmDeleteButton: {
    padding: '10px 20px',
    background: 'var(--danger)',
    color: '#fff',
    border: 'none',
    borderRadius: 'var(--radius-sm)',
    fontSize: 14,
    fontWeight: 600,
    fontFamily: 'inherit',
    cursor: 'pointer',
  },
}
