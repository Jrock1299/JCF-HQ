import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'

// Global "Editing" toggle. When on, every <EditableValue> across the app
// reveals its pencil and becomes click-to-edit. Persisted so it survives
// reloads. Kept deliberately tiny — one boolean + a toggle.
interface EditModeCtx {
  editing: boolean
  toggle: () => void
}

const Ctx = createContext<EditModeCtx>({ editing: false, toggle: () => {} })
const KEY = 'jcf-edit-mode'

export function EditModeProvider({ children }: { children: ReactNode }) {
  const [editing, setEditing] = useState<boolean>(() => {
    try {
      return localStorage.getItem(KEY) === '1'
    } catch {
      return false
    }
  })

  useEffect(() => {
    try {
      localStorage.setItem(KEY, editing ? '1' : '0')
    } catch {
      /* ignore */
    }
    // expose on <html> so CSS/other components can react if needed
    document.documentElement.setAttribute('data-editing', editing ? '1' : '0')
  }, [editing])

  const toggle = useCallback(() => setEditing((e) => !e), [])

  return <Ctx.Provider value={{ editing, toggle }}>{children}</Ctx.Provider>
}

export function useEditMode(): EditModeCtx {
  return useContext(Ctx)
}
