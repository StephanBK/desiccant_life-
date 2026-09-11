import { useState } from 'react'
import { TIPS } from './tips.js'

// Info control. Click (or Enter) expands a three-part note under the field:
// what it is, how the model uses it, where the number comes from. Inline
// expansion instead of a floating popover so nothing is clipped by the
// scrolling rail and it works on touch.
export function Tip({ id, inline }) {
  const [open, setOpen] = useState(false)
  const t = TIPS[id]
  if (!t) return null
  return (
    <>
      <button type="button" className="tip" aria-expanded={open} aria-label={`About ${id}`} title="What, how it is used, source" onClick={(e) => { e.preventDefault(); setOpen((o) => !o) }}>i</button>
      {open && (
        <div className={`tipbox${inline ? ' inline' : ''}`} role="note">
          <p><b>What.</b> {t.what}</p>
          <p><b>How it is used.</b> {t.how}</p>
          <p><b>Source.</b> {t.src}</p>
        </div>
      )}
    </>
  )
}
