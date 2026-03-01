export interface PipelineStep {
  id: string
  label: string
  description: string
  default_enabled: boolean
  requires_extra: string | null
  depends_on: string[]
  config_keys: string[]
}

interface Props {
  step: PipelineStep
  enabled: boolean
  onToggle: (id: string, enabled: boolean) => void
  dependenciesMet: boolean
}

export default function PipelineToggle({ step, enabled, onToggle, dependenciesMet }: Props) {
  const disabled = !dependenciesMet
  const active = enabled && dependenciesMet

  return (
    <div
      style={{
        padding: 20,
        background: disabled ? '#f9fafb' : active ? '#f0fdf4' : '#fff',
        border: `1px solid ${active ? '#86efac' : '#e5e7eb'}`,
        borderRadius: 10,
        opacity: disabled ? 0.6 : 1,
        transition: 'all 0.15s ease',
        cursor: disabled ? 'not-allowed' : 'pointer',
      }}
      onClick={() => {
        if (!disabled) onToggle(step.id, !enabled)
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 600, fontSize: 15, color: '#111827', marginBottom: 4 }}>
            {step.label}
          </div>
          <div style={{ fontSize: 13, color: '#6b7280', lineHeight: 1.5 }}>
            {step.description}
          </div>
          {step.requires_extra && (
            <div
              style={{
                marginTop: 8,
                fontSize: 12,
                color: '#9333ea',
                background: '#faf5ff',
                padding: '4px 8px',
                borderRadius: 4,
                display: 'inline-block',
              }}
            >
              requires: pip install 'casestack[{step.requires_extra}]'
            </div>
          )}
          {disabled && step.depends_on.length > 0 && (
            <div style={{ marginTop: 8, fontSize: 12, color: '#ef4444' }}>
              Requires: {step.depends_on.join(', ')}
            </div>
          )}
        </div>
        <div
          style={{
            width: 44,
            height: 24,
            borderRadius: 12,
            background: active ? '#22c55e' : '#d1d5db',
            position: 'relative',
            transition: 'background 0.15s ease',
            flexShrink: 0,
            marginTop: 2,
          }}
        >
          <div
            style={{
              width: 20,
              height: 20,
              borderRadius: 10,
              background: '#fff',
              position: 'absolute',
              top: 2,
              left: active ? 22 : 2,
              transition: 'left 0.15s ease',
              boxShadow: '0 1px 3px rgba(0,0,0,0.15)',
            }}
          />
        </div>
      </div>
    </div>
  )
}
