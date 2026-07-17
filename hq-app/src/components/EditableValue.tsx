import { useState, type CSSProperties, type ReactNode } from 'react'
import { useEditMode } from '../edit/EditModeContext'

// ── Override layer ────────────────────────────────────────────────────
// Edits are written to localStorage immediately (instant + offline-safe
// fallback) AND POSTed to /hq/edit/<file> for cross-device persistence.
// On display, a localStorage override wins over the fetched value so an
// edit sticks even if the :8900 storage server is unreachable.
const OVR = 'hq-edit:'

export function loadOverride(file: string, path: string): any {
  try {
    const raw = localStorage.getItem(`${OVR}${file}:${path}`)
    return raw == null ? undefined : JSON.parse(raw)
  } catch {
    return undefined
  }
}

function saveOverride(file: string, path: string, value: any) {
  try {
    localStorage.setItem(`${OVR}${file}:${path}`, JSON.stringify(value))
  } catch {
    /* ignore */
  }
}

async function persist(file: string, path: string, value: any): Promise<boolean> {
  try {
    const res = await fetch(`/hq/edit/${file}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, value }),
    })
    return res.ok
  } catch {
    return false
  }
}

interface Props {
  file: string // e.g. 'blade_balance.json'
  path: string // dot path e.g. 'balance' or 'records.0.entry_price'
  value: number | string | null | undefined
  type?: 'number' | 'text'
  display?: (v: number | string | null | undefined) => ReactNode
  className?: string
  style?: CSSProperties
  inputWidth?: number
}

// Inline, in-place editable value. In view mode renders display(value).
// In edit mode, shows a hover pencil; click → inline input; Enter/blur saves,
// Esc cancels.
export default function EditableValue({
  file,
  path,
  value,
  type = 'text',
  display,
  className,
  style,
  inputWidth = 120,
}: Props) {
  const { editing } = useEditMode()
  const [override, setOverride] = useState<any>(() => loadOverride(file, path))
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState('')

  const resolved = override !== undefined ? override : value
  const render = (v: any): ReactNode => (display ? display(v) : v == null || v === '' ? '--' : String(v))

  if (!editing) {
    return (
      <span className={className} style={style}>
        {render(resolved)}
      </span>
    )
  }

  function commit() {
    let v: any = draft
    if (type === 'number') {
      const trimmed = draft.trim()
      v = trimmed === '' ? 0 : Number(trimmed)
      if (Number.isNaN(v)) v = 0
    }
    setOverride(v)
    saveOverride(file, path, v)
    persist(file, path, v)
    setOpen(false)
  }

  if (open) {
    return (
      <input
        autoFocus
        type={type === 'number' ? 'number' : 'text'}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit()
          if (e.key === 'Escape') setOpen(false)
        }}
        onBlur={commit}
        className={`mono ${className || ''}`}
        style={{
          width: inputWidth,
          maxWidth: '100%',
          padding: '2px 8px',
          borderRadius: 7,
          background: 'var(--input-bg)',
          border: '0.5px solid var(--gold-border)',
          color: 'var(--text-hi)',
          outline: 'none',
          font: 'inherit',
          ...style,
        }}
      />
    )
  }

  return (
    <span
      className={className}
      style={{ ...style, position: 'relative', display: 'inline-flex', alignItems: 'center', gap: 6 }}
    >
      {render(resolved)}
      <button
        type="button"
        className="edit-pencil"
        title="Edit"
        onClick={(e) => {
          e.stopPropagation()
          setDraft(resolved == null ? '' : String(resolved))
          setOpen(true)
        }}
      >
        ✎
      </button>
    </span>
  )
}
